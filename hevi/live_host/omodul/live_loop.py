"""omodul：整轮直播交互编排（听→想→说），流式逐句输出。"""

from __future__ import annotations

import logging
from pathlib import Path

from hevi.live_host.oprim.registry import EngineRegistry
from hevi.live_host.oprim.silero_vad import SileroVAD
from hevi.live_host.oprim.stt_whisper import WhisperSTT
from hevi.live_host.oskill.skill_listen import skill_listen
from hevi.live_host.oskill.skill_speak import skill_speak
from hevi.live_host.oskill.skill_think import skill_think
from hevi.live_host.schemas import EngineConfig, TurnInput, TurnOutput

logger = logging.getLogger(__name__)


class LiveHost:
    """赛博小雅直播主持：一轮「输入 → 输出音频」的完整编排。"""

    def __init__(
        self, cfg: EngineConfig | None = None, workdir: str | Path = "audit/live_host/run"
    ) -> None:
        self.cfg = cfg or EngineConfig()
        self.registry = EngineRegistry(self.cfg)
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.vad = SileroVAD() if self.cfg.stt == "whisper" else None

    def _apply_aigc_label(self, text: str) -> str:
        if self.cfg.aigc_label_enabled:
            return f"【{self.cfg.aigc_label_text}】{text}"
        return text

    def turn(self, turn: TurnInput) -> TurnOutput:
        """跑完整一轮。"""
        stt = self.registry.get("stt")
        llm = self.registry.get("llm")
        tts = self.registry.get("tts")

        out = TurnOutput()
        # 听
        out = skill_listen(turn, stt, self.vad, out)
        if not out.question.strip():
            return out

        # 想（流式）
        think = skill_think(out.question, llm, out, self.cfg)
        out.reply_text = think.reply_text
        out.utterances = think.utterances

        # 说（逐句 TTS）
        skill_speak(out.utterances, tts, self.cfg, out.timing, self.workdir)
        return out

    def turn_labeled(self, turn: TurnInput) -> TurnOutput:
        """跑一轮并对回复加 AIGC 标识（用于对外输出）。"""
        out = self.turn(turn)
        if self.cfg.aigc_label_enabled and out.reply_text:
            # 仅文本层面打标；音频侧由 OBS 贴片实现（见 DESIGN §8）
            out.reply_text = self._apply_aigc_label(out.reply_text)
        return out
