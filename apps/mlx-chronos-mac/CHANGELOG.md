# MLX Chronos for macOS — Changelog

The macOS app is versioned independently of the Python CLI. This history starts
with the first public app baseline; private prototypes are not earlier releases.

## Unreleased

- Allow local tests with external CLI installations lacking Foundation thermal
  observations. Keep thermal support in verified app-managed installations and
  public-result requirements; energy still requires macmon.
- Validate and pass only the server ports used by a command. File comparisons,
  history and submission checks are independent of unused port fields; full
  environment/engine inventories still check every configured server port.
- Show protocol-change notices when loading valid saved configurations. New
  measurements use the selected CLI's current method; no test starts on load.
  Label similar cold/cached timings as a cache observation.
- Separate serving/runtime version evidence from locally detected client versions
  in Environment. Keep older CLI snapshots compatible, label unavailable
  provenance, and never substitute packages from another Python for a server version.
  Label server-process package metadata as indirect installation evidence.
- Diagnose inconsistent historical progress when displaying saved trial charts;
  mark an associated sustained warning as unverified while preserving saved
  trial values and means. Carry indirect/client-only version cautions into this view.

- Preserve process termination escalation when Stop races with launch, and ignore
  stale timeout callbacks after the runner has moved on to another process.
- Enforce catalog/artifact byte limits during transfer. Save resolved dependency
  versions after installation and reuse them for repairs of the same approved
  release on the same Python version. New releases resolve a separate environment.
- Respect boolean defaults from the CLI contract and report when a true-default
  flag cannot be turned off through the exposed command interface.

- Show trial charts below a single selected standard benchmark in **Results**:
  cold/cached TTFT in milliseconds and request/decode throughput in tok/s.
  Read the saved samples and optional means locally, preserve trial order,
  identify missing measurements, and explain recorded warnings without inferring
  causes. Support point inspection with pointer and keyboard controls, native
  light/dark styling, and refresh after file changes. The same viewer serves all
  engines and older files with available samples; browsing does not validate
  schema/seals or public eligibility. No CLI or protocol change is required.
- Add **Save configuration…** and **Load configuration…** for standard `run`
  tests when supported by the selected CLI. Resolve and validate files through
  that CLI; save/load never start inference or require thermal support. Show
  loaded values before an explicit test start, preserve local result paths and
  contributor attribution, and reject incompatible settings/file formats. Older
  CLIs retain the existing form without these optional actions.
- Show the selected CLI's expanded repeat summaries and optional two-series
  comparison through the existing command form. Label and validate the number
  of A files; keep **Compare selected** in ordinary per-file mode. The optional
  integer flag and positional files also fit app 0.2.0's existing dynamic form.
  Statistics remain in the CLI; no duplicated calculation or interface-version
  bump. Requires a CLI containing these Unreleased changes.
- Explain pairwise, metric-specific comparison cautions, incomplete metadata
  and estimated/unavailable percentages. Use the selected CLI's comparison
  logic; the refined behavior requires a CLI containing the Unreleased changes.
- Support `ddalcu/mlx-serve` through a CLI containing the new adapter. Keep
  engine choices and all test commands driven by the selected CLI; read local
  loaded-model inventory without inference and show the separate desktop app
  version when available. Tests accept only local MLX safetensors; all GGUF
  paths and llama.cpp/ds4 are rejected through the shared CLI validation.
  The approved CLI 0.5.1 remains unchanged until a new
  compatible release is published and approved.

## [0.2.0] — 2026-10-04

**App 0.2.0, build 4** downloads Python and the CLI independently. The initial
approved CLI is **0.5.1**; CLI updates do not require a new app DMG when their
interface remains compatible.

- Remove the embedded CLI wheel. At launch, download private Python and the
  newest published CLI explicitly approved by the compatibility catalog.
- Gate updates on app/interface versions, required capabilities, command support,
  SHA-256 checks and post-install CLI/Foundation verification. Unknown releases
  remain excluded; failed updates preserve the active environment.
- Keep versioned environments and a verified rollback action. External Python,
  source checkouts and package-manager installations are preserved.
- Add independent app-release notifications linking to the official download.
  The app does not replace its own bundle automatically.
- Add fresh standalone bootstrap, rollback and failed-update regressions in CI.
- Select the newest results by recorded date before applying the visible
  5,000-file limit, and scan all immediate diagnostic subfolders.
- Reuse unchanged display summaries during refresh and cooperatively cancel
  superseded scans. Report incomplete folder scans in the Results view.
- Verify the full Release build and compatibility with both the approved
  published and current-source CLI in CI.
- Document benchmark protocol revision numbers and link their explanation from
  the app user guide and public leaderboard.

## [0.1.0] — 2026-10-02

Initial release: **0.1.0, build 3**, bundling **mlx-chronos 0.5.0**.
Distributed as a free Apple Silicon DMG with a local/ad-hoc signature;
**not Developer ID signed or notarized by Apple**.

Distribution maintenance: the public DMG filename was simplified to
`MLXChronos-0.1.0-arm64.dmg`, with a matching renamed checksum file. The DMG
content, internal build 3 and published source tag are unchanged.

### Benchmarking and diagnostics

- Native forms for all 13 non-interactive CLI commands. Environment and test
  forms replace the terminal wizard; options/defaults come from the selected
  CLI's actual command contract.
- Standard baseline and sustained benchmarks: cold/cached TTFT, request
  throughput, sustained progress and degradation, system RAM peak/baseline/
  delta, swap growth, engine RSS and Foundation thermal conditions.
- Standard-profile public-readiness preflight, integrity-sealed JSON,
  JSON/Markdown output, output-token controls, HTTP connection mode, RAM
  sampling, cooldown, notes, declared server settings and opt-in contributor
  attribution.
- Sealed server-setting provenance separates API observations from unverified
  operator declarations. Runtime/cache evidence and server finish reasons are
  preserved where supported, without treating missing evidence as confirmation.
- Independent complete-run repetitions with separate results and a run summary.
- Local engine matrix with explicit engine-to-model mappings, all-engine
  preflight, seeded randomized/rotating order, cooldown and condition/failure
  recording. No automatic alias-to-artifact identity merging.
- Local context-length diagnostics with distinct bucket/trial prompts and
  conditional server-reported input-token counts.
- Local concurrency diagnostics with unique per-request/per-wave prompts,
  separate warm-up, cache-clear evidence, aggregate throughput and latencies.
- Experimental local macmon whole-system energy diagnostics with separate
  no-request and active phases, sampling traces and quality/coverage gates.
- Six supported engine adapters: oMLX, Rapid-MLX, vllm-mlx, mlx-lm, Ollama with
  MLX and experimental LM Studio. LM Studio verifies both MLX model
  compatibility and the runtime answering inference, rejecting GGUF/llama.cpp.

### Environment and installation

- Existing Python/CLI discovery, explicit interpreter or source-checkout
  selection, runtime identity/details and persisted active installation.
- Checksummed bundled CLI wheel; isolated app-managed setup/repair using an
  existing compatible Python, mandatory thermal dependency and post-install
  verification. No bundled Python, engines or model weights.
- Confirmation-gated CLI updates and targeted removal of eligible external
  pip-owned copies, protecting the app-managed copy, inherited packages, source
  checkouts and protected/externally managed environments. Python, dependencies,
  models and results are not removed.
- Mac identity, RAM, macOS/architecture, thermal state, power source and Low
  Power Mode; engine installation/version, endpoint/port, reachability and
  available-versus-verified-loaded model evidence. Explicit port overrides.
- Setup diagnosis, model validation, engine/model listing and update checks.

### Results and application behavior

- Configurable result destinations, custom-folder routing, JSON browsing and
  complete recorded-data inspection. Recognizes benchmark, context,
  concurrency, energy and matrix reports; chronological sorting supports
  matrix `created_at` and file-date fallback.
- Sealed-result comparison with an explicit reference and non-homogeneous
  comparison warnings; local benchmark history.
- Public-eligibility validation without sending by default. Explicit review
  and confirmation for full-JSON inbox submission, optional reply email and
  contributor attribution kept separate, with no maintainer misattribution.
- Actual-command preview, validated literal arguments without shell dispatch,
  and command-specific defaults/reset and grouped additional settings.
- One-operation-at-a-time execution, bounded streaming output, concurrent
  stdout/stderr draining, timeout and interruption handling, and cleanup limited
  to owned subprocesses. Quit waits for active-operation cleanup.
- Native Environment, Tests, Results and Activity sections; restrained
  blue/grey light/dark styling, compact aligned header, transparent Chronos
  sidebar logo and light/dark app icons with smooth black dark background.
- Standalone English user guide, shared contribution instructions and reusable
  Python/Swift regression tests. The app source uses the repository's Apache
  2.0 license; bundled runtime provenance and licenses are included.
- Drag-to-Applications DMG, SHA-256 checksum, and plain-text first-launch
  instructions for manual authorization of this non-notarized build.

The app uses the published CLI's measurement fixes and validation rules rather
than reimplementing them. For the CLI's full change history and the separate
web leaderboard (including exports/charts), see the
[CLI changelog](../../CHANGELOG.md). Web features are not bundled app controls.

[0.2.0]: https://github.com/igurss/mlx-chronos/releases/tag/app-v0.2.0
[0.1.0]: https://github.com/igurss/mlx-chronos/releases/tag/app-v0.1.0
