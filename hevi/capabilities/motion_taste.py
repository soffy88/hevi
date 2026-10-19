"""Motion taste capabilities: Emil Kowalski animation rules as callable capabilities.

Registers three ``kind="line"`` capabilities so every product line can invoke
the taste rules by dotted name (CAPABILITY_CONTRACT.md, user addendum
2026-10-14; precedent: ``agent.ops_bridge`` and the ``qa.*`` safety gates):

* ``motion.review``      — review-animations: review animation code against the
  ten non-negotiable standards; verdict Block / Approve.
* ``motion.audit_plan``  — improve-animations: scan a codebase directory, emit a
  prioritized audit table plus self-contained ``plans/`` implementation plans.
* ``motion.perfcheck``   — animation-performance: diagnose frame-budget causes
  (property tier, thread, CSS-variable storms, blur cost, will-change abuse).

Rule source: ``docs/rules/animation_taste.md`` (Taste R1), distilled from
``emilkowalski/skills`` (MIT). The checks below are the statically-decidable
subset of the rule card; feel judgments (crossfade blur, spring bounce,
opacity/height balance) stay manual per the card.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import Capability, CapabilityResult, register

RULES_VERSION = "taste-r1"

# Exact values from docs/rules/animation_taste.md — never approximated.
EASE_OUT = "cubic-bezier(0.23, 1, 0.32, 1)"
EASE_IN_OUT = "cubic-bezier(0.77, 0, 0.175, 1)"
EASE_DRAWER = "cubic-bezier(0.32, 0.72, 0, 1)"

_SEV_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


@dataclass
class Finding:
    rule: str
    severity: str  # HIGH | MEDIUM | LOW
    file: str
    line: int
    excerpt: str
    why: str
    fix: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "excerpt": self.excerpt,
            "why": self.why,
            "fix": self.fix,
        }


# ---------------------------------------------------------------------------
# Static checks (deterministic; sorted output for reproducibility)
# ---------------------------------------------------------------------------

def _lines(text: str) -> list[str]:
    return text.splitlines()


def _check_transition_all(fname: str, text: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(_lines(text), 1):
        if re.search(r"transition\s*:\s*all\b", ln) or "transition-all" in ln:
            out.append(Finding(
                rule="transition_all", severity="HIGH", file=fname, line=i,
                excerpt=ln.strip()[:160],
                why="`transition: all` animates whatever changes next, including "
                    "layout properties nobody intended to animate.",
                fix="Name exact properties, e.g. `transition: transform 200ms " + EASE_OUT + "`.",
            ))
    return out


def _check_scale_zero(fname: str, text: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(_lines(text), 1):
        if re.search(r"scale\(\s*0(\.0+)?\s*\)", ln):
            out.append(Finding(
                rule="scale_zero", severity="HIGH", file=fname, line=i,
                excerpt=ln.strip()[:160],
                why="Nothing in the real world appears from nothing; scale(0) "
                    "looks like it came from nowhere.",
                fix="Start from `scale(0.95)` combined with `opacity: 0`.",
            ))
    return out


def _check_ease_in(fname: str, text: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(_lines(text), 1):
        if re.search(r"\bease-in\b(?!-out)", ln):
            out.append(Finding(
                rule="ease_in", severity="HIGH", file=fname, line=i,
                excerpt=ln.strip()[:160],
                why="`ease-in` delays the initial movement — the exact moment the "
                    "user is watching most closely; it feels sluggish.",
                fix="Use `ease-out` or a strong custom curve: " + EASE_OUT + ".",
            ))
    return out


def _check_long_duration(fname: str, text: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(_lines(text), 1):
        low = ln.lower()
        if "transition" not in low and "animation" not in low and "duration" not in low:
            continue
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*ms\b", ln):
            if float(m.group(1)) > 300:
                out.append(Finding(
                    rule="long_duration", severity="MEDIUM", file=fname, line=i,
                    excerpt=ln.strip()[:160],
                    why="UI animations stay under 300ms; slower feels unresponsive.",
                    fix="Reduce to 150-250ms for UI elements.",
                ))
                break
        else:
            for m in re.finditer(r"(\d+(?:\.\d+)?)\s*s\b", ln):
                if float(m.group(1)) > 0.3:
                    out.append(Finding(
                        rule="long_duration", severity="MEDIUM", file=fname, line=i,
                        excerpt=ln.strip()[:160],
                        why="UI animations stay under 300ms; slower feels unresponsive.",
                        fix="Reduce to 150-250ms for UI elements.",
                    ))
                    break
    return out


def _check_origin_center_popover(fname: str, text: str) -> list[Finding]:
    if not re.search(r"popover|dropdown|tooltip|\bmenu\b", text, re.I):
        return []
    out = []
    for i, ln in enumerate(_lines(text), 1):
        if re.search(r"transform-origin\s*:\s*center", ln, re.I):
            out.append(Finding(
                rule="origin_center_popover", severity="MEDIUM", file=fname, line=i,
                excerpt=ln.strip()[:160],
                why="Popovers/dropdowns/tooltips should scale from their trigger, "
                    "not from center. (Modals are exempt — they stay centered.)",
                fix="Set `transform-origin` to the trigger location "
                    "(`var(--transform-origin)` in Base UI).",
            ))
    return out


def _check_keyframes_rapid(fname: str, text: str) -> list[Finding]:
    if "@keyframes" not in text:
        return []
    if not re.search(r"\btoast\b|\btoggle\b", text, re.I):
        return []
    ln_no = next((i for i, ln in enumerate(_lines(text), 1) if "@keyframes" in ln), 1)
    return [Finding(
        rule="keyframes_rapid", severity="MEDIUM", file=fname, line=ln_no,
        excerpt="@keyframes present alongside toast/toggle usage",
        why="Keyframes restart from zero on interruption; rapidly-triggered "
            "elements (toasts, toggles) need retargetable transitions.",
        fix="Use CSS transitions for rapidly-triggered elements.",
    )]


def _check_layout_props(fname: str, text: str) -> list[Finding]:
    out = []
    pat = re.compile(
        r"(?:transition|animation)[^;{]*\b(width|height|margin|padding|top|left|"
        r"border-width)\b"
    )
    for i, ln in enumerate(_lines(text), 1):
        m = pat.search(ln)
        if m:
            out.append(Finding(
                rule="layout_props", severity="HIGH", file=fname, line=i,
                excerpt=ln.strip()[:160],
                why=f"Animating `{m.group(1)}` triggers layout+paint+composite "
                    "every frame — the most expensive tier.",
                fix="Animate `transform`/`opacity` instead "
                    "(`scale()` for size, `translate()` for position).",
            ))
    return out


def _check_motion_shorthand(fname: str, text: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(_lines(text), 1):
        m = re.search(r"animate=\{\{[^}]*\b(x|y|scale|rotate)\s*:", ln)
        if m:
            out.append(Finding(
                rule="motion_shorthand", severity="MEDIUM", file=fname, line=i,
                excerpt=ln.strip()[:160],
                why=f"Framer Motion `{m.group(1)}` shorthand runs on the main thread "
                    "and drops frames when the page is busy.",
                fix='Use the full transform string: `animate={{ transform: '
                    '"translateX(100px)" }}`.',
            ))
    return out


def _check_no_reduced_motion(fname: str, text: str) -> list[Finding]:
    if "prefers-reduced-motion" in text:
        return []
    if not re.search(r"transition|@keyframes|animate=", text):
        return []
    return [Finding(
        rule="no_reduced_motion", severity="MEDIUM", file=fname, line=1,
        excerpt="motion present, no prefers-reduced-motion handling",
        why="Animations can cause motion sickness; reduced motion must be honored.",
        fix="Add `@media (prefers-reduced-motion: reduce)` — gentler variant, "
            "not zero: keep opacity/color, drop movement.",
    )]


def _check_ungated_hover(fname: str, text: str) -> list[Finding]:
    if "@media (hover: hover)" in text:
        return []
    if not re.search(r":hover", text):
        return []
    if not re.search(r":hover[^{]*\{[^}]*(transform|transition)", text):
        return []
    return [Finding(
        rule="ungated_hover", severity="LOW", file=fname, line=1,
        excerpt=":hover motion without pointer gating",
        why="Touch devices fire :hover on tap, causing false positives.",
        fix="Gate hover motion behind `@media (hover: hover) and (pointer: fine)`.",
    )]


def _check_css_var_transform(fname: str, text: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(_lines(text), 1):
        if re.search(r"(?:transform|translate[XY]?)\s*:[^;]*var\(--", ln):
            out.append(Finding(
                rule="css_var_transform", severity="HIGH", file=fname, line=i,
                excerpt=ln.strip()[:160],
                why="CSS variables inherit: changing one on a parent recalculates "
                    "styles for every child, every frame.",
                fix="Set `transform` directly on the animating element instead of "
                    "driving it through a CSS variable.",
            ))
    return out


def _check_heavy_blur(fname: str, text: str) -> list[Finding]:
    out = []
    for i, ln in enumerate(_lines(text), 1):
        for m in re.finditer(r"blur\(\s*(\d+(?:\.\d+)?)\s*px\s*\)", ln):
            if float(m.group(1)) > 20:
                out.append(Finding(
                    rule="heavy_blur", severity="MEDIUM", file=fname, line=i,
                    excerpt=ln.strip()[:160],
                    why="`filter: blur()` over 20px gets expensive fast, "
                        "especially in Safari.",
                    fix="Keep animated blur under 20px; 2-5px suffices to mask "
                        "a crossfade.",
                ))
                break
    return out


def _check_state_in_raf(fname: str, text: str) -> list[Finding]:
    if "requestAnimationFrame" not in text:
        return []
    if not re.search(r"\bset[A-Z]\w*\s*\(", text):
        return []
    return [Finding(
        rule="state_in_raf", severity="MEDIUM", file=fname, line=1,
        excerpt="requestAnimationFrame alongside setState-style calls",
        why="A hand-rolled animation calling setState every frame re-renders "
            "every 16.7ms and blows the frame budget.",
        fix="Write to `ref.current.style.transform` (or a motion value) "
            "instead of state.",
    )]


def _check_will_change_abuse(fname: str, text: str) -> list[Finding]:
    if re.search(r"\*\s*\{[^}]*will-change", text):
        return [Finding(
            rule="will_change_abuse", severity="LOW", file=fname, line=1,
            excerpt="will-change on `*` selector",
            why="Every promoted layer costs GPU memory; `*` promotes everything.",
            fix="Add `will-change: transform` only to the animating element, "
                "and only after seeing a 1px shift or measured dropped frames.",
        )]
    return []


_REVIEW_CHECKS = [
    _check_transition_all,
    _check_scale_zero,
    _check_ease_in,
    _check_long_duration,
    _check_origin_center_popover,
    _check_keyframes_rapid,
    _check_layout_props,
    _check_motion_shorthand,
    _check_no_reduced_motion,
    _check_ungated_hover,
    _check_css_var_transform,
    _check_heavy_blur,
    _check_state_in_raf,
    _check_will_change_abuse,
]

# animation-performance is the performance subset, diagnosed cause-first.
_PERF_CHECKS = [
    _check_transition_all,
    _check_layout_props,
    _check_motion_shorthand,
    _check_css_var_transform,
    _check_heavy_blur,
    _check_state_in_raf,
    _check_will_change_abuse,
    _check_long_duration,
]


def _run_checks(fname: str, text: str, checks: list) -> list[Finding]:
    findings: list[Finding] = []
    for check in checks:
        findings.extend(check(fname, text))
    findings.sort(key=lambda f: (_SEV_ORDER[f.severity], f.file, f.line, f.rule))
    return findings


def _verdict(findings: list[Finding]) -> str:
    # review-animations: Block on any feel-breaking (HIGH) regression, else Approve.
    return "Block" if any(f.severity == "HIGH" for f in findings) else "Approve"


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

def _findings_table_md(findings: list[Finding]) -> str:
    if not findings:
        return "No findings — the motion already meets the bar.\n"
    rows = ["| Before | After | Why |", "| --- | --- | --- |"]
    for f in findings:
        before = f"`{f.file}:{f.line}` {f.excerpt}".replace("|", "\\|")
        after = f.fix.replace("|", "\\|")
        why = f"**[{f.severity}]** {f.why}".replace("|", "\\|")
        rows.append(f"| {before} | {after} | {why} |")
    return "\n".join(rows) + "\n"


def _write_review_report(out_dir: Path, stem: str, findings: list[Finding],
                         verdict: str, meta: dict[str, Any]) -> tuple[Path, Path]:
    md_path = out_dir / f"{stem}_review.md"
    json_path = out_dir / f"{stem}_review.json"
    md = (
        f"# Motion Review — `{meta.get('target', stem)}`\n\n"
        f"Rules: docs/rules/animation_taste.md ({RULES_VERSION}). "
        f"Verdict: **{verdict}**\n\n"
        f"## Findings ({len(findings)})\n\n"
        + _findings_table_md(findings)
        + "\n## Notes\n\n"
        "- Feel judgments (crossfade blur, spring bounce, opacity/height balance) "
        "cannot be settled from code: replay at 2-5x duration or frame-by-frame "
        "in DevTools, test gestures on a real device, and re-check with fresh "
        "eyes the next day.\n"
    )
    md_path.write_text(md, encoding="utf-8")
    payload = {
        "rules_version": RULES_VERSION,
        "target": meta.get("target", stem),
        "verdict": verdict,
        "findings": [f.as_dict() for f in findings],
        "meta": meta,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path


def _write_perf_report(out_dir: Path, stem: str, findings: list[Finding]) -> tuple[Path, Path]:
    md_path = out_dir / f"{stem}_perf.md"
    json_path = out_dir / f"{stem}_perf.json"
    parts = [f"# Animation Performance Diagnosis — `{stem}`\n",
             f"Rules: docs/rules/animation_taste.md ({RULES_VERSION}).\n"]
    if not findings:
        parts.append("No frame-budget causes found from code. If it still janks, "
                     "record the DevTools Performance panel on a mid-range phone "
                     "— never conclude from a fast machine.\n")
    parts.extend(
        f"**{f.file}:{f.line}**\n"
        f"Cause: {f.rule} — {f.why}\n"
        f"Before: `{f.excerpt}`\n"
        f"After: {f.fix}\n"
        f"Verified: from code\n"
        for f in findings
    )
    md_path.write_text("\n".join(parts), encoding="utf-8")
    payload = {
        "rules_version": RULES_VERSION,
        "target": stem,
        "diagnoses": [f.as_dict() for f in findings],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path


def _write_audit_report(out_dir: Path, stem: str, file_findings: dict[str, list[Finding]],
                        plans: list[str], meta: dict[str, Any]) -> tuple[Path, Path]:
    md_path = out_dir / f"{stem}_audit.md"
    json_path = out_dir / f"{stem}_audit.json"
    total = sum(len(v) for v in file_findings.values())
    sev = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for v in file_findings.values():
        for f in v:
            sev[f.severity] += 1
    rows = ["| # | Severity | Location | Finding | Fix summary |",
            "| --- | --- | --- | --- | --- |"]
    n = 0
    for fname in sorted(file_findings):
        for f in sorted(file_findings[fname],
                        key=lambda x: (_SEV_ORDER[x.severity], x.line, x.rule)):
            n += 1
            rows.append(
                f"| {n} | {f.severity} | `{f.file}:{f.line}` | "
                f"{f.rule}: {f.why[:90]} | {f.fix[:90]} |"
            )
    md = (
        f"# Motion Audit — `{meta.get('repo_path', stem)}`\n\n"
        f"Rules: docs/rules/animation_taste.md ({RULES_VERSION}). "
        f"Files scanned: {meta.get('files_scanned', 0)}. "
        f"Findings: {total} (HIGH {sev['HIGH']} / MEDIUM {sev['MEDIUM']} / "
        f"LOW {sev['LOW']}).\n\n"
        f"## Prioritized findings (impact / effort)\n\n"
        + "\n".join(rows)
        + "\n\n## Implementation plans\n\n"
        + ("\n".join(f"- `{p}`" for p in plans) if plans else "No plans generated.")
        + "\n"
    )
    md_path.write_text(md, encoding="utf-8")
    payload = {
        "rules_version": RULES_VERSION,
        "repo_path": meta.get("repo_path", stem),
        "files_scanned": meta.get("files_scanned", 0),
        "severity_counts": sev,
        "findings": {k: [f.as_dict() for f in v] for k, v in sorted(file_findings.items())},
        "plans": plans,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path


def _write_plan_files(plans_dir: Path, file_findings: dict[str, list[Finding]]) -> list[str]:
    """Group findings by rule into self-contained plans (improve-animations format)."""
    plans_dir.mkdir(parents=True, exist_ok=True)
    by_rule: dict[str, list[Finding]] = {}
    for fname in sorted(file_findings):
        for f in file_findings[fname]:
            by_rule.setdefault(f.rule, []).append(f)
    written: list[str] = []
    for idx, rule in enumerate(sorted(by_rule,
                                     key=lambda r: _SEV_ORDER[by_rule[r][0].severity]), 1):
        items = sorted(by_rule[rule], key=lambda f: (f.file, f.line))
        slug = f"{idx:03d}-{rule.replace('_', '-')}"
        plan_path = plans_dir / f"{slug}.md"
        lines = [
            f"# Plan {idx:03d}: fix `{rule}` ({items[0].severity})",
            "",
            "## Problem",
            "",
            items[0].why,
            "",
            "## Exact target values (from docs/rules/animation_taste.md, never approximated)",
            "",
            f"- `--ease-out: {EASE_OUT}`",
            f"- `--ease-in-out: {EASE_IN_OUT}`",
            f"- `--ease-drawer: {EASE_DRAWER}`",
            "- UI durations: button 100-160ms, tooltip/popover 125-200ms, "
            "dropdown 150-250ms, modal/drawer 200-500ms, all < 300ms.",
            "",
            "## Locations",
            "",
        ]
        for f in items:
            lines.append(f"- `{f.file}:{f.line}` — `{f.excerpt[:120]}`")
            lines.append(f"  Fix: {f.fix}")
        lines += [
            "",
            "## Verification",
            "",
            "- Re-run `motion.review` on the touched files: expect `Approve` "
            "with zero findings for this rule.",
            "- Feel-check: replay the changed animation at 2-5x duration or "
            "frame-by-frame; test gestures on a real device.",
            "",
            "## Scope boundary",
            "",
            "- Touch only the locations listed above. Do not refactor unrelated motion.",
            "- Extend existing easing/duration tokens; do not invent parallel ones.",
        ]
        plan_path.write_text("\n".join(lines), encoding="utf-8")
        written.append(f"plans/{slug}.md")
    readme = plans_dir / "README.md"
    readme.write_text(
        "# Motion improvement plans\n\n"
        "Ordered by severity (HIGH first). Each plan is self-contained: exact "
        "file:line locations, exact target values, and verification steps.\n\n"
        + "\n".join(f"- [ ] `{p}`" for p in written)
        + "\n",
        encoding="utf-8",
    )
    return written


def _preview_mp4(out_dir: Path, stem: str, duration: float, aspect: str,
                 seed: int) -> tuple[str, str, float]:
    """2s lavfi preview artefact so the capability passes the ffprobe contract
    test (same pattern as agent.ops_bridge)."""
    from hevi.renderers.ffmpeg import resolve_ffmpeg_bin

    dur = float(duration) if duration and duration > 0 else 2.0
    res = "320x568" if aspect == "9:16" else "568x320"
    mp4_path = out_dir / f"{stem}_{seed}.mp4"
    cmd = [
        resolve_ffmpeg_bin(), "-y",
        "-f", "lavfi", "-i", f"color=c=slateblue:s={res}:d={dur}:rate=24",
        "-f", "lavfi", "-i", f"sine=f=440:r=48000:d={dur}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(mp4_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    sha = hashlib.sha256(mp4_path.read_bytes()).hexdigest()
    return str(mp4_path), sha, dur


# ---------------------------------------------------------------------------
# Renders
# ---------------------------------------------------------------------------

def _render_motion_review(params: dict[str, Any], out_dir: Path | str, *,
                          duration: float, aspect: str, seed: int) -> CapabilityResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    code = params["code"]
    language = params.get("language", "css")
    context = params.get("context", "")
    fname = f"{context or 'snippet'}.{language}" if context else f"snippet.{language}"
    findings = _run_checks(fname, code, _REVIEW_CHECKS)
    verdict = _verdict(findings)
    stem = f"motion_review_{seed}"
    md_path, json_path = _write_review_report(
        out, stem, findings, verdict,
        {"target": fname, "language": language, "seed": seed},
    )
    mp4, sha, dur = _preview_mp4(out, stem, duration, aspect, seed)
    return CapabilityResult(
        mp4=mp4, duration_s=dur, sha256=sha,
        qa={
            "verdict": verdict,
            "findings_count": len(findings),
            "severity_counts": {
                s: sum(1 for f in findings if f.severity == s)
                for s in ("HIGH", "MEDIUM", "LOW")
            },
            "report_md": str(md_path),
            "report_json": str(json_path),
            "rules_version": RULES_VERSION,
        },
    )


def _render_motion_perf(params: dict[str, Any], out_dir: Path | str, *,
                        duration: float, aspect: str, seed: int) -> CapabilityResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    code = params["code"]
    language = params.get("language", "css")
    context = params.get("context", "")
    fname = f"{context or 'snippet'}.{language}" if context else f"snippet.{language}"
    findings = _run_checks(fname, code, _PERF_CHECKS)
    stem = f"motion_perf_{seed}"
    md_path, json_path = _write_perf_report(out, stem, findings)
    mp4, sha, dur = _preview_mp4(out, stem, duration, aspect, seed)
    return CapabilityResult(
        mp4=mp4, duration_s=dur, sha256=sha,
        qa={
            "diagnoses_count": len(findings),
            "report_md": str(md_path),
            "report_json": str(json_path),
            "rules_version": RULES_VERSION,
        },
    )


_SCAN_EXTS = {".css", ".scss", ".less", ".tsx", ".ts", ".jsx", ".js", ".vue"}
_SKIP_DIRS = {"node_modules", ".git", "dist", "build", ".next", "__pycache__",
              ".venv", "vendor", "coverage"}
_EFFORT_MAX_FILES = {"quick": 100, "standard": 500, "deep": 2000}


def _render_motion_audit(params: dict[str, Any], out_dir: Path | str, *,
                         duration: float, aspect: str, seed: int) -> CapabilityResult:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    repo_path = Path(params["repo_path"])
    if not repo_path.is_dir():
        raise CapabilityError(f"motion.audit_plan: repo_path is not a directory: {repo_path}")
    effort = params.get("effort", "standard")
    max_files = int(params.get("max_files", _EFFORT_MAX_FILES[effort]))
    max_files = min(max_files, _EFFORT_MAX_FILES["deep"])

    scanned = 0
    file_findings: dict[str, list[Finding]] = {}
    for root, dirs, files in __import__("os").walk(repo_path):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for fn in sorted(files):
            if scanned >= max_files:
                break
            if Path(fn).suffix not in _SCAN_EXTS:
                continue
            fp = Path(root) / fn
            try:
                if fp.stat().st_size > 512 * 1024:
                    continue
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            rel = str(fp.relative_to(repo_path) if fp.is_absolute() else fp)
            findings = _run_checks(rel, text, _REVIEW_CHECKS)
            if findings:
                file_findings[rel] = findings
        if scanned >= max_files:
            break

    stem = f"motion_audit_{seed}"
    plans = _write_plan_files(out / "plans", file_findings)
    md_path, json_path = _write_audit_report(
        out, stem, file_findings, plans,
        {"repo_path": str(repo_path), "files_scanned": scanned,
         "effort": effort, "seed": seed},
    )
    mp4, sha, dur = _preview_mp4(out, stem, duration, aspect, seed)
    total = sum(len(v) for v in file_findings.values())
    return CapabilityResult(
        mp4=mp4, duration_s=dur, sha256=sha,
        qa={
            "files_scanned": scanned,
            "files_with_findings": len(file_findings),
            "findings_total": total,
            "plans": plans,
            "report_md": str(md_path),
            "report_json": str(json_path),
            "rules_version": RULES_VERSION,
        },
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def _base_schema(extra_props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": extra_props,
        "required": required,
        "additionalProperties": False,
    }


def register_motion_taste_capabilities() -> None:
    register(Capability(
        name="motion.review",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema=_base_schema({
            "code": {"type": "string", "minLength": 1},
            "language": {"type": "string",
                         "enum": ["css", "tsx", "ts", "jsx", "js"]},
            "context": {"type": "string"},
        }, ["code"]),
        cpu_cost_hint=0.05,
        render=_render_motion_review,
        line="motion_taste",
        description="动画评审（review-animations）：按十项硬标准审查动画代码，"
                    "输出 findings 表 + Block/Approve 结论。规则见 "
                    "docs/rules/animation_taste.md。",
    ))
    register(Capability(
        name="motion.audit_plan",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema=_base_schema({
            "repo_path": {"type": "string", "minLength": 1},
            "effort": {"type": "string", "enum": ["quick", "standard", "deep"]},
            "max_files": {"type": "integer", "minimum": 1, "maximum": 2000},
        }, ["repo_path"]),
        cpu_cost_hint=0.05,
        render=_render_motion_audit,
        line="motion_taste",
        description="全库动画审计（improve-animations）：扫描目录的动效代码，"
                    "输出按影响/成本排序的审计表 + plans/ 下可执行的改进计划。",
    ))
    register(Capability(
        name="motion.perfcheck",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema=_base_schema({
            "code": {"type": "string", "minLength": 1},
            "language": {"type": "string",
                         "enum": ["css", "tsx", "ts", "jsx", "js"]},
            "context": {"type": "string"},
        }, ["code"]),
        cpu_cost_hint=0.05,
        render=_render_motion_perf,
        line="motion_taste",
        description="动画性能诊断（animation-performance）：按帧预算因果表定位"
                    "掉帧原因（属性层级/线程/CSS 变量风暴/blur/will-change）。",
    ))


register_motion_taste_capabilities()

__all__ = [
    "RULES_VERSION",
    "CapabilityError",
    "Finding",
    "register_motion_taste_capabilities",
]
