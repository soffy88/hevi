"""已知失败样本回归测试 —— 不是普通单测,是留档。

`tests/fixtures/audio/g_final_v1_acoustic_blend_sample.wav` 是 G-FINAL v1(2026-07-20,
装配层原声优先改造之前)的**真实**产物切片:原声 + 独立 TTS 两条音轨叠在一起,ASR 转写
出的是同一段连续转写里的口吃式重复("……可明日，就要别了，就要别了……"),不是两个
界限分明的 cue。`verify_no_duplicate_dialogue_renders`/`assert_no_duplicate_dialogue_
renders` 对这类"声学层面真叠在一起、糊成一段转写"的重复**测不出来**——这是文档里显式
记录过的已知边界(见 `native_dialogue.py` 模块 docstring),不是 bug。

这个测试的意义不是"验证功能正确",是**把这个已知边界钉死成可复测的实物**:不管以后
谁怎么改这道闸(比如想加 n-gram 重复启发式、能量/频谱检测把这类 blind spot 也堵上,
SPEC-007 backlog 里记过),都应该拿这个真实样本跑一遍——

- 如果还是测不出来(`violations == []`):边界没漂移,预期行为。
- 如果测出来了(有 violation):说明改进生效了,**更新这个测试的断言和上面的说明**,
  不要把这个真实样本删掉——它是目前唯一一份"闸抓不到"的实物证据,以后任何"能不能堵住
  这类 blind spot"的验证都得靠它,删了就再也造不出一模一样的真实撞见样本了。

真实文本核对(fixture 里说的是 s1_sg001 那句台词):
    "许兄……这半年清扬相待，情逾骨肉——可明日，就要别了。"
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hevi.assembly.native_dialogue import verify_no_duplicate_dialogue_renders

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
_FIXTURE = Path(__file__).parent / "fixtures" / "audio" / "g_final_v1_acoustic_blend_sample.wav"


@pytest.mark.skipif(not _HAS_FFMPEG, reason="needs ffmpeg/ffprobe")
@pytest.mark.skipif(not _FIXTURE.exists(), reason=f"missing regression fixture: {_FIXTURE}")
async def test_known_blind_spot_acoustic_blend_stutter_not_yet_detected(tmp_path: Path) -> None:
    violations = await verify_no_duplicate_dialogue_renders(
        _FIXTURE,
        expected_lines=[("王六郎", "许兄……这半年清扬相待，情逾骨肉——可明日，就要别了。")],
        tmp_wav=tmp_path / "probe.wav",
    )

    # 见模块 docstring:这个断言故意跟"这道闸应该抓住所有重复"相反——它记录的是当前
    # 已知边界。如果这个断言开始失败(意味着 violations 非空),说明检测能力提升了,
    # 更新断言 + docstring,不要删这个测试或删 fixture。
    assert violations == []
