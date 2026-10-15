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

## 5. Shared Style Presets (DRAMAKEY + COMICNARR)

Non-photoreal illustration styles live in **one shared module** so that the
`dramakey` drama pipeline and the `comicnarr` comic-narration line render the
same look.  Do not hard-code style tokens in a product package.

```
hevi/layer4_legacy/keyframe/oprim_impl/style_presets.py
```

Exports:

| Symbol | Meaning |
|---|---|
| `StylePreset` | frozen dataclass (see fields below) |
| `STYLE_PRESETS` | `dict[str, StylePreset]` |
| `DEFAULT_STYLE` | `"guofeng_anime"` (comic-narration default) |
| `get_style_preset(name)` | tolerant lookup with fallback to `DEFAULT_STYLE` |
| `list_style_presets()` | sorted preset names |

Required `StylePreset` fields: `style_tokens`, `negative_prompt`,
`subtitle_style`, `bgm_mood`, `transition`, `postprocess`.  Optional subtitle
rendering hints (`font_size`, `subtitle_primary`, `subtitle_outline`, ...) and
`bubble_*` colours are also carried here so every consumer renders readable
captions.

Built-in presets:

| Name | Look | Postprocess | Notes |
|---|---|---|---|
| `guofeng_anime` | 国风动漫 / donghua, cel-shaded, ink-wash accents | `none` | **default** for `comic_narration` |
| `comic_color` | colourful flat comic / graphic novel | `none` | |
| `manga_bw` | black & white manga, screentone | `manga_bw` (grayscale + halftone) | guarantees a monochrome frame |

Usage:

```python
from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import (
    DEFAULT_STYLE, get_style_preset,
)

preset = get_style_preset("manga_bw")
prompt = f"{scene_tokens}, {preset.style_tokens}"
negative = preset.negative_prompt
# postprocess pass for the generated keyframe:
from hevi.layer4_legacy.comicnarr.oprim_impl.postprocess import apply_style_postprocess
apply_style_postprocess(image_path, preset.postprocess)
```

The `comicnarr` package keeps the historical names `COMIC_STYLES` /
`get_style_template` as thin aliases over the shared presets.

---

## 6. Licensing Notice

`SD-Turbo` is released under the Stability AI Non-Commercial Research Community License. It is free for non-commercial research and commercial use under $1M/year revenue. All deliverables using this engine must acknowledge this community license.

---

## 6. Keyframe Style Presets (shared with comicnarr)

On CPU, photoreal live-action faces are not competitive (SD-Turbo at 512px renders
blurry, non-consistent faces), so the **default style is `anime_guofeng` (国风动漫插画)**
and `photoreal` is an opt-in preset that is **off by default**.

Canonical definition (single source of truth):
`hevi/prompt/style_presets.py` → `KEYFRAME_STYLE_PRESETS`, so `dramakey`,
`comicnarr`, and `script2video` share the exact same presets. Convenience re-exports
live in `hevi.layer4_legacy.keyframe.oskill_impl` (`get_keyframe_style`,
`list_keyframe_styles`, `resolve_style_preset`).

| Style key | Label | prompt_prefix | photoreal |
|---|---|---|---|
| `anime_guofeng` | 国风动漫插画（默认） | `chinese anime illustration, guofeng donghua art style, 2d animation cel, stylized character design` | No |
| `ink` | 国风水墨 | `traditional chinese ink wash painting, shuimo guofeng style` | No |
| `flat_comic` | 平涂漫画 | `flat comic book illustration, graphic novel panel art` | No |
| `photoreal` | 写实真人（可选，默认关闭） | `cinematic photorealistic live-action film still` | Yes |

Each preset supplies `prompt_prefix` (front-loaded style words), `style_tags`
(postfix detail), and `negative` (merged into the final negative prompt). The
non-photoreal presets add `photo, photograph, photorealistic, realistic, 3d render,
cgi, ...` to the negative prompt so the CPU model stays illustrative.

Usage:

```python
from hevi.layer4_legacy.keyframe.omodul_impl.video_render import RenderConfig

cfg = RenderConfig(style="anime_guofeng")  # default; also: ink | flat_comic | photoreal
```

`RenderConfig.style`, `Novel2VideoConfig.style`, and `Script2VideoKernelConfig.style`
are all accepted from CLI/API. The QA report records a measured style gate
(`compute_style_alignment`, OpenCLIP anime-vs-photoreal) per shot; `stylized_pass`
is false if any winner keyframe reads more like a photograph than an illustration.
