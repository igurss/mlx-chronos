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
        text = f"{stats['mean']} {unit} (±{stats['stddev']})"
        if stats.get("p95") is not None:
            text += f", p95 {stats['p95']}"
        return text

class JSONReporter(BaseReporter):
    """Saves benchmark results as JSON."""
    
    def save(self, result: dict, results_dir: Path) -> Path:
        results_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self._generate_base_filename(result)}.json"
        output_path = results_dir / filename
        
        with open(output_path, "w") as f:
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
        
        md = f"# mlx-chronos Benchmark Result\n\n"
        md += f"**Engine:** {result['engine']['name']} ({result['engine']['version']})\n"
        md += f"**Model:** {result['model']['name']} ({result['model']['quantization']})\n\n"
        md += f"## Run\n"
        md += f"- **Timestamp:** {self._format_timestamp(meta.get('timestamp'))}\n"
        md += f"- **Chronos version:** {self._format_optional(meta.get('chronos_version'))}\n"
        md += f"- **Trials:** {trials.get('count', 'unknown')}\n"
        md += f"- **Token count source:** {self._format_optional(metrics.get('token_count_source'))}\n\n"
        
        md += f"## Hardware\n"
        md += f"- **Chip:** {hw['chip']}\n"
        md += f"- **Machine:** {self._format_optional(hw.get('machine_model'))}\n"
        md += f"- **Memory:** {hw['memory_gb']} GB\n"
        md += f"- **macOS:** {hw['macos_version']}\n"
        md += f"- **Thermal state:** {self._format_optional(hw.get('thermal_state'))}\n\n"
        
        md += f"## Metrics\n"
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
            md += f"- **Peak engine RSS:** {ram_peak_gb} GB\n"
        else:
            md += f"- **Peak engine RSS fallback (system RAM):** {ram_peak_gb} GB\n"
        md += (
            f"- **RAM measurement method:** "
            f"{self._format_optional(metrics.get('ram_measurement_method'))}\n"
        )
        md += (
            f"- **Peak system RAM:** {system_ram_peak_gb} GB "
            f"({system_ram_peak_percent}%)\n"
        )

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
        
        notes = meta.get("notes")
        if notes:
            md += f"\n## Notes\n{notes}\n"
        
        with open(output_path, "w") as f:
            f.write(md)
            
        return output_path
