"""HEVI P9.2 — the opt-in live HTTP qualification.

Every test here calls a **paid third-party API**. None of them run by default; they
require ``HEVI_HTTP_LIVE=1``. That gate is the whole point of this file: a qualification
suite that quietly bills a provider on every ``pytest`` run is a defect, not a feature.

Run deliberately:

    HEVI_HTTP_LIVE=1 pytest tests/test_p9_2_live_http.py -v

Each test resolves credentials *first* and skips — loudly — when they are absent, because
"not attempted" is a real outcome and must not be reported as a pass.
"""

from __future__ import annotations

import os

import pytest

from hevi.qualification.credentials import resolve
from hevi.qualification.http_runner import qualify_http_provider
from hevi.qualification.live_run import QualificationVerdict
from hevi.qualification.providers.http import HTTP_PROFILES, profile_for

pytestmark = pytest.mark.skipif(
    os.environ.get("HEVI_HTTP_LIVE") != "1",
    reason="HEVI_HTTP_LIVE != 1; live HTTP qualification spends money and is opt-in",
)

PROMPT = "a single blue circle on a white background, static camera"


@pytest.mark.parametrize("provider_id", sorted(HTTP_PROFILES))
def test_http_provider_produces_a_real_artifact(provider_id, tmp_path):
    profile = profile_for(provider_id)
    resolution = resolve(provider_id, profile.required_credentials)
    if not resolution.complete:
        pytest.skip(f"credentials absent: {','.join(resolution.missing)}")

    out = tmp_path / f"{provider_id}.mp4"
    outcome = qualify_http_provider(
        provider_id, out, params={"payload": {"prompt": PROMPT}}, timeout_s=900.0
    )
    print(f"\n  {provider_id}: {outcome.state.value} / {outcome.verdict.value} — {outcome.reason}")
    assert outcome.verdict is QualificationVerdict.QUALIFIED, (
        f"{provider_id} did not qualify: {outcome.verdict.value} ({outcome.reason})"
    )
    assert out.exists() and out.stat().st_size > 0
    assert outcome.receipt is not None
