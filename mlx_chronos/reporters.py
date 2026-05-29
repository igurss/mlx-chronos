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
        md += f"- **Chronos version:** {meta.get('chronos_version', 'unknown')}\n"
        md += f"- **Trials:** {trials.get('count', 'unknown')}\n"
        md += f"- **Token count source:** {metrics.get('token_count_source', 'unknown')}\n\n"
        
        md += f"## Hardware\n"
        md += f"- **Chip:** {hw['chip']}\n"
        md += f"- **Machine:** {hw.get('machine_model', 'unknown')}\n"
        md += f"- **Memory:** {hw['memory_gb']} GB\n"
        md += f"- **macOS:** {hw['macos_version']}\n\n"
        
        md += f"## Metrics\n"
        md += (
            f"- **Throughput:** {metrics['tokens_per_second']['mean']} tokens/s "
            f"(±{metrics['tokens_per_second']['stddev']})\n"
        )
        md += (
            f"- **Cold TTFT:** {metrics['ttft_cold']['mean']} s "
            f"(±{metrics['ttft_cold']['stddev']})\n"
        )
        md += (
            f"- **Cached TTFT:** {metrics['ttft_cached']['mean']} s "
            f"(±{metrics['ttft_cached']['stddev']})\n"
        )
        if metrics.get("ram_is_process_rss", False):
            md += f"- **Peak engine RSS:** {metrics['ram_peak_gb']} GB\n"
        else:
            md += f"- **Peak engine RSS fallback (system RAM):** {metrics['ram_peak_gb']} GB\n"
        md += (
            f"- **Peak system RAM:** {metrics['system_ram_peak_gb']} GB "
            f"({metrics['system_ram_peak_percent']}%)\n"
        )

        raw_sections = [
            (label, values)
            for label, values in [
                ("Cold TTFT", trials.get("ttft_cold_raw")),
                ("Cached TTFT", trials.get("ttft_cached_raw")),
                ("Throughput", trials.get("tokens_per_second_raw")),
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
