"""导演词表 (Filmvision 107 项) —— 规范分类、风险等级与提示词表达。

收录来自 filmvision.ai/learn 的 107 个专业导演技法：
- Shot Types (25)
- Camera Movements (20)
- Lighting (15)
- Editing (20)
- Composition (12)
- Genres (15)

总计 107 项。
ai_risk 分类：
- stable: AI 视频模型生成表现稳定可靠
- caution: 极易引起肢体变形、面部走样或几何错乱，需谨慎使用
- post_only: 剪辑类技法(如 J/L cut、跳切、蒙太奇等)及破坏单镜连续性的极端运镜(如眩晕变焦、甩镜、旋转)，
            严禁进入文本生成提示词，必须留到剪辑单后期处理。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RiskLevel = Literal["stable", "caution", "post_only"]
Category = Literal[
    "shot_type",
    "camera_movement",
    "lighting",
    "editing",
    "composition",
    "genre",
]


@dataclass(frozen=True)
class VocabItem:
    id: str
    name_en: str
    name_zh: str
    prompt_hint_zh: str
    ai_risk: RiskLevel
    category: Category


# ── 107 项完整条目 ──────────────────────────────────────────────────────────

_VOCAB_LIST: list[VocabItem] = [
    # ── Shot Types (25 项) ──────────────────────────────────────────────────
    VocabItem(
        id="shot_type_close_up",
        name_en="Close-Up",
        name_zh="特写",
        prompt_hint_zh="特写镜头，焦点聚集于人物面部表情与细微情绪变化",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_extreme_close_up",
        name_en="Extreme Close-Up",
        name_zh="大特写",
        prompt_hint_zh="大特写微距镜头，极致展现眼眸、嘴唇等局部特异细节",
        ai_risk="caution",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_medium",
        name_en="Medium",
        name_zh="中景",
        prompt_hint_zh="标准中景，展现半身身姿与手势互动",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_medium_close_up",
        name_en="Medium Close-Up",
        name_zh="中近景",
        prompt_hint_zh="中近景胸部以上，突出人物对话与神态反应",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_wide",
        name_en="Wide",
        name_zh="全景",
        prompt_hint_zh="全景镜头，清晰展现人物全身与周围环境的空间关系",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_extreme_wide",
        name_en="Extreme Wide",
        name_zh="大远景",
        prompt_hint_zh="大远景开阔视野，强调恢弘环境与人在场景中的空间格局",
        ai_risk="caution",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_full",
        name_en="Full",
        name_zh="全身景",
        prompt_hint_zh="全身镜头，完整容纳人物从头到脚的动作与站位",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_cowboy",
        name_en="Cowboy",
        name_zh="牛仔景",
        prompt_hint_zh="牛仔七分身景别，人物膝盖以上，突出腰部道具与身体姿态",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_two_shot",
        name_en="Two-Shot",
        name_zh="双人镜头",
        prompt_hint_zh="双人同框镜头，清晰展现两人在同一画面的相对位置与对视",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_over_the_shoulder",
        name_en="Over-the-Shoulder",
        name_zh="过肩镜头",
        prompt_hint_zh="过肩镜头，从前景人物肩部背后拍摄对方正面表情",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_pov",
        name_en="POV",
        name_zh="主观视角",
        prompt_hint_zh="第一人称主观视角镜头，模拟角色视线所见场景",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_dutch_angle",
        name_en="Dutch Angle",
        name_zh="荷兰角",
        prompt_hint_zh="倾斜地平线荷兰角构图，营造失衡与心理紧张感",
        ai_risk="caution",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_birds_eye",
        name_en="Bird's Eye",
        name_zh="鸟瞰镜头",
        prompt_hint_zh="垂直向下鸟瞰视角，俯瞰全局平面几何布局与人员调度",
        ai_risk="caution",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_worms_eye",
        name_en="Worm's Eye",
        name_zh="虫视镜头",
        prompt_hint_zh="贴地极低仰视虫视镜头，营造压迫感与主体崇高感",
        ai_risk="caution",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_establishing",
        name_en="Establishing",
        name_zh="定场镜头",
        prompt_hint_zh="定场交代镜头，交代地理环境与故事时空基准",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_insert",
        name_en="Insert",
        name_zh="插入镜头",
        prompt_hint_zh="特写插入镜头，清晰交代关键道具或手中细微动作",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_cutaway",
        name_en="Cutaway",
        name_zh="切出镜头",
        prompt_hint_zh="切出观察镜头，拍摄场景旁观者或次要环境细节",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_reaction",
        name_en="Reaction",
        name_zh="反应镜头",
        prompt_hint_zh="反应镜头，捕捉倾听者在关键对话时的面部心理反馈",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_master",
        name_en="Master",
        name_zh="主镜头",
        prompt_hint_zh="主镜头全景覆盖，完整记录本场全部角色与空间调度事实",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_tracking_shot_framing",
        name_en="Tracking Shot Framing",
        name_zh="跟拍取景",
        prompt_hint_zh="行进跟拍取景构图，在平稳运动中保持主体在画面的相对位置",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_profile",
        name_en="Profile",
        name_zh="正侧面镜头",
        prompt_hint_zh="正侧面90度构图，聚焦角色侧面五官剪影与视线走向",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_three_quarter",
        name_en="Three-Quarter",
        name_zh="四分之三侧面镜头",
        prompt_hint_zh="四分之三侧脸黄金视角，呈现自然面部纵深与立体感",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_clean_single",
        name_en="Clean Single",
        name_zh="干净单人镜头",
        prompt_hint_zh="干净单人构图，主体独占画面无任何前景人物遮挡",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_dirty_single",
        name_en="Dirty Single",
        name_zh="带前景单人镜头",
        prompt_hint_zh="带前景微虚遮挡的单人镜头，增强空间纵深与现场对话真实感",
        ai_risk="stable",
        category="shot_type",
    ),
    VocabItem(
        id="shot_type_split_screen",
        name_en="Split-Screen",
        name_zh="分屏镜头",
        prompt_hint_zh="左右或多格分屏对比画面(后期合成)",
        ai_risk="post_only",
        category="shot_type",
    ),
    # ── Camera Movements (20 项) ─────────────────────────────────────────────
    VocabItem(
        id="cam_dolly",
        name_en="Dolly",
        name_zh="推拉移动",
        prompt_hint_zh="轨道移动车平稳直线推进或拉出",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_dolly_zoom",
        name_en="Dolly Zoom",
        name_zh="滑动变焦",
        prompt_hint_zh="反向滑动变焦眩晕效果(后期合成)",
        ai_risk="post_only",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_pan",
        name_en="Pan",
        name_zh="水平摇镜",
        prompt_hint_zh="机位固定水平平滑扫视",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_tilt",
        name_en="Tilt",
        name_zh="垂直俯仰摇镜",
        prompt_hint_zh="机位固定垂直方向缓慢俯仰摇移",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_tracking",
        name_en="Tracking",
        name_zh="跟拍移动",
        prompt_hint_zh="摄影机伴随主体行进方向同速平移跟拍",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_crane",
        name_en="Crane",
        name_zh="摇臂升降",
        prompt_hint_zh="大摇臂高空大范围平稳起伏升降运镜",
        ai_risk="caution",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_steadicam",
        name_en="Steadicam",
        name_zh="斯坦尼康跟随",
        prompt_hint_zh="斯坦尼康稳定器跟随，行云流水般平稳穿梭",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_handheld",
        name_en="Handheld",
        name_zh="手持微晃",
        prompt_hint_zh="纪实手持自然微弱呼吸感轻度晃动，临场感强烈",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_zoom",
        name_en="Zoom",
        name_zh="光学变焦",
        prompt_hint_zh="机位固定光学变焦轻柔拉近焦点",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_push_in",
        name_en="Push In",
        name_zh="缓推镜头",
        prompt_hint_zh="镜头匀速缓缓向前推入，焦点凝聚于主体内心状态",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_pull_out",
        name_en="Pull Out",
        name_zh="缓拉镜头",
        prompt_hint_zh="镜头匀速缓缓向后拉开，逐步揭示周围环境信息",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_arc",
        name_en="Arc",
        name_zh="圆弧环绕",
        prompt_hint_zh="摄影机绕主体做圆弧小角度环绕平移运镜",
        ai_risk="caution",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_whip_pan",
        name_en="Whip Pan",
        name_zh="甩镜",
        prompt_hint_zh="高速模糊甩镜头转场(后期剪辑处理)",
        ai_risk="post_only",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_roll",
        name_en="Roll",
        name_zh="滚转镜头",
        prompt_hint_zh="镜头沿光轴轴向旋转滚转(后期特效处理)",
        ai_risk="post_only",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_boom",
        name_en="Boom",
        name_zh="吊杆升降",
        prompt_hint_zh="吊杆垂直平稳升降，垂直高度线性平移改变",
        ai_risk="caution",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_cable_cam",
        name_en="Cable Cam",
        name_zh="索道飞猫",
        prompt_hint_zh="空中索道长距离平稳滑行运镜",
        ai_risk="caution",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_drone",
        name_en="Drone",
        name_zh="无人机航拍",
        prompt_hint_zh="低空无人机平稳穿越航拍运镜",
        ai_risk="caution",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_slider",
        name_en="Slider",
        name_zh="滑轨轻移",
        prompt_hint_zh="滑轨微小距离平滑慢移，展现前景背景微弱视差",
        ai_risk="stable",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_jib",
        name_en="Jib",
        name_zh="小摇臂",
        prompt_hint_zh="轻便小摇臂轻柔微升微降，保持视平微动",
        ai_risk="caution",
        category="camera_movement",
    ),
    VocabItem(
        id="cam_follow",
        name_en="Follow",
        name_zh="紧随跟随",
        prompt_hint_zh="紧随主体步伐在身后或侧后方同速跟随",
        ai_risk="stable",
        category="camera_movement",
    ),
    # ── Lighting (15 项) ────────────────────────────────────────────────────
    VocabItem(
        id="light_three_point",
        name_en="Three-Point",
        name_zh="三点布光",
        prompt_hint_zh="经典三点布光，主光/辅光/轮廓光清晰平衡，层次立体",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_high_key",
        name_en="High-Key",
        name_zh="高调光",
        prompt_hint_zh="通透高调光照，低光比低阴影反差，明朗轻快",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_low_key",
        name_en="Low-Key",
        name_zh="低调光",
        prompt_hint_zh="低调幽暗布光，高光比深邃大面积阴影，氛围浓郁",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_rembrandt",
        name_en="Rembrandt",
        name_zh="伦勃朗光",
        prompt_hint_zh="伦勃朗布光，人物暗侧脸颊形成明确三角形受光区",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_silhouette",
        name_en="Silhouette",
        name_zh="剪影逆光",
        prompt_hint_zh="强逆光剪影效果，背景高亮人物身姿呈清晰黑色剪影",
        ai_risk="caution",
        category="lighting",
    ),
    VocabItem(
        id="light_chiaroscuro",
        name_en="Chiaroscuro",
        name_zh="明暗对照光",
        prompt_hint_zh="戏剧性卡拉瓦乔式明暗强烈对照，明亮与幽暗剧烈交锋",
        ai_risk="caution",
        category="lighting",
    ),
    VocabItem(
        id="light_practical",
        name_en="Practical",
        name_zh="实物现场光",
        prompt_hint_zh="画面内台灯、烛光等实体光源发光，真实可信",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_motivated",
        name_en="Motivated",
        name_zh="动机光源",
        prompt_hint_zh="符合场景物理逻辑的动机光源(如窗外天光、门缝光)",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_natural",
        name_en="Natural",
        name_zh="自然日光",
        prompt_hint_zh="纯自然日光漫射照明，写实质朴真实光影质感",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_backlight",
        name_en="Backlight",
        name_zh="逆光背光",
        prompt_hint_zh="主体背部逆光照射，发丝与肩膀勾勒出金色光晕边缘",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_rim",
        name_en="Rim",
        name_zh="轮廓光",
        prompt_hint_zh="清晰轮廓边缘光，将深色人物从暗背景中清晰剥离",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_fill",
        name_en="Fill",
        name_zh="辅助辅光",
        prompt_hint_zh="柔润辅助辅光轻度补亮暗部阴影，保留阴影细节",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_hard",
        name_en="Hard",
        name_zh="直射硬光",
        prompt_hint_zh="未漫射直射硬光，边缘锐利投下清晰生硬阴影",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_soft",
        name_en="Soft",
        name_zh="柔光漫射",
        prompt_hint_zh="大面积柔光漫射，过渡极其平缓温和无硬边阴影",
        ai_risk="stable",
        category="lighting",
    ),
    VocabItem(
        id="light_bounce",
        name_en="Bounce",
        name_zh="反射跳光",
        prompt_hint_zh="反射漫射光，墙面反光板反射而来的极柔和柔光",
        ai_risk="stable",
        category="lighting",
    ),
    # ── Editing (20 项，全部为剪辑阶段 post_only) ───────────────────────────
    VocabItem(
        id="edit_jump_cut",
        name_en="Jump Cut",
        name_zh="跳切",
        prompt_hint_zh="同一机位省略连续动作的突变跳切(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_match_cut",
        name_en="Match Cut",
        name_zh="匹配剪辑",
        prompt_hint_zh="两镜头之间形状或动作相似的图形匹配剪接(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_j_cut",
        name_en="J-Cut",
        name_zh="J型剪辑",
        prompt_hint_zh="下一镜声音先于画面切入的J型剪接(音频剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_l_cut",
        name_en="L-Cut",
        name_zh="L型剪辑",
        prompt_hint_zh="上一镜声音延续至下一镜画面的L型剪接(音频剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_cross_dissolve",
        name_en="Cross Dissolve",
        name_zh="叠化",
        prompt_hint_zh="前后两镜头渐隐渐显平滑重叠交叉溶解转场(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_smash_cut",
        name_en="Smash Cut",
        name_zh="突切",
        prompt_hint_zh="极静突然切至极闹的剧烈突切剪接(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_montage",
        name_en="Montage",
        name_zh="蒙太奇",
        prompt_hint_zh="压缩时间与叙事的快速片段组合蒙太奇(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_parallel_editing",
        name_en="Parallel Editing",
        name_zh="平行剪辑",
        prompt_hint_zh="两条叙事线在不同空间交替剪辑呈现(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_cross_cutting",
        name_en="Cross-Cutting",
        name_zh="交叉剪辑",
        prompt_hint_zh="多线紧张同时发生的高频交叉剪辑(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_flash_cut",
        name_en="Flash Cut",
        name_zh="闪切",
        prompt_hint_zh="仅持续几帧的瞬时闪白或极短闪切(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_freeze_frame",
        name_en="Freeze Frame",
        name_zh="定格画面",
        prompt_hint_zh="将单帧冻结为静止画面的定格处理(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_slow_motion",
        name_en="Slow Motion",
        name_zh="升格慢动作",
        prompt_hint_zh="高帧率慢动作变速播放处理(剪辑变速)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_time_lapse",
        name_en="Time-Lapse",
        name_zh="延时摄影",
        prompt_hint_zh="降格快速播放流逝的延时摄影处理(剪辑变速)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_split_edit",
        name_en="Split Edit",
        name_zh="拆分剪辑",
        prompt_hint_zh="声画切点时间不一致的拆分剪接(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_invisible_cut",
        name_en="Invisible Cut",
        name_zh="隐形剪辑",
        prompt_hint_zh="利用前景暗部或快速摇镜遮挡缝合的无缝隐形转场(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_match_on_action",
        name_en="Match on Action",
        name_zh="动作连贯剪接",
        prompt_hint_zh="动作在剪辑点两侧精确衔接顺畅剪接(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_eyeline_match",
        name_en="Eyeline Match",
        name_zh="视线连贯剪接",
        prompt_hint_zh="上一镜看某处下一镜精确切出被看对象的视线对齐剪辑(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_cut_on_action",
        name_en="Cut on Action",
        name_zh="动点剪辑",
        prompt_hint_zh="在动作发生的动态峰值点利落切开(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_establishing_cut",
        name_en="Establishing Cut",
        name_zh="定场切入",
        prompt_hint_zh="从大环境全景切入局部主体的建立定场剪接(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    VocabItem(
        id="edit_cutaway_edit",
        name_en="Cutaway",
        name_zh="切出镜头组接",
        prompt_hint_zh="在主对话中切入相关反应或环境物件的剪辑手法(剪辑单)",
        ai_risk="post_only",
        category="editing",
    ),
    # ── Composition (12 项) ─────────────────────────────────────────────────
    VocabItem(
        id="comp_rule_of_thirds",
        name_en="Rule of Thirds",
        name_zh="三分法则",
        prompt_hint_zh="三分法则九宫格黄金分割点构图，视觉舒适自然",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_leading_lines",
        name_en="Leading Lines",
        name_zh="引导线",
        prompt_hint_zh="场景透视线条汇聚导向核心主体，增强画面纵深感",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_symmetry",
        name_en="Symmetry",
        name_zh="对称构图",
        prompt_hint_zh="严格居中轴线对称构图，庄严肃穆且极具仪式感",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_framing_within_frame",
        name_en="Framing Within Frame",
        name_zh="框中框构图",
        prompt_hint_zh="利用门框、窗棂或物体构筑次级框架框住主体",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_depth_of_field",
        name_en="Depth of Field",
        name_zh="浅景深层次",
        prompt_hint_zh="大光圈浅景深，背景虚化剥离，前景中景背景层次清晰",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_negative_space",
        name_en="Negative Space",
        name_zh="留白空间",
        prompt_hint_zh="大面积空旷负空间留白，凸显角色内心的孤独与宁静",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_golden_ratio",
        name_en="Golden Ratio",
        name_zh="黄金比例",
        prompt_hint_zh="黄金螺旋斐波那契构图，动态视觉平衡协调",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_diagonal_lines",
        name_en="Diagonal Lines",
        name_zh="对角线构图",
        prompt_hint_zh="对角线倾斜几何结构，为画面注入动势与不稳定能量",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_foreground_interest",
        name_en="Foreground Interest",
        name_zh="前景趣味",
        prompt_hint_zh="前景放置具有空间质感的虚化物件，建立层次层次纵深",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_balance",
        name_en="Balance",
        name_zh="视觉平衡",
        prompt_hint_zh="画面左右元素质量与体量沉静均衡分布",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_triangular",
        name_en="Triangular",
        name_zh="三角构图",
        prompt_hint_zh="稳固三角形视觉分布，构图端庄坚实稳定",
        ai_risk="stable",
        category="composition",
    ),
    VocabItem(
        id="comp_dynamic_symmetry",
        name_en="Dynamic Symmetry",
        name_zh="动态对称",
        prompt_hint_zh="对角菱形律动对称，在工整中富有动感与节奏",
        ai_risk="stable",
        category="composition",
    ),
    # ── Genres (15 项) ──────────────────────────────────────────────────────
    VocabItem(
        id="genre_horror",
        name_en="Horror",
        name_zh="恐怖",
        prompt_hint_zh="恐怖片风格，暗部压抑沉滞，冷暗阴郁且危机四伏",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_comedy",
        name_en="Comedy",
        name_zh="喜剧",
        prompt_hint_zh="喜剧片风格，色调明朗欢快通透，饱满活泼",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_drama",
        name_en="Drama",
        name_zh="正剧",
        prompt_hint_zh="现实主义院线剧情片沉稳基调，细腻情感与电影级质感",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_thriller",
        name_en="Thriller",
        name_zh="惊悚",
        prompt_hint_zh="冷峻悬疑惊悚基调，高对比度低调光线与紧迫张力",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_sci_fi",
        name_en="Sci-Fi",
        name_zh="科幻",
        prompt_hint_zh="科幻未来感美学，冷青冷灰伴随细微工业质感",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_action",
        name_en="Action",
        name_zh="动作",
        prompt_hint_zh="硬派动作大片风格，高反差凌厉光影与紧凑动态",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_romance",
        name_en="Romance",
        name_zh="爱情",
        prompt_hint_zh="浪漫温情色调，暖金柔光漫射与柔滑细腻肤质",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_documentary",
        name_en="Documentary",
        name_zh="纪录片",
        prompt_hint_zh="现实纪实风格，自然光线与无修饰写实质地",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_film_noir",
        name_en="Film Noir",
        name_zh="黑色电影",
        prompt_hint_zh="经典黑色电影风格，极高反差剪影百叶窗阴影，冷酷宿命感",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_western",
        name_en="Western",
        name_zh="西部",
        prompt_hint_zh="西部片粗粝粗野风貌，烈日大地焦黄风沙尘土与强逆光",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_musical",
        name_en="Musical",
        name_zh="歌舞",
        prompt_hint_zh="华丽舞台歌舞片影调，梦幻饱和光泽与高雅戏剧灯效",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_mystery",
        name_en="Mystery",
        name_zh="悬疑",
        prompt_hint_zh="深沉悬疑推理氛围，幽微暗角与朦胧烟雾环境",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_war",
        name_en="War",
        name_zh="战争",
        prompt_hint_zh="冷峻战争史诗影调，低饱和泥泞硝烟颗粒感与沉重压抑",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_animation",
        name_en="Animation",
        name_zh="动画",
        prompt_hint_zh="精致动画艺术质感，饱满明晰色彩层次与细腻轮廓",
        ai_risk="stable",
        category="genre",
    ),
    VocabItem(
        id="genre_independent",
        name_en="Independent",
        name_zh="独立电影",
        prompt_hint_zh="欧洲独立艺术片电影胶片质感，内敛沉郁反差与写实冷色",
        ai_risk="stable",
        category="genre",
    ),
]

# 校验词表项总数必须严格等于 107
assert len(_VOCAB_LIST) == 107, f"Expected 107 items, got {len(_VOCAB_LIST)}"

VOCAB_MAP: dict[str, VocabItem] = {item.id: item for item in _VOCAB_LIST}

# 快捷英文/中文索引表(全小写归一)
_LOOKUP: dict[str, VocabItem] = {}
for _item in _VOCAB_LIST:
    _LOOKUP[_item.id.lower()] = _item
    _LOOKUP[_item.name_en.lower()] = _item
    _LOOKUP[_item.name_zh] = _item
    _LOOKUP[_item.name_en.lower().replace("-", " ").replace("'", "")] = _item

# post_only 技法集合(不可进文本生成提示词)
POST_ONLY_IDS: set[str] = {item.id for item in _VOCAB_LIST if item.ai_risk == "post_only"}
POST_ONLY_NAMES_EN: set[str] = {
    item.name_en.lower() for item in _VOCAB_LIST if item.ai_risk == "post_only"
}
POST_ONLY_NAMES_ZH: set[str] = {
    item.name_zh for item in _VOCAB_LIST if item.ai_risk == "post_only"
}


def get_vocab_item(key: str) -> VocabItem | None:
    """根据 id、英文名或中文名检索词表条目。"""
    if not key:
        return None
    k = key.strip()
    return _LOOKUP.get(k) or _LOOKUP.get(k.lower()) or _LOOKUP.get(k.lower().replace("-", " "))


def list_vocab_by_category(cat: Category) -> list[VocabItem]:
    """按分类列出词表项。"""
    return [it for it in _VOCAB_LIST if it.category == cat]


def is_post_only(key: str) -> bool:
    """判断是否为 post_only 技法(禁止进提示词)。"""
    item = get_vocab_item(key)
    if item:
        return item.ai_risk == "post_only"
    k_lower = key.strip().lower()
    return (
        k_lower in POST_ONLY_NAMES_EN
        or key.strip() in POST_ONLY_NAMES_ZH
        or any(po in k_lower for po in ["dolly zoom", "whip pan", "split screen", "jump cut"])
    )


def find_post_only_violations(text_or_names: str | list[str]) -> list[str]:
    """检查文本或字段名中是否包含 post_only 词汇，返回命中的禁词列表。"""
    violations: list[str] = []
    if isinstance(text_or_names, str):
        candidates = [text_or_names]
    else:
        candidates = list(text_or_names)

    for item in _VOCAB_LIST:
        if item.ai_risk != "post_only":
            continue
        en = item.name_en.lower()
        zh = item.name_zh
        for cand in candidates:
            c_lower = cand.lower()
            if en in c_lower or zh in cand:
                violations.append(f"{item.name_en}({item.name_zh})")
                break
    return sorted(list(set(violations)))
