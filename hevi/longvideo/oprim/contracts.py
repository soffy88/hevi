"""Long video generation request primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LongVideoRequest:
    prompt: str
    mode: str = "t2v"
    duration_s: int = 60
    shot_prompts: tuple[str, ...] = ()
    reference_images: tuple[str, ...] = ()
    model: str = "longlive"
    precision: str = "fp16"
    sequence_parallel: int = 1
    attention_sink: bool = True
    async_decode: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.prompt.strip() and not self.shot_prompts:
            errors.append("prompt or shot_prompts is required")
        if self.mode not in {"t2v", "i2v", "multi_shot"}:
            errors.append(f"unsupported mode: {self.mode}")
        if self.duration_s < 1 or self.duration_s > 3600:
            errors.append("duration_s must be between 1 and 3600")
        if self.mode == "i2v" and not self.reference_images:
            errors.append("i2v requires at least one reference image")
        if self.precision not in {"fp16", "bf16", "fp8", "nvfp4"}:
            errors.append(f"unsupported precision: {self.precision}")
        if self.sequence_parallel < 1:
            errors.append("sequence_parallel must be >= 1")
        return errors

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["shot_prompts"] = list(self.shot_prompts)
        body["reference_images"] = list(self.reference_images)
        return body


__all__ = ["LongVideoRequest"]
