"""SPEC-007 批1 ②:J/L-cut 判定算法——废掉 scratchpad 那版硬编码场景专属常数
(`_JCUT_ADVANCE_S = {3: 0.4, 5: 0.4}` 这类),改成按 `SceneScriptSegment` 的
speaker/target/camera_movement 数据自动判定,不是场景常数表。

判据(不是启发式发明,是既定设计):
- **L-cut**:下一段是反应镜头(`camera_movement` 含"反应")且上一段有台词——上一段说话人
  的话音延续到下一段的听者反应画面。
- **J-cut**:下一段的说话人跟上一段的说话人是同一个角色(同一人跨段继续说话)——下一段的
  台词提前进入,音频先于画面切换。
- 两个条件都不满足 → 不做特殊处理,走默认的自然剪辑点(`style=None`)。

L 判定优先于 J 检查(先看是不是反应镜头,不是才看说话人是否延续)——两个条件在实际数据里
理论上不会同时成立(反应镜头的段本身通常没有台词,或说话人已经变成了旁观者),但顺序上
明确优先级,不依赖字典/条件表达式求值顺序的隐式行为。
"""

from __future__ import annotations

from dataclasses import dataclass

from hevi.director.pipeline_schemas import SceneScriptSegment

_DEFAULT_OFFSET_S = 0.4  # soffy 给定区间 0.3-0.5s 的中点
_REACTION_MARKER = "反应"


@dataclass(frozen=True)
class CutStyleDecision:
    style: str | None  # "J" / "L" / None
    offset_s: float


def classify_seam_cut_style(
    seg_a: SceneScriptSegment, seg_b: SceneScriptSegment, *, offset_s: float = _DEFAULT_OFFSET_S
) -> CutStyleDecision:
    a_speaker = seg_a.dialogue[0].character_name if seg_a.dialogue else ""
    b_speaker = seg_b.dialogue[0].character_name if seg_b.dialogue else ""

    if _REACTION_MARKER in seg_b.camera_movement and seg_a.dialogue:
        return CutStyleDecision(style="L", offset_s=offset_s)
    if a_speaker and b_speaker and a_speaker == b_speaker:
        return CutStyleDecision(style="J", offset_s=offset_s)
    return CutStyleDecision(style=None, offset_s=0.0)
