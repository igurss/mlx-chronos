# MLX Chronos for macOS — User guide

App version: **0.2.0 (next release)**. Python and mlx-chronos are downloaded independently.
The published 0.1.0 app retains its original bundled setup; this guide describes the new app source.

The app configures and runs the Python CLI. It does not implement a separate
measurement method. Available options and defaults come from the selected CLI installation.

## First run

### Install and authorize the app

Download the DMG and its matching `.sha256` file from the
[official app release](https://github.com/igurss/mlx-chronos/releases).
Open the DMG, drag `MLXChronos.app` to Applications, and launch the installed
copy. Eject the DMG after installation.

**This free build is locally/ad-hoc signed, not Developer ID signed or Apple
notarized.** macOS may block the first launch. Only if you trust the official
download and its integrity, first try opening the app, then use **System
Settings → Privacy & Security → Open Anyway** and confirm **Open**, when
available. This authorizes the individual app, not all downloaded software.
Managed Macs may prevent this exception. Do not disable Gatekeeper or remove
quarantine attributes. If the app is reported damaged or malicious, stop and
verify the package rather than ignoring the warning.
[Apple's explanation](https://support.apple.com/en-us/102445).

Optional checksum verification from the folder containing both downloads:

```bash
shasum -a 256 -c MLXChronos-0.2.0-arm64.dmg.sha256
```

This detects an altered download relative to the published checksum; it is not
Apple identity verification or notarization. The download filename omits the
internal app build number; check the release page for the current asset names.
Installation/launch instructions
are also included as a text file inside the DMG.

### Prepare the measurement environment

You need an Apple Silicon Mac with macOS 14 or later and a supported inference
engine. On first launch the app downloads a private Python interpreter and a
verified compatible mlx-chronos release with Foundation thermal support.
Initial preparation requires Internet. Python already on your Mac is preserved.
Engine installation, server startup and model downloads remain separate.

1. Open the app and wait for automatic environment preparation in **Environment**.
2. If preparation fails or you disabled launch checks, use **Check / prepare
   compatible CLI**. Activity contains the installation output.
3. Start your engine's server and make a suitable model available there.
4. Use **Refresh Mac and engines** to check the server and its model IDs.
5. In **Tests**, choose **Standard benchmark**, the engine and its exact model
   ID. Leave numeric overrides blank for the profile defaults. Choose
   **Start test**.
6. Open **Results** to inspect the saved JSON. Sharing is optional and separate
   from running a test.

For engine setup and default ports, see the repository's
[contributor guide](../../CONTRIBUTING.md#2-start-an-engine-server).

## Environment

### Python and CLI installations

The app-managed copy is the default. **Active installation** lets you select
a detected installed copy instead. Detection checks common installation
locations, not every directory on your Mac. Use **Add Python / environment…**
for a specific executable or **Add source checkout…** for a local CLI project.
Source use is explicit; a working directory cannot silently replace the CLI.

The selected installation reports Python version and architecture, CLI version
and location, and verified thermal support. Changing installations resets form
drafts. An unavailable selected installation is reported rather than silently
replaced.

- **Check and update the app-managed CLI at launch** is enabled by default.
  Checks run at each launch and install only approved compatible releases.
  Unsupported or unknown releases are skipped with a visible explanation.
- **Check / prepare compatible CLI** checks updates and prepares the private
  copy if needed. It does not upgrade external Python environments.
- **Repair private CLI** rebuilds a separate private copy and switches to it only
  after verification. The previous copy remains available.
- **Restore previous CLI** verifies and activates the previous copy, then pauses
  automatic CLI updates. Re-enable launch updates when ready.
- **Use app-managed CLI instead** prepares/selects the private copy when browsing
  an external installation.
- **Remove this mlx-chronos copy** removes only the selected, eligible pip-owned
  CLI package after confirmation and a fresh ownership check. It does not
  remove Python, other dependencies, models or results. The app-managed copy,
  source checkouts, inherited packages and protected/externally managed
  installations cannot be removed this way.

### Mac and engines

**Refresh Mac and engines** reads Mac identity, unified memory, macOS,
architecture, thermal state, power source and Low Power Mode. It reports engine
installation/version evidence, server reachability, endpoints/ports and model
IDs. Refresh does not run inference or load models. Installed, reachable and
model-loaded are different states; loaded status is shown only when verified
by the server API. A port override tells Chronos where to connect; it does not
reconfigure or start the server.

Supported engines: oMLX, Rapid-MLX, vllm-mlx, mlx-lm, Ollama with MLX, and
experimental MLX-only LM Studio. For LM Studio, both the model's compatibility
and the runtime answering a probe must confirm MLX. GGUF/llama.cpp is rejected;
`safetensors` alone does not prove the runtime. See the
[LM Studio gate](../../docs/methodology.md#lm-studio-mlx-only-gate).

### Checks and maintenance

| Action / CLI command | Purpose and options |
| --- | --- |
| Setup diagnosis / `doctor` | Diagnose the Mac and setup. Optional `--engine`, `--model`, `--model-url` and `--publishable` deepen engine/public-readiness checks. A model requires an engine and may trigger inference. |
| Engine and model check / `validate` | Check the selected engine; optional `--model` performs a small completion and can trigger server-side model loading. Default `--engine`: omlx. |
| List models / `models` | List server model IDs for `--engine` (default omlx). Does not download models or certify every listed model as MLX. |
| List engines / `engines` | List supported engines and detected status. Does not install them. |
| Update mlx-chronos / `upgrade` | In the app, checks/prepares the newest approved compatible private CLI. External installations and engines are preserved. The terminal CLI retains its own upgrade behavior. |

Compatibility uses an explicit interface version, minimum app version,
required capabilities and supported commands. Python/package compatibility
alone is insufficient. A failed download, checksum or verification keeps the
active copy. Installed copies remain usable offline; the first installation
requires Internet. CLI versions without verified compatibility metadata are
not installed automatically.

The app separately checks GitHub app releases. **App VERSION available — open
download page** opens the official release page; replacing the app remains a
manual action. Updating the CLI does not update the app.

## Tests

### Common configuration

Blank optional fields delegate to the selected CLI's defaults. Required fields
must be filled. **Additional settings** contains less common options; collapsing
it does not clear them. Use decimal points, not commas, for decimal numbers.
Use file pickers or literal absolute paths; shell abbreviations are not expanded.
For repeated entries, use one item per line.

**Show command** previews the actual CLI arguments without starting a test.
Execution does not go through a shell. **Restore CLI defaults** resets that
command's draft, including its output folder and validation-only sharing.
Drafts last for the current app session; they are not saved presets.

| Field / flag | Meaning |
| --- | --- |
| Engine / `--engine` | The server to measure, not a model format. |
| Exact model ID / `--model` | The literal ID accepted by that engine. **Use detected model** fills it without loading or validating the model. Changing engines clears the previous ID. |
| Quantization / format / `--quantization` | Declares the actual weights' quantization/format; it does not convert them. Run/matrix default: 4bit. |
| Model reference URL / `--model-url` | Full reference to the relevant model artifact, normally Hugging Face. Required for public results. Keep revision/file paths when significant; matching repositories or aliases do not prove identical weights. |
| Result folder / `--output-dir` | Save destination. A blank test folder uses the app's default, with separate subfolders for diagnostics. |
| Report format / `--format` | `json`, `markdown` or `all`, where supported. Results browsing and public validation require JSON. |
| Trials / `--trials` | Trials within one session (1–30), not complete repeated sessions. |
| Maximum output tokens / `--max-tokens` | Requested output-token ceiling, not context size. A model can stop earlier. |
| Minimum output tokens / `--min-tokens` | Optional engine-dependent output minimum; must not exceed the maximum. Overrides are not part of the standard public protocol. |
| RAM sampling interval / `--ram-sample-interval` | Sampling period in seconds, default 0.05. Smaller intervals add sampling overhead. |
| HTTP connections / `--connection-mode` | `persistent` (default) reuses the client; `per_request` adds separate connections. Public protocol requires persistent connections. |
| Notes / `--notes` | Recorded annotation, not an inference prompt or server setting. |
| Contributor handle / `--submitted-by` | Optional public attribution, not authenticated identity; distinct from the submission email. |

Only options supported by the chosen command are displayed. The terminal's
interactive `wizard` is replaced by these forms rather than launched inside
the app.

### Standard benchmark — `run`

Measures cold and cached time to first token (TTFT), request throughput and
memory. `--profile baseline` defaults to 5 trials and 100 output tokens;
`sustained` defaults to 1 trial and 1000 tokens, with throughput-progress samples
to observe late-run degradation. Cold TTFT is not model download/load time.

| Option | Purpose |
| --- | --- |
| Public-ready settings / `--publishable` | Apply public-profile preflight and configuration requirements. Requires model URL, standard profile settings, JSON, persistent connections and Low Power Mode off. Does not send anything or guarantee final eligibility. |
| Complete repetitions / `--repeat` | Run 1–20 independent complete sessions; default 1. Each has its own sealed result. The cross-run summary does not replace those results. |
| Cooldown / `--cooldown-seconds` | Minimum elapsed time since the previous JSON in the output folder; default 0. Not a temperature target or a pause after every request. |
| Extra model access check / `--preflight` | Additional unmeasured access check before measurements; may load/warm the model. |
| Declared server settings / `--engine-opt` | One unique `KEY=VALUE` per line, recorded as an unverified operator declaration. Does not configure the server. |

For public results, keep numeric overrides blank, enable **Public-ready
settings**, supply the model URL, and then validate the saved file. See the
[public protocol rules](../../README.md#leaderboard-rules).

### Multiple engines — `matrix`

Organizes local engine runs with preflight for every mapping, randomized initial
order, rotating positions between rounds, cooldown and recorded conditions.

- **Engine → model mapping** (`--engine-model`): one `ENGINE=MODEL` per line,
  with no duplicate engine. **Add detected engine/model** can fill a mapping.
- **Complete engine sweeps** (`--rounds`): 1–20; default is the engine count,
  balancing order positions over the sweeps.
- **Order seed** (`--seed`): optional integer; the generated/selected seed is
  recorded for reproducibility of order, not Mac conditions.
- **Cooldown** (`--cooldown-seconds`): default 120 seconds after preflight and
  between complete runs. Zero is useful for smoke tests, not thermal separation.

Other options: profile, quantization, model URL, trials, output token bounds,
RAM interval, connection mode, format, notes, contributor and result folder.
The manifest is local; it does not certify identical artifacts across aliases.
Other servers/models can still occupy RAM. Chronos does not automatically
unload them. Interrupted matrices can leave useful partial manifests.

### Context length — `context`

Measures TTFT with larger inputs, using distinct run/bucket/trial prefixes.
`--buckets` accepts distinct comma-separated names: `small` (~2,000 characters),
`medium` (~8,000), `large` (~32,000), `xlarge` (~128,000). Default: small,medium.
These are character targets, **not token counts**.

`--trials-per-bucket`: 1–10, default 3. `--request-timeout-seconds`: positive
per-request limit, default 120. Also supports engine/model, quantization, model
URL, connection mode, format (default all) and result folder.
Large inputs can exceed model context or available RAM. Input-token counts
depend on server reporting; this local diagnostic is not a uniform prefill or
public benchmark comparison.

### Concurrent requests — `concurrency`

Measures aggregate throughput, latency and outcomes for waves of concurrent
client requests. It does not prove the server uses the same GPU parallelism.

- `--levels`: distinct comma-separated levels from 1 to 32; default 1,2,4,8.
  Start with 1,2 on memory-limited Macs.
- `--trials-per-level`: measured waves per level, 1–10; default 3.
- `--request-max-tokens`: positive output limit **per request**; default 60.

Also supports engine/model, quantization, model URL, format (default all) and
result folder. Warm-up is separate from measurement, and prompts are unique
across requests/waves. Cache-clear evidence is recorded without claiming every
engine is fully cold. Insufficient output can fail quality checks. Local only.

### System energy — `energy` (experimental)

Uses `macmon` to sample **whole-system** power during separate no-request and
active phases. Requires a working macmon installation discoverable on PATH.
Not a calibrated wall-power measurement or energy attributed solely to a model.

| Option | Default / purpose |
| --- | --- |
| `--trials`, `--max-tokens` | 3 throughput trials, 100 output tokens each. Increase work if the active phase is too short. |
| `--settle-seconds` | 5 seconds after warm-up, before the no-request phase; may be zero. |
| `--idle-seconds` | 5 seconds with no Chronos inference requests; other Mac activity/model residency may remain. |
| `--sample-interval-ms` | 500 ms; allowed range 100–1000 ms. |

Also supports engine/model, quantization, model URL and result folder. Outputs
a local JSON report with trace and quality/coverage information. Both measured
phases must last at least `max(5 seconds, 8 sampling intervals)`; at 1000 ms,
5 seconds is insufficient. Invalid samples, gaps or short phases can invalidate
the estimate. Reduce unrelated workloads before interpreting it.

## Results

The default folder is `~/Library/Application Support/MLXChronos/results`.
**Choose default folder…** changes the destination for subsequent tests.
Results from a custom test folder are shown there after execution without
changing the default for later tests; **Show default folder** returns to it.
The browser reads JSON, including diagnostic subfolders, and orders by recorded
date with file-date fallback. It is not a recursive whole-disk result search.

Folders with more than 5,000 JSON files show the
newest 5,000 and a notice with the total. Incomplete subfolder scans also show a
notice.

**Inspect all recorded data** opens the selected JSON. Browsing alone does not
verify its integrity seal or public eligibility.

| Action / CLI command | Use |
| --- | --- |
| Result history / `history` | Read benchmark history in `--output-dir`. `--limit` optionally caps the entries; blank shows all discovered benchmarks. |
| Compare results / `compare` | Select at least two benchmark JSON files and choose a reference, then use **Compare selected**. In the manual file list, the first path is the reference. Schema/seal errors are rejected; differences in hardware, model/reference URL, quantization or protocol produce warnings, not proof of a fair comparison. Diagnostic reports/manifests are not standard benchmark inputs. |
| Share a result / `submit` | **Use selected for sharing** fills `--file` and enables validation without sending. **Validate result** runs eligibility checks locally. Disable validation-only and choose **Review and send…** for an explicit confirmation before sending the full JSON. |

Sharing options: `--file` (required), `--dry-run` (validation-only), optional
`--email` for replies, `--endpoint` for a deliberate inbox override, and
`--timeout` for the request (default 30 seconds). Inherited submission email
and endpoint variables are cleared so the app uses the explicit form choices.
Email and contributor attribution are separate; omitting email does not remove
a handle already in the sealed result. Sending is not automatic leaderboard
publication. Do not edit sealed benchmark JSON manually.

## Activity and stopping

Activity streams command output and errors. Only one foreground operation runs
at a time. **Stop** interrupts it and escalates termination if needed, targeting
its own subprocesses, not independently started engine servers. Quit requests
the same cleanup before closing. Interrupted operations may leave partial
reports; inspect them before use. The console is bounded, not a permanent log
archive; saved JSON files are the durable measurement record.

## Local data, network access and versions

Runtime selection, explicit paths, port overrides and the default result folder
are saved locally. Form drafts and console text are session state. Benchmark
data stays local unless you deliberately share it. Review the full JSON and
notes before sending, especially hardware, model/server metadata and paths.

The app adds no analytics or tracking. Launch checks contact the official runtime catalog, PyPI and GitHub releases.
Preparation downloads Python from python-build-standalone and packages from
PyPI; engine checks and tests contact the configured servers;
confirmed sharing contacts the selected inbox. Engine applications have their
own network and privacy behavior, separate from Chronos.

App version and build identify the macOS bundle; CLI version identifies the
measurement implementation. Updating the CLI does not update the app, and the
app checks for app releases but does not automatically replace its own bundle. For metric definitions and diagnostic
limitations, see [Methodology](../../docs/methodology.md).
