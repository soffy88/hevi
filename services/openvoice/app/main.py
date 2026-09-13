"""Minimal isolated service contract; model loading is deployment-specific."""

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="HEVI OpenVoice optional provider")


class SynthesisRequest(BaseModel):
    text: str
    language: str
    options: dict[str, Any] = {}
    reference_sha256: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "blocked", "reason": "model runtime not installed"}


@app.post("/v1/synthesize")
def synthesize(_: SynthesisRequest) -> None:
    raise HTTPException(status_code=503, detail="OpenVoice model runtime is not installed in this image")
