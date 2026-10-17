"""生成后逐镜审片清单 (Review Checklist) —— 落地 research.md 实证的 16 项防穿帮审片准则。

包含：
1. 脸和身形
2. 服装
3. 道具和手
4. 视线和轴线
5. 出入画方向
6. 剪辑点动作匹配 (适合 VLM 粗筛)
7. 光线
8. 背景和布景 (适合 VLM 粗筛)
9. 语言
10. 音色 (适合音频模型/听感粗筛)
11. 口型
12. 画面文字
13. 物理肢体
14. 表演情绪 (适合 VLM 粗筛)
15. 声音底噪
16. 场记记录
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from hevi.prompt.continuity.schemas import ShotContract


@dataclass
class ReviewItem:
    item_no: int
    category: str
    criteria: str
    shot_focus: str
    vlm_screenable: bool = False  # research.md: 6/8/10/14 适合先拿视觉/听觉模型粗筛，再人工复核
    status: str = "pending"  # pending / pass / fail

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def review_checklist(shot: ShotContract) -> list[ReviewItem]:
    """根据具体镜头契约动态生成 16 项逐镜审片清单。"""
    sid = shot.shot_id or "Current-Shot"
    chars = ", ".join(shot.character_names) if shot.character_names else "出场角色"
    props = ", ".join(shot.prop_names) if shot.prop_names else "无显式道具"
    hands = str(shot.hands_occupation) if shot.hands_occupation else "双手自然"
    speaker = (
        shot.dialogue.speaker
        if shot.dialogue
        else (shot.dialogue_lines[0].speaker if shot.dialogue_lines else "无对白")
    )

    items = [
        ReviewItem(
            item_no=1,
            category="脸和身形",
            criteria="与定妆图并排比对，五官、发际线、痣或疤都在；宁要“更像本人”，不要“更清晰”。",
            shot_focus=f"比对角色 [{chars}] 定妆母卡，核验五官轮廓与特征标记无漂移。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=2,
            category="服装",
            criteria="扣子、拉链、袖口卷起、破损和脏污与故事日一致；配饰（耳环、手表）在位。",
            shot_focus=f"故事日 [{shot.story_day}] 服装破损与穿戴状态是否与当日基准一致。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=3,
            category="道具和手",
            criteria="道具在哪只手、液位、烟长是否连贯，严禁凭空出现或消失；对照前后帧。",
            shot_focus=f"手部状态 [{hands}] 与涉及道具 [{props}]，确认双手未被非法重复占用。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=4,
            category="视线和轴线",
            criteria="正反打视线方向相反、视线高低度匹配；严格遵守 180° 规则，无无理由越轴。",
            shot_focus=f"视线规划 [{shot.eyeline_angle or '标准视平'}]，核对正反打视线矢量。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=5,
            category="出入画方向",
            criteria="人物出入画方向和行进动势连贯；避免右出又从右进。",
            shot_focus=f"出入画设置 [{shot.in_out_direction or '画中静止'}]，检查与前后镜方向接续。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=6,
            category="剪辑点动作匹配",
            criteria="动作发生在台词的同一个词上(match on action)；姿态与上一镜尾帧接续。",
            shot_focus=f"动作对齐锚点: [{shot.match_on_action or '自然动作衔接'}]。",
            vlm_screenable=True,
        ),
        ReviewItem(
            item_no=7,
            category="光线",
            criteria="主光方向、时段、色温与场景卡一致；同一场戏内光影不跳变。",
            shot_focus=f"场景 [{shot.scene_name}] 布光基准与色调统一性核验。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=8,
            category="背景和布景",
            criteria="窗、门、家具相对几何位置固定；反打背景与场景参考一致。",
            shot_focus=f"检查场景空间要素，反打角度无幻觉新增背景物体。",
            vlm_screenable=True,
        ),
        ReviewItem(
            item_no=9,
            category="语言",
            criteria="每句台词是指定语言(普通话)，禁止被场景文化带偏(如日式布景冒出日语)；口音一致。",
            shot_focus="台词语音为清晰纯正普通话，无外语乱入。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=10,
            category="音色",
            criteria="与角色音色卡一致；把同一角色的所有台词按角色连起来听一遍无漂移。",
            shot_focus=f"说话人 [{speaker}] 的音高、音色质感与 VoiceCard 是否完全贴合。",
            vlm_screenable=True,
        ),
        ReviewItem(
            item_no=11,
            category="口型",
            criteria="说话人嘴型匹配；画外台词画面中无人张嘴；台词完整无截断吞字。",
            shot_focus=f"说话人 [{speaker}] 口型开合精准；非发声角色闭嘴无乱动口型。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=12,
            category="画面文字",
            criteria="无字幕、乱码、AI水印；画面内仅允许白名单文字出现。",
            shot_focus=f"画内文字审查: 白名单约定 [{shot.on_screen_text or '无文字'}]，无多余乱码。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=13,
            category="物理",
            criteria="没有多余手指或肢体畸变、无穿模、悬浮或反物理形变。",
            shot_focus="四肢解剖结构完整，手部指节与面部结构正常无变形。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=14,
            category="表演情绪",
            criteria="表演情绪与相邻镜头的情绪刻度连贯一致，无喜怒无常断崖突变。",
            shot_focus=f"情绪刻度 [{shot.emotion_scale or '自然平稳'}] 与前后节拍咬合。",
            vlm_screenable=True,
        ),
        ReviewItem(
            item_no=15,
            category="声音",
            criteria="环境底噪连续不断流；配乐按策略执行，无音乐镜头模型严禁私加 BGM。",
            shot_focus="音频轨底噪连贯平稳，无私自生成的背景杂音或多余配乐。",
            vlm_screenable=False,
        ),
        ReviewItem(
            item_no=16,
            category="记录",
            criteria="在生成日志中标记“选用/废弃＋原因”，更新道具和伤情状态账本作为下一镜交接。",
            shot_focus=f"登记镜号 [{sid}] 的条次与 seed，更新 start/end 衔接账本。",
            vlm_screenable=False,
        ),
    ]

    return items
