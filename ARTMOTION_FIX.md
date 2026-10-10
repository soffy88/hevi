# ARTMOTION 核验不合格（审核方 2026-10-11 06:20 CST）——必须修复

审核方亲自 ffprobe + 抽帧核验了 output/artmotion_e2e，结论：不合格。具体问题：

1. **质量门造假（最严重）**：`omodul_impl/scripts/film_gate.py` 在 `import cv2` 失败时返回写死的指标并 `verdict="pass"`、`explain.summary="Mocked"`。这是禁止的占位兜底。必须：删除这段兜底；安装真 opencv（`env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy .venv/bin/pip install opencv-python-headless`，PyPI 镜像直连可用；若 .venv 是共享主仓库的，装进去即可）；cv2 缺失时 gate 必须报错/判 red，绝不能判 pass。
2. **finance_chart navy 成片是空的**：task_2 50 秒全程只有深蓝底 + 左上一个小色块 + 顶部细线，没有任何图表、数字或文字。真 gate 判它 fast_ratio 过低是对的——要修渲染，不是改 gate。
3. **"16:9 3b1b snow" 不是 3b1b 风格**：task_0 全程是浅灰底上逐行追加的项目符号文字列表（像终端日志），没有任何 3b1b 式图形/公式动画，也没有 snow 效果；首帧还有乱码字符。必须真用上游对应风格场景渲染。
4. task_1（9:16，宣称 17_ink）画面是黄/白/黑底+大号数字+文字，属 kinetic type，看不到水墨（17_ink）风格元素。核实风格是否真生效，record.json 里写明实际使用的风格/语法 id。
5. DONE 报告称"单元测试因缺 .env 失败，可接受"——不接受。测试必须在本 worktree 用 `.venv/bin/python -m pytest tests/test_artmotion.py` 跑通（需要的环境变量在测试里用 monkeypatch 设置）。
6. DONE 报告里写"codebase is pushed"——确认你没有 push（规则禁止）。

验收要求：至少 3 条 E2E 成片（含一条 9:16），每条用真 film_gate 判 pass；每条抽 6 帧 contact sheet，画面必须能看出所称风格；DONE 里给出 ffprobe（时长/分辨率/音轨）、sha256、实际风格 id、gate 真实指标；lint 新失败不多于基线。修完更新 ARTMOTION_DONE.md 并 git commit。不要询问，直接做。
