"""Narrator AI CLI 适配层。未安装 CLI / 未配置 key 时明确降级,不假装出片。"""

from hevi.narrator.client import NarratorUnavailable, narrator_status, run_narrator

__all__ = ["NarratorUnavailable", "narrator_status", "run_narrator"]
