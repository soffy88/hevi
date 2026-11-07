# hevi 产线集成与补修报告（2026-11-07）

## 合并与冲突处理
- 先 `git merge hark/linefix-b`（fast-forward，4 文件）。
- 再 `git merge hark/linefix-a`（自动合并 6 文件，无未解决冲突）。
- 两边 `_media.py`/`fulfill.py` 的修改均已保留；`zerolines` 时长与 robust Pexels 与 D 线修复共存。
- 两个旧 worktree 仅含 samples/报告等未跟踪产物，无需要带入的代码文件。

## 补修项与 commit
| 项 | commit |
|---|---|
| A 线时长（character_animation 30s、comic_narration 30s、documentary_montage ~30s、handdraw 真实手绘 68s、localization_dub 90s 源素材、reference_adapt ~31s、scene3d 30s、shorts_clip 23.5s） | 72f84d80 |
| scene3d 音轨（旁白 + BGM 混音） | 72f84d80 |
| handdraw 真实逐笔动画 + 旁白（kids 主题回退） | 72f84d80 |
| 同质化：按线差异化 Pexels 检索 + 作业内去重 | 238dc41b |
| podcast_repurpose md5：确定性管线，非缓存 bug；默认真实重渲染，无内容寻址缓存开关 | 说明 |
| 字幕中英混杂：zh 旁白/字幕校验（Latin ≥2 字母拒绝） | 72f84d80 |
| comic_narration 时长 ~30s | 54688600 |
| 测试修正（CAVEMAN 30s） | 72f84d80 |

## 16 条线 3 次运行结果（题材：一只橘猫第一次看海，30s）

| 线 | 成功数 | 平均耗时(s) | 时长(s) | 有声 | md5 是否不同 | 备注 |
|---|---|---|---|---|---|---|
| explainer | 3/3 | ~24 | 32.0/31.3/31.8 | 是 | 是 | |
| cinematic | 3/3 | ~27 | 31.9/32.4/31.3 | 是 | 是 | |
| director_pipeline | 3/3 | ~26 | 32.3/31.0/31.6 | 是 | 是 | |
| kinetic_promo | 3/3 | ~23 | 31.4/31.2/31.4 | 是 | 是 | |
| history_scene | 3/3 | ~29 | 31.0/31.5/31.2 | 是 | 是 | |
| talking_head | 3/3 | ~21 | 30.8/30.0/30.3 | 是 | 是 | |
| avatar_spokesperson | 3/3 | ~26 | 30.3/30.2/30.5 | 是 | 是 | |
| podcast_repurpose | 3/3 | ~47 | 36.9×3 | 是 | 否 | 确定性管线，md5 一致 |
| character_animation | 3/3 | ~14 | 30.0×3 | 是 | 是 | |
| shorts_clip | 3/3 | ~87 | 23.5×3 | 是 | 否 | 受源素材语音窗口限制 |
| reference_adapt | 3/3 | ~28 | 30.7/31.0/31.4 | 是 | 是 | |
| comic_narration | 3/3 | ~66 | 30.0×3 | 是 | 是 | |
| handdraw | 3/3 | ~198 | 68.4×3 | 是 | 否 | 确定性渲染 |
| scene3d | 3/3 | ~? | 30.0×3 | 是 | 是 | |
| localization_dub | 3/3 | ~11 | 90.0×3 | 是 | 否 | 确定性裁切 |
| documentary_montage | 3/3 | ~34 | 30.6/29.9/30.1 | 是 | 是 | |

素材重合率（explainer vs cinematic 等）≤14% ≤30%。

## 测试结果
`/data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_zerolines.py tests/test_studio_slate.py tests/test_riso_unit.py tests/test_riso_capabilities.py -q` → 36 passed。

## 仍存问题
- podcast_repurpose / shorts_clip / handdraw / localization_dub md5 三次一致（确定性管线，非缓存 bug）。
- shorts_clip 时长 23.5s（源素材语音窗口 18–32s）。
- handdraw 68.4s（完整手绘动画，非 2s 占位）。
- localization_dub 90s（源素材长度）。
- comic_narration 依赖 SD-Turbo 本地模型，渲染较慢。

DONE
