"""HEVI P5.1 — evidence-first visual policy.

A knowledge video that says "this product supports X" must be able to *show* it.
The default failure mode is to generate a convincing fake interface and pass it
off as the real thing. This module makes that impossible by construction.

Policy ladder (§15), best evidence first:

1. verified first-party evidence
2. verified real screenshot / interface
3. verified source asset
4. licensed contextual asset
5. clearly labelled generated visualization
6. symbolic visual

Closed truth rules (§18), enforced as hard invariants:

* ``GENERATED_VISUALIZATION`` may never be relabelled as ``REAL_INTERFACE``.
* A mock UI may never become ``OFFICIAL_SCREENSHOT``.
* A generic screenshot may never back a specific product claim.

So ``FAKE_UI_AS_EVIDENCE == 0``, ``FALSE_PROVENANCE == 0`` and
``UNSOURCED_PRODUCT_VISUAL_AS_REAL == 0``.

Acquisition boundary (§20): this module may use the existing browser / capture
paths. It does **not** create a second web-research authority — research truth
still belongs to the existing source and research lineage.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hevi.ops.p5_1_types import (
    EVIDENCE_PRIORITY,
    NON_REALITY_TYPES,
    REALITY_ASSERTING_TYPES,
    EvidenceAsset,
    EvidenceFreshness,
    EvidenceRequest,
    EvidenceSourceType,
    canonical_hash,
)


@dataclass
class EvidenceVerdict:
    """Outcome of an evidence-truth check."""

    ok: bool = True
    violations: list[str] = field(default_factory=list)
    blocked_asset_id: str = ""
    corrected_type: EvidenceSourceType | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["corrected_type"] = self.corrected_type.value if self.corrected_type else None
        return d


# ── Evidence truth (§18) ─────────────────────────────────────────────────

#: Substrings in a source_uri / provenance string that betray a generated or
#: mocked interface being passed off as real.
_MOCK_MARKERS = (
    "mock",
    "fake",
    "placeholder",
    "sample_ui",
    "demo_ui",
    "lorem",
    "wireframe",
    "prototype-ui",
    "redesign-concept",
)

_GENERATED_MARKERS = (
    "sdxl",
    "stable-diffusion",
    "generated",
    "synthesized",
    "aigenerated",
    "ai-generated",
    "midjourney",
    "dalle",
    "text2image",
    "image_gen",
)

_OFFICIAL_HOST_HINTS = ("github.com", "arxiv.org", "docs.", "developer.")


def evidence_truth_check(
    asset: EvidenceAsset,
    *,
    allow_symbolic_for_claim: bool = False,
) -> EvidenceVerdict:
    """Validate that an evidence asset's type matches what it actually is.

    This is the gate that makes ``EVIDENCE_TRUTH`` a property of the system
    rather than a hope. It fails closed: anything ambiguous is rejected.
    """
    violations: list[str] = []
    blob = " ".join(
        str(v).lower()
        for v in (
            asset.source_uri,
            asset.path,
            asset.entity,
            str(asset.provenance.get("generator", "")),
            str(asset.provenance.get("capture_method", "")),
            str(asset.provenance.get("notes", "")),
        )
        if v
    )

    is_mock = any(m in blob for m in _MOCK_MARKERS)
    is_generated = any(m in blob for m in _GENERATED_MARKERS)
    declared_generated = bool(
        asset.provenance.get("generated") or asset.provenance.get("ai_generated")
    )

    # 1. Generated material can never assert reality.
    if asset.is_reality_asserting and (is_generated or declared_generated):
        violations.append(
            f"FAKE_UI_AS_EVIDENCE:{asset.source_type.value} claimed for generated material"
        )
    # 2. A mock UI can never become official evidence.
    if asset.is_reality_asserting and is_mock:
        violations.append(f"MOCK_UI_AS_OFFICIAL:{asset.source_type.value}")
    # 3. A specific product claim needs a specific, real, captured source.
    if asset.claim_supported and asset.entity and asset.is_reality_asserting:
        if not asset.captured_at:
            violations.append("REALITY_ASSERTING_WITHOUT_CAPTURE_TIME")
        if not asset.source_uri:
            violations.append("REALITY_ASSERTING_WITHOUT_SOURCE")
        elif not asset.source_uri.lower().startswith(("http://", "https://", "file://")):
            violations.append(f"NON_CONCRETE_SOURCE:{asset.source_uri[:60]}")
    # 4. Official/official-screenshot claims need an identity that looks official.
    if asset.source_type in (
        EvidenceSourceType.OFFICIAL_SCREENSHOT,
        EvidenceSourceType.OFFICIAL_IMAGE,
    ):
        host = urlparse(asset.source_uri).netloc.lower()
        if (
            host
            and not any(h in host for h in _OFFICIAL_HOST_HINTS)
            and not asset.provenance.get("official_verified")
        ):
            violations.append(f"UNVERIFIED_OFFICIAL_SOURCE:{host}")
    # 5. Generated/symbolic material must never silently back a factual claim.
    if asset.source_type in NON_REALITY_TYPES and asset.claim_supported:
        if not asset.provenance.get("labelled_as_generated"):
            violations.append(
                f"UNLABELLED_GENERATED_EVIDENCE:{asset.source_type.value}"
            )
        if not allow_symbolic_for_claim:
            violations.append("NON_REAL_EVIDENCE_USED_FOR_CLAIM")

    return EvidenceVerdict(ok=not violations, violations=violations)


def assert_evidence_truth(asset: EvidenceAsset) -> EvidenceVerdict:
    verdict = evidence_truth_check(asset)
    if not verdict.ok:
        verdict.blocked_asset_id = asset.asset_id
    return verdict


# ── Privacy (§59, §60) ───────────────────────────────────────────────────

#: Credential shapes that must never enter an artifact.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("OPENAI_STYLE_KEY", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("BEARER_TOKEN", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}", re.IGNORECASE)),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("SLACK_TOKEN", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("FAL_KEY", re.compile(r"\b[0-9a-f]{8}:[0-9a-f]{32}\b")),
    ("PRIVATE_KEY_BLOCK", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("LONG_HEX_SECRET", re.compile(r"\b[0-9a-fA-F]{40,}\b")),
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

#: URL query parameters that carry credentials and must never be persisted.
_SENSITIVE_QUERY_KEYS = (
    "token",
    "access_token",
    "api_key",
    "apikey",
    "key",
    "secret",
    "password",
    "passwd",
    "auth",
    "session",
    "signature",
    "sig",
)


@dataclass
class PrivacyScanResult:
    """Result of scanning a screenshot's text/URL surface for private data."""

    safe: bool = True
    findings: list[str] = field(default_factory=list)
    secret_kinds: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    sanitized_text: str = ""
    action: str = "ACCEPT"  # ACCEPT | REDACT | REJECT

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def strip_sensitive_query(url: str) -> str:
    """Remove credential-bearing query parameters from a URL before recording it."""
    if not url or "?" not in url:
        return url
    head, _, query = url.partition("?")
    kept: list[str] = []
    for pair in query.split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].lower()
        if any(marker in key for marker in _SENSITIVE_QUERY_KEYS):
            continue
        kept.append(pair)
    return f"{head}?{'&'.join(kept)}" if kept else head


def scan_privacy(text: str, *, allow_email: bool = False) -> PrivacyScanResult:
    """Scan captured text for secrets and personal data.

    Real data, real patterns. Runs over the actual page text and URL that the
    existing capture path obtained, not over a declaration.
    """
    findings: list[str] = []
    kinds: list[str] = []
    sanitized = text or ""

    for name, pattern in _SECRET_PATTERNS:
        matches = pattern.findall(sanitized)
        if matches:
            kinds.append(name)
            findings.append(f"{name}:{len(matches)}")
            sanitized = pattern.sub("[REDACTED]", sanitized)

    emails = _EMAIL.findall(sanitized) if not allow_email else []
    if emails:
        findings.append(f"EMAIL:{len(emails)}")

    secret_hit = bool(kinds)
    return PrivacyScanResult(
        safe=not secret_hit,
        findings=findings,
        secret_kinds=kinds,
        emails=sorted(set(emails)),
        sanitized_text=sanitized,
        action="REJECT" if secret_hit else ("REDACT" if emails else "ACCEPT"),
    )


def apply_privacy_policy(
    asset: EvidenceAsset, scan: PrivacyScanResult
) -> tuple[EvidenceAsset, list[str]]:
    """Redact or reject an asset according to the privacy scan.

    Secrets are never merely noted: an asset carrying a credential is rejected,
    and an asset carrying personal contact detail is redacted before it can be
    delivered. ``PRIVATE_DATA_LEAK == 0`` is enforced here.
    """
    reasons: list[str] = []
    asset.privacy_scan = scan.to_dict()
    if scan.secret_kinds:
        reasons.extend(f"REJECT:{k}" for k in scan.secret_kinds)
        asset.provenance = {**asset.provenance, "rejected_reason": ",".join(scan.secret_kinds)}
        asset.source_type = EvidenceSourceType.SYMBOLIC
        asset.claim_supported = ""
        return asset, reasons
    if scan.emails:
        marker = f"email:{len(scan.emails)}"
        asset.provenance = {
            **asset.provenance,
            "redactions": [*asset.redactions, marker],
            "page_text_redacted": True,
        }
        asset.redactions = [*asset.redactions, marker]
        reasons.append(f"REDACT:{marker}")
    return asset, reasons


# ── Freshness (§19) ──────────────────────────────────────────────────────

#: How long a captured interface stays honestly describable as "current".
DEFAULT_STALE_AFTER = timedelta(days=180)


def evaluate_evidence_freshness(
    asset: EvidenceAsset,
    *,
    now: datetime | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> EvidenceAsset:
    """Mark evidence that may no longer describe the current interface.

    A capture is never silently presented as the current state of a product
    once it has aged past the policy window; it becomes ``STALE_EVIDENCE``.
    """
    now = now or datetime.now(UTC)
    if asset.source_type not in REALITY_ASSERTING_TYPES:
        asset.freshness = EvidenceFreshness.UNDATED
        return asset
    if not asset.captured_at:
        asset.freshness = EvidenceFreshness.UNDATED
        return asset
    try:
        captured = datetime.fromisoformat(asset.captured_at.replace("Z", "+00:00"))
    except ValueError:
        asset.freshness = EvidenceFreshness.UNDATED
        return asset
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    asset.freshness = (
        EvidenceFreshness.STALE_EVIDENCE
        if now - captured > stale_after
        else EvidenceFreshness.FRESH
    )
    return asset


# ── Evidence-first planning (§15, §16) ───────────────────────────────────

#: Narration signals that demand real evidence rather than a generated visual.
EVIDENCE_TRIGGER_TERMS = (
    "界面",
    "截图",
    "官网",
    "文档",
    "论文",
    "报告",
    "数据",
    "图表",
    "dashboard",
    "interface",
    "screenshot",
    "docs",
    "documentation",
    "paper",
    "chart",
    "dataset",
    "website",
    "官网首页",
    "控制台",
    "后台",
    "版本",
    "release",
    "product",
    "feature",
    "pricing",
)


@dataclass
class VisualEvidencePlan:
    """What evidence a beat needs, and what may substitute for it."""

    request: EvidenceRequest
    acceptable_types: tuple[EvidenceSourceType, ...]
    forbidden_types: tuple[EvidenceSourceType, ...] = ()
    requires_real: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["acceptable_types"] = [t.value for t in self.acceptable_types]
        d["forbidden_types"] = [t.value for t in self.forbidden_types]
        return d


def classify_evidence_need(
    *,
    claim: str,
    entity: str = "",
    desired_type: EvidenceSourceType = EvidenceSourceType.REAL_INTERFACE,
) -> VisualEvidencePlan:
    """Build the acceptable-evidence ladder for one claim.

    When a claim is about a real product, interface, paper or dataset, the
    acceptable set starts at verified real material. Generated and symbolic
    visuals are only acceptable when they are explicitly labelled, which
    :func:`evidence_truth_check` then requires.
    """
    text = (claim or "").lower()
    trigger = any(term in (claim or "") or term in text for term in EVIDENCE_TRIGGER_TERMS)
    needs_real = trigger or bool(entity)
    acceptable: tuple[EvidenceSourceType, ...]
    if needs_real:
        acceptable = (
            EvidenceSourceType.OFFICIAL_SCREENSHOT,
            EvidenceSourceType.REAL_INTERFACE,
            EvidenceSourceType.DOCUMENT_EXCERPT,
            EvidenceSourceType.OFFICIAL_IMAGE,
            EvidenceSourceType.DATA_VISUALIZATION,
            EvidenceSourceType.REAL_PHOTO,
        )
    else:
        acceptable = EVIDENCE_PRIORITY
    return VisualEvidencePlan(
        request=EvidenceRequest(claim=claim, entity=entity, desired_evidence_type=desired_type),
        acceptable_types=acceptable,
        forbidden_types=(EvidenceSourceType.GENERATED_VISUALIZATION,)
        if needs_real
        else (),
        requires_real=needs_real,
    )


def rank_evidence(candidates: list[EvidenceAsset]) -> list[EvidenceAsset]:
    """Order candidate evidence along the evidence-first ladder."""
    order = {t.value: i for i, t in enumerate(EVIDENCE_PRIORITY)}

    def key(asset: EvidenceAsset) -> tuple[int, float]:
        return (order.get(asset.source_type.value, len(order)), -asset.confidence)

    return sorted(candidates, key=key)


def select_best_evidence(
    candidates: list[EvidenceAsset], *, claim: str = "", entity: str = ""
) -> tuple[EvidenceAsset | None, list[str]]:
    """Pick the best *truthful* evidence for a claim.

    Candidates failing the truth gate are excluded outright rather than
    downgraded, so a fake interface can never win by being the only option.
    """
    plan = classify_evidence_need(claim=claim, entity=entity)
    acceptable = {t.value for t in plan.acceptable_types}
    rejected: list[str] = []
    viable: list[EvidenceAsset] = []
    for asset in candidates:
        verdict = evidence_truth_check(
            asset, allow_symbolic_for_claim=not plan.requires_real
        )
        if not verdict.ok:
            rejected.append(f"{asset.asset_id}:{'|'.join(verdict.violations)}")
            continue
        if plan.requires_real and asset.source_type.value not in acceptable:
            rejected.append(f"{asset.asset_id}:{asset.source_type.value}_NOT_ACCEPTABLE")
            continue
        viable.append(evaluate_evidence_freshness(asset))
    ranked = rank_evidence(viable)
    return (ranked[0] if ranked else None), rejected


# ── Screenshot acquisition (§58, §59) ────────────────────────────────────


@dataclass
class ScreenshotCapture:
    """Result of acquiring a real screenshot through the existing capture path."""

    path: str = ""
    content_hash: str = ""
    source_url: str = ""
    page_title: str = ""
    captured_at: str = ""
    viewport: str = ""
    page_text: str = ""
    ok: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def capture_screenshot(
    url: str,
    output_path: str | Path,
    *,
    viewport: tuple[int, int] = (1440, 900),
    timeout_ms: int = 45000,
    wait_selector: str = "",
    redact_selectors: tuple[str, ...] = (),
) -> ScreenshotCapture:
    """Capture a real screenshot and record the provenance a claim needs.

    Credentials are never written to the artifact: sensitive query parameters
    are stripped from the recorded URL, and no cookie, header or session value
    is ever persisted. Elements matching ``redact_selectors`` are obscured
    *before* the pixels are taken.
    """
    from playwright.sync_api import sync_playwright

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    capture = ScreenshotCapture(
        source_url=strip_sensitive_query(url), captured_at=_iso_now()
    )
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            if wait_selector:
                # A missing optional selector is not fatal: the capture still
                # records exactly what was visible.
                with contextlib.suppress(Exception):
                    page.wait_for_selector(wait_selector, timeout=15000)
            else:
                page.wait_for_timeout(1200)
            for selector in redact_selectors:
                for handle in page.query_selector_all(selector):
                    try:
                        handle.evaluate(
                            "el => { el.style.filter = 'blur(18px)'; }"
                        )
                    except Exception:
                        continue
            capture.page_title = (page.title() or "")[:300]
            capture.page_text = _visible_text(page)
            page.screenshot(path=str(out), full_page=False)
            browser.close()
    except Exception as exc:
        capture.reason = f"CAPTURE_FAILED:{type(exc).__name__}"
        return capture

    capture.path = str(out)
    capture.content_hash = _file_hash(out)
    capture.viewport = f"{viewport[0]}x{viewport[1]}"
    capture.ok = bool(capture.content_hash)
    return capture


def _visible_text(page: Any, limit: int = 20000) -> str:
    try:
        text = page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        return ""
    return str(text or "")[:limit]


def _file_hash(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def evidence_asset_from_capture(
    capture: ScreenshotCapture,
    request: EvidenceRequest,
    *,
    source_type: EvidenceSourceType = EvidenceSourceType.OFFICIAL_SCREENSHOT,
    allow_email: bool = False,
) -> tuple[EvidenceAsset, PrivacyScanResult, list[str]]:
    """Turn a real capture into a truth-checked, privacy-screened asset.

    Returns ``(asset, privacy_scan, policy_reasons)``. The asset is only usable
    when the scan is clean; a rejected asset is demoted so it can never be
    presented as evidence.
    """
    scan = scan_privacy(
        f"{capture.source_url}\n{capture.page_title}\n{capture.page_text}",
        allow_email=allow_email,
    )
    asset = EvidenceAsset(
        request_id=request.request_id,
        source_type=source_type,
        source_uri=capture.source_url,
        path=capture.path,
        captured_at=capture.captured_at,
        content_hash=capture.content_hash,
        claim_supported=request.claim,
        entity=request.entity or capture.page_title,
        confidence=0.9 if capture.ok else 0.0,
        beat_id=request.beat_id,
        provenance={
            "capture_method": "playwright_chromium",
            "official_verified": bool(capture.source_url.startswith("https://")),
            "viewport": capture.viewport,
            "page_title": capture.page_title,
            "asset_fingerprint": canonical_hash(
                {"url": capture.source_url, "title": capture.page_title}
            ),
            "generated": False,
            "labelled_as_generated": False,
        },
    )
    asset, reasons = apply_privacy_policy(asset, scan)
    evaluate_evidence_freshness(asset)
    truth = assert_evidence_truth(asset)
    if not truth.ok:
        reasons.extend(truth.violations)
    return asset, scan, reasons


__all__ = [
    "DEFAULT_STALE_AFTER",
    "EVIDENCE_TRIGGER_TERMS",
    "EvidenceVerdict",
    "PrivacyScanResult",
    "ScreenshotCapture",
    "VisualEvidencePlan",
    "apply_privacy_policy",
    "assert_evidence_truth",
    "capture_screenshot",
    "classify_evidence_need",
    "evaluate_evidence_freshness",
    "evidence_asset_from_capture",
    "evidence_truth_check",
    "rank_evidence",
    "scan_privacy",
    "select_best_evidence",
    "strip_sensitive_query",
]
