# HEVI OpenVoice isolated provider

This directory defines the optional HTTP service boundary only. OpenVoice
models and Python dependencies are not installed in HEVI's root environment.
The service is `OPTIONAL_EXTERNAL_PROVIDER`; absence is reported as a blocked
provider and never falls back silently during production qualification.

The `/health` and `/v1/synthesize` contracts are consumed by
`hevi.audio.providers.openvoice.OpenVoiceProvider`.

License/provenance must be recorded for the exact OpenVoice code and model
versions used by a deployment before commercial use.
