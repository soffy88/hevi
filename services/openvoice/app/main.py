"""Minimal isolated service contract; model loading is deployment-specific."""

from typing import Any

from fastapi import FastAPI, HTTPException
from model_bootstrap import model_status
from pydantic import BaseModel

app = FastAPI(title="HEVI OpenVoice optional provider")


class SynthesisRequest(BaseModel):
    text: str
    language: str
    options: dict[str, Any] = {}
    reference_sha256: str


@app.get("/health")
def health() -> dict[str, str]:
    return model_status()


@app.get("/ready")
def ready() -> dict[str, str]:
    return model_status()


@app.post("/v1/synthesize")
def synthesize(_: SynthesisRequest) -> None:
    status = model_status()
    if status.get("status") != "READY":
        raise HTTPException(status_code=503, detail=status)
    raise HTTPException(status_code=501, detail="OpenVoice inference runtime is not installed in this image")
