"""C4 电影分镜 —— 场景(Scene) → 镜头组(CineShotList)。见 HEVI-SPEC-02 §4.2-4.3,
HEVI-EXEC-01 M3。

硬规则(确定性代码,不是 LLM 自由发挥,来自实证 #4):
- 同框人数 >=2 且景别不是 wide/full → 自动拆成各自单独的镜头(shot/reverse-shot;
  这同时就是 one clean face rule 的代码实现——拆开以后每个镜头天然只有一张清晰主脸)。
- 时长默认 <=6s,高动态镜头 <=4s。
- 每个镜头对白 <=2 短句,beat 里的台词超过这个数就二次拆分成多个镜头。
- 每个镜头 prompt 过 hevi.vault.identity_pack.lint_shot_prompt,身份词泄露进
  prompt 直接报错(fail fast,不是警告——身份完全由参考资产承载,同 SPEC-02 §11.1)。
"""

from __future__ import annotations

import re

from hevi.cinematic.schemas import CineShot, CineShotCamera, CineShotList, Scene
from hevi.tongjian.schemas import GateResult
from hevi.vault.identity_pack import lint_shot_prompt

_MAX_DURATION_S = 6.0
_MAX_DURATION_HIGH_MOTION_S = 4.0
_MAX_SENTENCES_PER_SHOT = 2
_WIDE_SHOT_SIZES = {"wide", "full"}

_SENTENCE_SPLIT_RE = re.compile("(?<=[。！？.!?])")  # 。！？ 全角 + .!? 半角


def _split_sentences(text: str) -> list[str]:
    return [p for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]


def _build_shot_prompt(art_direction: str, action: str, on_screen: list[str]) -> str:
    who = "、".join(on_screen)
    return f"{art_direction}, {action}" if not who else f"{art_direction}, {action}({who})"


async def plan_shots(
    scene: Scene,
    *,
    art_direction: str = "",
    immutable_traits_by_character: dict[str, str] | None = None,
    high_motion_beat_ids: set[str] | None = None,
    beat_ids: list[str] | None = None,
) -> CineShotList:
    """scene.beats 逐个转成 shot。默认推断:没有 dialogue 的 beat 视为建立/氛围
    镜头(wide,scene 里全部角色都可能入镜);有 dialogue 的 beat 视为该角色的中近景
    独白镜头(single on_screen)。beat 可以用 on_screen_hint/shot_size_hint 覆盖这
    个默认推断(比如一句没台词的反应镜头,不该被当成"全场入镜的建立镜头")。这个
    映射本身已经保证了"对手戏默认各自成镜"而不需要额外再判断,一旦某个 beat 硬要
    塞 >=2 人到 close/medium_close,下面的自动拆分规则会介入纠正。

    beat_ids:只把这些 beat_id 转成镜头(保持 scene.beats 原有顺序),不给就是全部
    beats 都转——单场景 P0 往往只需要 scene 里的一部分 beat 真正出镜(比如纯叙事
    桥接的 beat 交给旁白覆盖画面,不需要独立建镜),用这个参数选,而不是让 scene
    本身只保留"要出镜的"那几条,破坏 scene 作为完整叙事记录的完整性。

    immutable_traits_by_character:character_id -> 该角色 identity pack 的
    immutable_traits(vault manifest 里存的英文/中文外形锁定描述),用于 lint 检查——
    调用方(runner)从 vault 读出来传进来,这个函数本身不碰数据库(保持纯函数、
    好测试)。
    """
    immutable_traits_by_character = immutable_traits_by_character or {}
    high_motion_beat_ids = high_motion_beat_ids or set()
    beat_id_filter = set(beat_ids) if beat_ids is not None else None
    shots: list[CineShot] = []
    counter = 0

    def _next_id() -> str:
        nonlocal counter
        counter += 1
        return f"SH{counter:02d}"

    for beat in scene.beats:
        if beat_id_filter is not None and beat.beat_id not in beat_id_filter:
            continue

        if beat.on_screen_hint is not None:
            on_screen = list(beat.on_screen_hint)
            shot_size = beat.shot_size_hint or ("medium_close" if beat.dialogue else "wide")
        elif beat.dialogue is not None:
            on_screen = [beat.dialogue.speaker]
            shot_size = beat.shot_size_hint or "medium_close"
        else:
            on_screen = list(scene.characters)
            shot_size = beat.shot_size_hint or "wide"

        max_duration = (
            _MAX_DURATION_HIGH_MOTION_S if beat.beat_id in high_motion_beat_ids else _MAX_DURATION_S
        )

        # one clean face / 正反打拆分:>=2 人且不是 wide/full -> 拆成各自单独的镜头。
        if len(on_screen) >= 2 and shot_size not in _WIDE_SHOT_SIZES:
            groups: list[tuple[list[str], object]] = [
                ([c], beat.dialogue if beat.dialogue and beat.dialogue.speaker == c else None)
                for c in on_screen
            ]
        else:
            groups = [(on_screen, beat.dialogue)]

        for shot_on_screen, dialogue in groups:
            sentence_chunks: list[list[str]]
            if dialogue is not None:
                sentences = _split_sentences(dialogue.text)
                sentence_chunks = [
                    sentences[i : i + _MAX_SENTENCES_PER_SHOT]
                    for i in range(0, len(sentences), _MAX_SENTENCES_PER_SHOT)
                ] or [[]]
            else:
                sentence_chunks = [[]]

            for chunk in sentence_chunks:
                shot_dialogue = None
                if dialogue is not None and chunk:
                    shot_dialogue = dialogue.model_copy(update={"text": "".join(chunk)})

                prompt = _build_shot_prompt(art_direction, beat.action, shot_on_screen)
                for cid in shot_on_screen:
                    traits = immutable_traits_by_character.get(cid, "")
                    if traits:
                        violations = lint_shot_prompt(prompt, traits)
                        if violations:
                            raise ValueError(
                                f"shot prompt 命中身份词泄露: {violations}"
                                f"(character={cid}, beat={beat.beat_id})"
                            )

                shots.append(
                    CineShot(
                        shot_id=_next_id(),
                        scene_id=scene.scene_id,
                        beat_ids=[beat.beat_id],
                        pack_ids=list(shot_on_screen),
                        shot_size=shot_size,
                        camera=CineShotCamera(shot_size=shot_size, movement="static"),
                        on_screen=shot_on_screen,
                        dialogue_inline=shot_dialogue,
                        est_duration_s=max_duration,
                        prompt=prompt,
                    )
                )

    return CineShotList(shots=shots)


def gate_shotlist(shotlist: CineShotList, scene: Scene) -> GateResult:
    """G4 校验门(纯代码,无 LLM)——双重保险:即便 plan_shots 本身的逻辑有 bug,
    产出的 shotlist 也要能在这里被独立复核出硬规则违规。"""
    known_characters = set(scene.characters)
    errors: list[str] = []
    for shot in shotlist.shots:
        if not set(shot.on_screen) <= known_characters:
            errors.append(f"{shot.shot_id} 的 on_screen {shot.on_screen} 不在 scene.characters 里")
        if len(shot.on_screen) >= 2 and shot.shot_size not in _WIDE_SHOT_SIZES:
            errors.append(
                f"{shot.shot_id} 同框 {len(shot.on_screen)} 人但景别是 {shot.shot_size!r}"
                "(one clean face rule:非 wide/full 只能单人入镜)"
            )
        if shot.est_duration_s > _MAX_DURATION_S:
            errors.append(
                f"{shot.shot_id} 时长 {shot.est_duration_s}s 超过 {_MAX_DURATION_S}s 上限"
            )
        if shot.dialogue_inline is not None:
            n = len(_split_sentences(shot.dialogue_inline.text))
            if n > _MAX_SENTENCES_PER_SHOT:
                errors.append(
                    f"{shot.shot_id} 台词 {n} 句,超过每镜头 {_MAX_SENTENCES_PER_SHOT} 句上限"
                )

    return GateResult(passed=not errors, coverage=1.0 if not errors else 0.0, errors=errors)
