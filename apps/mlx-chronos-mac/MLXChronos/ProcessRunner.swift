import Darwin
import Foundation

struct ProcessResult: Sendable {
    var exitCode: Int32
    var stdout: String
    var stderr: String
    var cancelled: Bool
    var timedOut: Bool
    var outputTruncated: Bool
    var succeeded: Bool { exitCode == 0 && !cancelled && !timedOut && !outputTruncated }
}

/// Owns one process tree. Pipes drain concurrently, including during stop.
final class ProcessRunner: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var cancelled = false
    private var timedOut = false
    private var terminatingProcess: Process?
    private let launch: @Sendable (Process) throws -> Void

    init(launch: @escaping @Sendable (Process) throws -> Void = { try $0.run() }) {
        self.launch = launch
    }

    func run(
        executable: String, arguments: [String], directory: URL,
        environment: [String: String], timeout: TimeInterval?,
        onOutput: @escaping @Sendable (String) -> Void = { _ in }
    ) async -> ProcessResult {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let child = Process()
                let out = Pipe(), err = Pipe()
                let capture = OutputCapture()
                let readers = DispatchGroup()
                child.executableURL = URL(fileURLWithPath: executable)
                child.arguments = arguments
                child.currentDirectoryURL = directory
                child.environment = environment
                child.standardInput = FileHandle.nullDevice
                child.standardOutput = out
                child.standardError = err
                self.lock.lock()
                self.process = child
                let wasCancelled = self.cancelled
                self.lock.unlock()
                if wasCancelled {
                    self.lock.lock(); self.process = nil; self.lock.unlock()
                    continuation.resume(returning: ProcessResult(exitCode: -1, stdout: "", stderr: "Cancelled", cancelled: true, timedOut: false, outputTruncated: false))
                    return
                }
                do {
                    try self.launch(child)
                } catch {
                    self.lock.lock(); self.process = nil; self.lock.unlock()
                    continuation.resume(returning: ProcessResult(exitCode: -1, stdout: "", stderr: error.localizedDescription, cancelled: false, timedOut: false, outputTruncated: false))
                    return
                }
                self.lock.lock(); let cancelAfterLaunch = self.cancelled; self.lock.unlock()
                if cancelAfterLaunch { self.beginTermination(child) }
                for (pipe, isError) in [(out, false), (err, true)] {
                    readers.enter()
                    // The user-initiated waiter depends on these readers.
                    // Matching their priority avoids a priority inversion.
                    DispatchQueue.global(qos: .userInitiated).async {
                        var pending = Data()
                        let handle = pipe.fileHandleForReading
                        let fd = handle.fileDescriptor
                        _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
                        var bytes = [UInt8](repeating: 0, count: 16_384)
                        while !capture.shouldStopReading {
                            var event = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
                            let ready = Darwin.poll(&event, 1, 100)
                            if ready == 0 { continue }
                            if ready < 0 { if errno == EINTR { continue }; break }
                            let count = Darwin.read(fd, &bytes, bytes.count)
                            if count == 0 { break }
                            if count < 0 { if errno == EAGAIN || errno == EINTR { continue }; break }
                            let data = Data(bytes.prefix(count))
                            capture.append(data, isError: isError)
                            pending.append(data)
                            if let boundary = pending.lastIndex(where: { $0 == 10 || $0 == 13 }) {
                                let end = pending.index(after: boundary)
                                onOutput(String(decoding: pending[..<end], as: UTF8.self))
                                pending.removeSubrange(..<end)
                            } else if pending.count > 16_384 {
                                onOutput(String(decoding: pending, as: UTF8.self))
                                pending.removeAll(keepingCapacity: true)
                            }
                        }
                        if !pending.isEmpty { onOutput(String(decoding: pending, as: UTF8.self)) }
                        try? handle.close()
                        readers.leave()
                    }
                }
                let deadline = timeout.map { _ in DispatchWorkItem { self.stop(dueToTimeout: true, expectedProcess: child) } }
                if let timeout, let deadline {
                    DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: deadline)
                }
                child.waitUntilExit()
                deadline?.cancel()
                if readers.wait(timeout: .now() + 3) == .timedOut {
                    // Do not signal a group after its leader has been reaped:
                    // PID reuse could make that group belong to another app.
                    capture.stopReading()
                    readers.wait()
                }
                self.lock.lock()
                let cancelled = self.cancelled, timedOut = self.timedOut
                self.process = nil
                self.terminatingProcess = nil
                self.lock.unlock()
                let values = capture.snapshot()
                continuation.resume(returning: ProcessResult(
                    exitCode: child.terminationStatus, stdout: values.0, stderr: values.1,
                    cancelled: cancelled, timedOut: timedOut, outputTruncated: values.2
                ))
            }
        }
    }

    func stop(dueToTimeout: Bool = false, expectedProcess: Process? = nil) {
        lock.lock()
        if let expectedProcess, process !== expectedProcess { lock.unlock(); return }
        if dueToTimeout { timedOut = true } else { cancelled = true }
        let child = process
        lock.unlock()
        guard let child else { return }
        beginTermination(child)
    }

    private func beginTermination(_ child: Process) {
        lock.lock()
        guard process === child, child.isRunning, terminatingProcess !== child else {
            lock.unlock(); return
        }
        terminatingProcess = child
        lock.unlock()
        signal(child, SIGINT)
        DispatchQueue.global().asyncAfter(deadline: .now() + 3) {
            guard child.isRunning else { return }
            self.signal(child, SIGTERM)
            DispatchQueue.global().asyncAfter(deadline: .now() + 2) {
                if child.isRunning { self.signal(child, SIGKILL) }
            }
        }
    }

    private func signal(_ child: Process, _ signal: Int32) {
        let pid = child.processIdentifier
        guard pid > 0 else { return }
        if getpgid(pid) == pid { _ = Darwin.kill(-pid, signal) }
        else if child.isRunning { _ = Darwin.kill(pid, signal) }
    }
}

private final class OutputCapture: @unchecked Sendable {
    private let lock = NSLock()
    private var stdout = Data(), stderr = Data()
    private var truncated = false
    private var stopReaders = false
    private let limit = 4 * 1024 * 1024
    var shouldStopReading: Bool {
        lock.lock(); defer { lock.unlock() }; return stopReaders
    }
    func stopReading() {
        lock.lock(); defer { lock.unlock() }; stopReaders = true; truncated = true
    }
    func append(_ data: Data, isError: Bool) {
        lock.lock(); defer { lock.unlock() }
        let existing = isError ? stderr.count : stdout.count
        let room = max(0, limit - existing)
        if data.count > room { truncated = true }
        if isError { stderr.append(data.prefix(room)) }
        else { stdout.append(data.prefix(room)) }
    }
    func snapshot() -> (String, String, Bool) {
        lock.lock(); defer { lock.unlock() }
        return (String(decoding: stdout, as: UTF8.self), String(decoding: stderr, as: UTF8.self), truncated)
    }
}
