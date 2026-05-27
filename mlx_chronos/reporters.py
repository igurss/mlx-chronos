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
        # For timestamps, we typically want a consistent ts across formats for the same run
        # but calling datetime.now() inside here might yield slightly different seconds.
        # We can use the timestamp from result["meta"]["timestamp"] if available.
        # The timestamp in meta is a datetime object or a string depending on serialization.
        ts_meta = result.get("meta", {}).get("timestamp")
        if isinstance(ts_meta, str):
            try:
                # pydantic dumps it as ISO string
                ts = datetime.fromisoformat(ts_meta.replace('Z', '+00:00')).strftime("%Y%m%d_%H%M%S")
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
        
        md = f"# mlx-chronos Benchmark Result\n\n"
        md += f"**Engine:** {result['engine']['name']} ({result['engine']['version']})\n"
        md += f"**Model:** {result['model']['name']} ({result['model']['quantization']})\n\n"
        
        md += f"## Hardware\n"
        md += f"- **Chip:** {hw['chip']}\n"
        md += f"- **Machine:** {hw.get('machine_model', 'unknown')}\n"
        md += f"- **Memory:** {hw['memory_gb']} GB\n"
        md += f"- **macOS:** {hw['macos_version']}\n\n"
        
        md += f"## Metrics\n"
        md += f"- **Throughput:** {metrics['tokens_per_second']['mean']} tokens/s (±{metrics['tokens_per_second']['stddev']})\n"
        md += f"- **Cold TTFT:** {metrics['ttft_cold']['mean']} s (±{metrics['ttft_cold']['stddev']})\n"
        md += f"- **Cached TTFT:** {metrics['ttft_cached']['mean']} s (±{metrics['ttft_cached']['stddev']})\n"
        if metrics.get("ram_is_process_rss", False):
            md += f"- **Peak engine RSS:** {metrics['ram_peak_gb']} GB\n"
        else:
            md += f"- **Peak engine RSS fallback (system RAM):** {metrics['ram_peak_gb']} GB\n"
        md += (
            f"- **Peak system RAM:** {metrics['system_ram_peak_gb']} GB "
            f"({metrics['system_ram_peak_percent']}%)\n"
        )
        
        notes = result.get("meta", {}).get("notes")
        if notes:
            md += f"\n## Notes\n{notes}\n"
        
        with open(output_path, "w") as f:
            f.write(md)
            
        return output_path
