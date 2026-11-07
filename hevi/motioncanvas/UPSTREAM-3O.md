# motioncanvas → canonical 3O 回流记录（2026-10-22）
Motion Canvas 3.17（MIT）仅作为 npm 依赖使用，未拷贝其源码。
- obase/mc_render.py：job 工程脚手架（node_modules 软链复用）、`render_job` 调 hevi-motioncanvas/tools/render.mjs（vite + 全量 Chromium 点 Render + ffmpeg 插件），env HEVI_MC_HOME/HEVI_NODE/MC_CHROMIUM。
- oskill/script.py：schema `hevi.motioncanvas.script/v1`，`validate`/`total_duration`/`to_scene_tsx`/`project_meta`；对象 text/code/rect/circle，op show/hide/text/code/highlight/move/wait/parallel。
- omodul/render_script.py：`render_script(script, out_mp4)`，CLI `python -m hevi.motioncanvas.omodul.render_script`。
- 测试 tests/test_motioncanvas_3o.py（E2E 需 HEVI_MC_E2E=1）。
