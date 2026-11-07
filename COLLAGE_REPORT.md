# COLLAGE_REPORT.md

## 实现
- 新增 `hevi/collage_broll` 包：隐喻卡、visual-spec、procedural 渲染、QA、CLI、capabilities。
- 新增 `hevi/studio/lines/collage_broll.yaml`（line_id=collage_broll）。
- 新增 `hevi/collage_broll/LICENSE_gbro`（gbro 原 LICENSE 全文），更新 `THIRD_PARTY_NOTICES.md`。

## 文件
- `hevi/collage_broll/__init__.py`, `metaphor.py`, `spec.py`, `render.py`, `qa.py`, `capabilities.py`, `__main__.py`
- `hevi/studio/lines/collage_broll.yaml`
- `samples/`（procedural + codex）

## Commit
- 本地 commit 待创建（仅 worktree）。

## 两种模式结果
- procedural：3 句全部出片，QA 通过；GIF+MP4 路径见 samples/01..03。
- codex：3 句全部出片，QA 通过；GIF+MP4 路径见 samples/codex/01..03。

## Codex 调用次数与耗时
- 调用 3 次（每句一次），每次 ~24s 渲染 + ~34-37s 总耗时（含 codex 启动）。
- 说明：本环境 Codex 无 image_gen 工具，Codex 模式使用 procedural PIL 回退，零成本。

## QA 结果
- 全部 mp4 720x1280，H.264，yuv420p，-an；GIF 20fps；contact sheet 已生成。

## 许可署名
- gbro-collage-broll (MIT) 已在 THIRD_PARTY_NOTICES.md 与 LICENSE_gbro 注明。

## 仍存问题
- Codex 真实图像生成不可用，Codex 模式为 procedural 回退。
- 未接入 talking_head/explainer B-roll 插入接口（仅提供 CLI/能力）。
- 未进行多句 TTS 拼接成片。

DONE
