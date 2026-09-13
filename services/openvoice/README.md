# HEVI OpenVoice isolated provider

This directory defines the optional HTTP service boundary only. OpenVoice
models and Python dependencies are not installed in HEVI's root environment.
The service is `OPTIONAL_EXTERNAL_PROVIDER`; absence is reported as a blocked
provider and never falls back silently during production qualification.

The `/health` and `/v1/synthesize` contracts are consumed by
`hevi.audio.providers.openvoice.OpenVoiceProvider`.

License/provenance must be recorded for the exact OpenVoice code and model
versions used by a deployment before commercial use.

Model weights are never baked into the image. Run `python model_bootstrap.py`
with `OPENVOICE_MODEL_ID`, `OPENVOICE_MODEL_URL`, and
`OPENVOICE_MODEL_SHA256`, using `/models/openvoice` as a persistent cache
volume. The service reports `BLOCKED_MODEL_MISSING`, `BLOCKED_NETWORK`, or
`BLOCKED_MODEL_RUNTIME` until the manifest and checksum are valid.
