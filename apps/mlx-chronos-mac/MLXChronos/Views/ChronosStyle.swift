import AppKit
import SwiftUI

/// Shared presentation only: no command, discovery or measurement state lives here.
enum ChronosStyle {
    static let headerHeight: CGFloat = 96
    static let headerContentTop: CGFloat = 30
    static let headerTitleLowering: CGFloat = 6
    static let pageTitle = Font.system(size: 28, weight: .semibold)
    static let sectionTitle = Font.system(size: 18, weight: .semibold)
    static let body = Font.system(size: 14)
    static let label = Font.system(size: 13, weight: .medium)
    static let help = Font.system(size: 12)
    static let code = Font.system(size: 12, design: .monospaced)

    static let accent = color(light: (0.16, 0.38, 0.66), dark: (0.46, 0.68, 0.94))
    // Prominent buttons need white-on-blue contrast; link/status accents can
    // remain lighter in dark mode without washing out the button label.
    static let primaryButton = color(light: (0.16, 0.38, 0.66), dark: (0.23, 0.46, 0.75))
    static let canvas = color(light: (0.95, 0.96, 0.98), dark: (0.07, 0.08, 0.10))
    static let surface = color(light: (0.99, 0.995, 1.0), dark: (0.10, 0.12, 0.15))
    static let inset = color(light: (0.94, 0.95, 0.97), dark: (0.08, 0.10, 0.13))
    static let rule = color(light: (0.82, 0.85, 0.89), dark: (0.22, 0.26, 0.32))
    static let secondary = color(light: (0.34, 0.39, 0.46), dark: (0.67, 0.72, 0.80))
    static let consoleBackground = adaptive(light: (0.97, 0.98, 0.99), dark: (0.065, 0.08, 0.105))

    private static func color(light: (Double, Double, Double), dark: (Double, Double, Double)) -> Color {
        Color(nsColor: adaptive(light: light, dark: dark))
    }

    private static func adaptive(light: (Double, Double, Double), dark: (Double, Double, Double)) -> NSColor {
        NSColor(name: nil) { appearance in
            let rgb = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
            return NSColor(srgbRed: rgb.0, green: rgb.1, blue: rgb.2, alpha: 1)
        }
    }
}

struct ChronosCard<Content: View>: View {
    var title: String
    var subtitle: String?
    var content: Content

    init(_ title: String, subtitle: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.subtitle = subtitle
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            VStack(alignment: .leading, spacing: 8) {
                Text(title).font(ChronosStyle.sectionTitle).accessibilityAddTraits(.isHeader)
                if let subtitle { ChronosHelp(subtitle) }
            }
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(22)
        .background(ChronosStyle.surface, in: RoundedRectangle(cornerRadius: 14))
        .overlay {
            RoundedRectangle(cornerRadius: 14).strokeBorder(ChronosStyle.rule.opacity(0.65), lineWidth: 1)
                .allowsHitTesting(false)
        }
    }
}

struct ChronosHelp: View {
    var text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text)
            .font(ChronosStyle.help)
            .foregroundStyle(ChronosStyle.secondary)
            .lineSpacing(3)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
    }
}

/// The complete disclosure label is a keyboard-accessible hit target, not
/// just the small native chevron. The DisclosureGroup still owns its state.
struct ChronosDisclosureStyle: DisclosureGroupStyle {
    var identifier: String

    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Button { configuration.isExpanded.toggle() } label: {
                HStack(spacing: 8) {
                    Image(systemName: configuration.isExpanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(ChronosStyle.secondary)
                        .frame(width: 12)
                        .accessibilityHidden(true)
                    configuration.label
                    Spacer(minLength: 0)
                }
                .padding(.vertical, 10)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier(identifier)
            if configuration.isExpanded { configuration.content }
        }
    }
}

/// Keep related actions together, but stack them when the window cannot fit a row.
struct ChronosActions<Content: View>: View {
    var content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 10) { content }
            VStack(alignment: .leading, spacing: 10) { content }
        }
        .font(ChronosStyle.label)
        .controlSize(.regular)
    }
}

struct ChronosStatus: View {
    var text: String
    var emphasized = false
    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(emphasized ? ChronosStyle.accent : ChronosStyle.secondary)
            .padding(.horizontal, 10).padding(.vertical, 5)
            .background(emphasized ? ChronosStyle.accent.opacity(0.12) : ChronosStyle.inset,
                        in: Capsule())
    }
}
