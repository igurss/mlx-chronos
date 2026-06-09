import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime, timezone

class BaseReporter(ABC):
    """Abstract base class for benchmark reporters."""
    
    @abstractmethod
    def save(self, result: dict, results_dir: Path) -> Path:
        """Save the benchmark result to the specified directory."""
        pass

    def _generate_base_filename(self, result: dict) -> str:
        chip_slug = self._slug(result["hardware"]["chip"])
        # Prefer the result timestamp so JSON and Markdown share the same basename.
        ts_meta = result.get("meta", {}).get("timestamp")
        if isinstance(ts_meta, str):
            try:
                # pydantic dumps it as ISO string
                ts = datetime.fromisoformat(
                    ts_meta.replace("Z", "+00:00")
                ).strftime("%Y%m%d_%H%M%S")
            except Exception:
                ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        elif isinstance(ts_meta, datetime):
            ts = ts_meta.strftime("%Y%m%d_%H%M%S")
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            
        engine_name = self._slug(result["engine"]["name"])
        return f"{engine_name}_{chip_slug}_{ts}"

    def _slug(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unknown"

    def _format_timestamp(self, value: object) -> str:
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        if isinstance(value, str) and value.strip():
            return value
        return "unknown"

    def _format_optional(self, value: object) -> object:
        return "unknown" if value is None else value

    def _format_stats(self, stats: dict, unit: str) -> str:
        text = (
            f"{stats['mean']} {unit} "
            f"(±{stats['stddev']}; min {stats['min']}, max {stats['max']})"
        )
        if stats.get("p95") is not None:
            text += f", p95 {stats['p95']}"
        return text

class JSONReporter(BaseReporter):
    """Saves benchmark results as JSON."""
    
    def save(self, result: dict, results_dir: Path) -> Path:
        results_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self._generate_base_filename(result)}.json"
        output_path = results_dir / filename
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
            f.write("\n")
            
        return output_path

class MarkdownReporter(BaseReporter):
    """Saves benchmark results as Markdown."""
    
    def save(self, result: dict, results_dir: Path) -> Path:
        results_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self._generate_base_filename(result)}.md"
        output_path = results_dir / filename
        
        hw = result["hardware"]
        metrics = result["metrics"]
        meta = result.get("meta", {})
        trials = result.get("trials", {})
        
        md = "# mlx-chronos Benchmark Result\n\n"
        md += f"**Engine:** {result['engine']['name']} ({result['engine']['version']})\n"
        md += f"**Model:** {result['model']['name']} ({result['model']['quantization']})\n\n"
        md += "## Run\n"
        md += f"- **Timestamp:** {self._format_timestamp(meta.get('timestamp'))}\n"
        md += f"- **Chronos version:** {self._format_optional(meta.get('chronos_version'))}\n"
        md += f"- **Profile:** {self._format_optional(meta.get('benchmark_profile'))}\n"
        md += f"- **Trials:** {trials.get('count', 'unknown')}\n"
        md += f"- **Token count source:** {self._format_optional(metrics.get('token_count_source'))}\n"
        integrity = result.get("integrity") or {}
        if integrity:
            md += (
                "- **Integrity:** "
                f"{self._format_optional(integrity.get('schema'))}\n"
            )
        protocol = meta.get("benchmark_protocol") or {}
        if protocol:
            md += (
                f"- **Protocol:** {self._format_optional(protocol.get('name'))} "
                f"v{self._format_optional(protocol.get('version'))}\n"
            )
            throughput_protocol = protocol.get("throughput") or {}
            if throughput_protocol:
                min_tokens = throughput_protocol.get("requested_min_tokens")
                min_tokens_label = "none" if min_tokens is None else min_tokens
                md += (
                    "- **Throughput token bounds:** "
                    f"max {throughput_protocol.get('requested_max_tokens', 'unknown')}, "
                    f"min {min_tokens_label}\n"
                )
        if meta.get("word_fallback_warning"):
            md += (
                "- **Warning:** throughput token counts used word_fallback; "
                "local tok/s is an estimate and is not leaderboard-comparable.\n"
            )
        if meta.get("engine_version_warning"):
            md += (
                "- **Warning:** engine version detection failed; "
                "`engine.version` is `unknown`.\n"
            )
        if meta.get("sustained_throttling_warning"):
            md += (
                "- **Warning:** sustained profile observed late throughput "
                "degradation with a thermal-state signal.\n"
            )
        if meta.get("cached_ttft_warning"):
            md += (
                "- **Warning:** cached TTFT is close to cold TTFT; prompt/KV "
                "cache reuse may not have occurred.\n"
            )
        if meta.get("elapsed_since_last_benchmark_seconds") is not None:
            md += (
                "- **Elapsed since prior result:** "
                f"{meta['elapsed_since_last_benchmark_seconds']} s\n"
            )
        if meta.get("warmup_failures"):
            md += f"- **Warmup failures:** {meta['warmup_failures']}\n"
        phase_timings = meta.get("phase_timings_seconds")
        if phase_timings:
            md += f"- **Total runtime:** {phase_timings['total_runtime']} s\n"
        md += "\n"
        
        md += "## Hardware\n"
        md += f"- **Chip:** {hw['chip']}\n"
        md += f"- **Machine:** {self._format_optional(hw.get('machine_model'))}\n"
        md += f"- **Memory:** {hw['memory_gb']} GB\n"
        md += f"- **macOS:** {hw['macos_version']}\n"
        md += f"- **Thermal state:** {self._format_optional(hw.get('thermal_state'))}\n"
        if hw.get("power_source") is not None:
            md += f"- **Power source:** {self._format_optional(hw.get('power_source'))}\n"
        if hw.get("low_power_mode") is not None:
            md += f"- **Low Power Mode:** {self._format_optional(hw.get('low_power_mode'))}\n"
        md += "\n"
        
        md += "## Metrics\n"
        md += (
            f"- **Request throughput:** "
            f"{self._format_stats(metrics['tokens_per_second'], 'tokens/s')}\n"
        )
        decode_stats = metrics.get("decode_tokens_per_second")
        if decode_stats:
            md += (
                f"- **Decode throughput:** "
                f"{self._format_stats(decode_stats, 'tokens/s')}\n"
            )
        md += (
            f"- **Decode timing source:** "
            f"{self._format_optional(metrics.get('decode_timing_source'))}\n"
        )
        md += (
            f"- **Cold TTFT:** {self._format_stats(metrics['ttft_cold'], 's')}\n"
        )
        md += (
            f"- **Cached TTFT:** {self._format_stats(metrics['ttft_cached'], 's')}\n"
        )
        ram_peak_gb = self._format_optional(metrics.get("ram_peak_gb"))
        system_ram_peak_gb = self._format_optional(metrics.get("system_ram_peak_gb"))
        system_ram_peak_percent = self._format_optional(
            metrics.get("system_ram_peak_percent")
        )

        if metrics.get("ram_is_process_rss", False):
            md += (
                "- **Post-warmup engine RSS diagnostic:** "
                f"{ram_peak_gb} GB\n"
            )
        else:
            md += (
                "- **Post-warmup engine RSS diagnostic fallback "
                "(system RAM):** "
                f"{ram_peak_gb} GB\n"
            )
        md += (
            f"- **RAM measurement method:** "
            f"{self._format_optional(metrics.get('ram_measurement_method'))}\n"
        )
        md += (
            f"- **Peak system RAM:** {system_ram_peak_gb} GB "
            f"({system_ram_peak_percent}%)\n"
        )

        thermal_monitor = meta.get("thermal_monitor")
        if thermal_monitor:
            md += "\n## Thermal Monitor\n"
            md += (
                f"- **Source:** "
                f"{self._format_optional(thermal_monitor.get('source'))}\n"
            )
            md += (
                f"- **Sample interval:** "
                f"{thermal_monitor['sample_interval_seconds']} s\n"
            )
            md += (
                f"- **State:** {thermal_monitor['start_state']} -> "
                f"{thermal_monitor['end_state']} "
                f"(worst: {thermal_monitor['worst_state']})\n"
            )
            md += f"- **Samples:** {thermal_monitor['samples']}\n"
            md += (
                f"- **Changed during run:** "
                f"{thermal_monitor['changed_during_run']}\n"
            )
            phases = thermal_monitor.get("non_nominal_phases") or []
            if phases:
                md += f"- **Non-nominal phases:** {', '.join(phases)}\n"

        if phase_timings:
            md += "\n## Phase Timings\n"
            for label, key in [
                ("Warmup", "warmup"),
                ("Cold TTFT", "ttft_cold"),
                ("Cache priming", "cache_priming"),
                ("Cached TTFT", "ttft_cached"),
                ("Throughput", "throughput"),
            ]:
                md += f"- **{label}:** {phase_timings[key]} s\n"

        raw_sections = [
            (label, values)
            for label, values in [
                ("Cold TTFT", trials.get("ttft_cold_raw")),
                ("Cached TTFT", trials.get("ttft_cached_raw")),
                ("Request throughput", trials.get("tokens_per_second_raw")),
                ("Throughput elapsed seconds", trials.get("throughput_elapsed_seconds_raw")),
                ("Decode throughput", trials.get("decode_tokens_per_second_raw")),
                ("Completion tokens", trials.get("completion_tokens_raw")),
            ]
            if values
        ]
        if raw_sections:
            md += "\n## Raw Trials\n"
            for label, values in raw_sections:
                rendered_values = ", ".join(f"{value:g}" for value in values)
                md += f"- **{label}:** {rendered_values}\n"

        progress_samples = trials.get("throughput_progress_samples_raw")
        if progress_samples:
            md += "\n## Throughput Progress Samples\n"
            for index, samples in enumerate(progress_samples, start=1):
                if not samples:
                    continue
                rendered_samples = ", ".join(
                    (
                        f"{sample['completion_tokens']} tokens @ "
                        f"{sample['elapsed_seconds']}s = "
                        f"{sample['tokens_per_second']} tokens/s "
                        f"({sample['token_count_source']})"
                    )
                    for sample in samples
                )
                md += f"- **Trial {index}:** {rendered_samples}\n"
        
        notes = meta.get("notes")
        if notes:
            md += f"\n## Notes\n{notes}\n"
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md)
            
        return output_path
