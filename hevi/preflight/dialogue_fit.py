"""preflight.dialogue_fit —— 对白与模型窗口适配。

标定（普通话清晰戏剧对白）：
- CLEAR_CPS = 4.5 字／秒：清晰可懂的上限（约 270 字／分钟）。
- HARD_CPS = 6.0 字／秒：超过即赶话，转写含糊概率陡增。
- 8 秒窗：清晰预算 36 字；>48 字判 FAIL（拦住，须拆镜或删减）；
  36–48 字判 WARN（偏快，生成后必过 ASR 验真）。
- 讲解段（narration/commentary）对白走 TTS，不占视频模型窗口，
  只出 INFO，不参与 FAIL。

字数只计 CJK 表意字与数字字母，标点不计。
"""

from __future__ import annotations

import re

from hevi.preflight.beats import Beat, get_model_spec
from hevi.preflight.findings import Finding

CLEAR_CPS = 4.5
HARD_CPS = 6.0

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf0-9a-zA-Z]")


def count_speech_chars(text: str) -> int:
    return len(_CJK_RE.findall(text or ""))


def fit_dialogue(beat: Beat, model: str) -> list[Finding]:
    spec = get_model_spec(model)
    if beat.kind != "dialogue":
        return [Finding(
            "INFO", "dialogue_window_na",
            f"{beat.kind} 段对白走 TTS，不占视频模型窗口",
            beat_id=beat.beat_id,
        )]

    window = spec.window_s if spec.window_s else beat.duration_s
    findings: list[Finding] = []

    lines = beat.dialogue_lines or []
    if not lines and beat.text.strip():
        lines = [type("L", (), {"speaker": beat.characters[0].char_id if beat.characters else "", "text": beat.text})()]  # type: ignore[attr-defined]

    total = 0
    per_line: list[dict[str, object]] = []
    for ln in lines:
        n = count_speech_chars(ln.text)
        total += n
        per_line.append({"speaker": ln.speaker, "chars": n})

    cps = total / window if window else 0.0
    clear_budget = int(CLEAR_CPS * window)
    hard_budget = int(HARD_CPS * window)
    detail = {
        "model": model, "window_s": window, "chars": total,
        "cps": round(cps, 2), "clear_budget": clear_budget,
        "hard_budget": hard_budget, "per_line": per_line,
    }
    if total > hard_budget:
        findings.append(Finding(
            "FAIL", "dialogue_over_window",
            f"对白 {total} 字塞进 {window:g} 秒窗（{cps:.1f} 字／秒，清晰上限 {CLEAR_CPS}）："
            f"须拆镜或删减到 {clear_budget} 字内，否则必赶话、转写必糊",
            beat_id=beat.beat_id, detail=detail,
        ))
    elif total > clear_budget:
        findings.append(Finding(
            "WARN", "dialogue_fast",
            f"对白 {total} 字／{window:g} 秒（{cps:.1f} 字／秒）超清晰预算 {clear_budget} 字："
            f"偏快，生成后必过 ASR 验真",
            beat_id=beat.beat_id, detail=detail,
        ))
    else:
        findings.append(Finding(
            "INFO", "dialogue_fit_ok",
            f"对白 {total} 字／{window:g} 秒（{cps:.1f} 字／秒）在清晰预算内",
            beat_id=beat.beat_id, detail=detail,
        ))
    return findings
