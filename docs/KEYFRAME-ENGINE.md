# Keyframe Engine Specification & Contract (DRAMAKEY / COMICNARR)

## Architecture Overview

The keyframe engine layer provides a unified, pluggable contract for generating keyframe images on CPU (and future GPU/cloud backends). It is consumed across drama and comic generation pipelines (e.g., `dramakey`, `comicnarr`, `script2video`).

Package Locations:
- Layer 4 Implementation: `hevi.layer4_legacy.keyframe.oprim_impl`
- Compatibility Shim: `hevi.keyframe.oprim`

---

## 1. Data Contracts

### `KeyframeResult`
```python
@dataclass(frozen=True)
class KeyframeResult:
    path: Path          # Path to output PNG/JPEG
    seed: int           # RNG seed used for generation
    engine: str         # Engine identifier (e.g. 'sdturbo_cpu')
    model: str          # Underlying model name (e.g. 'sd-turbo')
    sec: float          # Generation elapsed wall time in seconds
    rss_mb: float       # Resident process memory in MB
    width: int = 512    # Rendered width
    height: int = 512   # Rendered height
    steps: int = 2      # Inference steps
```

### `KeyframeEngine` (Abstract Base Class)
```python
class KeyframeEngine(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Engine identifier string."""

    @abstractmethod
    def available(self) -> bool:
        """Check if models and hardware requirements are satisfied."""

    @property
    @abstractmethod
    def max_resident_mb(self) -> float:
        """Estimated peak resident RAM in MB."""

    @abstractmethod
    def generate(
        self,
        prompt_en: str,
        *,
        negative: str | None = None,
        width: int = 512,
        height: int = 512,
        steps: int = 2,
        seed: int | None = None,
        ref_image: Path | None = None,
        output_path: Path | None = None,
    ) -> KeyframeResult:
        """Generate a single keyframe image."""
```

---

## 2. Standard Engine Implementations

| Engine Name | Role | Default Parameters | Availability Check | Peak RSS |
|---|---|---|---|---|
| `sdturbo_cpu` | **Default CPU Engine** | 512×512, steps=2, guidance=0.0 | Weights exist at `/data/soffy/models/ms/models/AI-ModelScope--sd-turbo/snapshots/master` | ~5.5 GB |
| `fake` | **Unit Test Only** | Synthetic PIL image (<10ms) | Always True (E2E paths assert engine != 'fake') | <10 MB |
| `cloud_stub` | Cloud Adapter Slot | Configurable | `HEVI_KEYFRAME_CLOUD=1` and provider API key set | <50 MB |
| `sdxlturbo_cpu` | High Quality Slot | 512×512 / 768×768 | `psutil.virtual_memory().available >= 18 GB` | ~16.5 GB |

---

## 3. Engine Resolution

Use `resolve_keyframe_engine(config=None)` to instantiate the appropriate engine:
1. Explicit argument in `config` (`config["engine"]` or `config.engine` or string `config`).
2. Environment variable `HEVI_KEYFRAME_ENGINE`.
3. Default fallback: `"sdturbo_cpu"`.

```python
from hevi.keyframe.oprim import resolve_keyframe_engine

engine = resolve_keyframe_engine()
result = engine.generate("an ancient Taoist priest in grey robes, cinematic", seed=42)
```

---

## 4. Multi-Process Concurrency & Mutex Lock

To prevent CPU overload and OOM errors when concurrent agents (e.g. DRAMAKEY and COMICNARR) execute, all model generation must acquire the system-wide render flock:
- File: `/tmp/hevi_cpu_render.lock`
- Python context manager: `from hevi.keyframe.oprim import cpu_render_lock`
- Inside `sdturbo_cpu.generate()`, this lock is acquired automatically during inference.

---

## 5. Licensing Notice

`SD-Turbo` is released under the Stability AI Non-Commercial Research Community License. It is free for non-commercial research and commercial use under $1M/year revenue. All deliverables using this engine must acknowledge this community license.
