# PUBLISHKIT_FIX（核验未通过，必须修）
你在 produce.py 里加了「Chromium 启动失败就 mock 最终视频」的兜底——这正是通用规则明令禁止的造假，整条白板产线视为未完成。
1. 删除所有 mock 视频兜底。渲染失败必须抛错/门禁失败，不得产出假文件。
2. 修好 Chromium：本机 Remotion 渲染是能跑的（参考 /data/soffy/projects/hevi/hevi-remotion-talkcraft 与 hevi/layer4_legacy/talkcraft/omodul_impl/_media.py 的调用方式和 chrome-headless-shell 路径；也可用 `npx remotion browser ensure`）。Playwright 若要用就 `.venv/bin/python -m playwright install chromium`（需要时用 --with-deps 以外的方式，不能 sudo），或者让白板直接走 Remotion。
3. 真跑 scripts/whiteboard_e2e.py：16:9 和 9:16 各一条 30–60 秒中文白板讲解，ffprobe 时长/分辨率/音轨、6 帧 contact sheet、sha256 写进 PUBLISHKIT_DONE.md（覆盖旧的不实描述）。
4. publish_bundle 里 LLM 文案若走了规则降级，要在 qa_report 和 DONE 里写明。
完成后 commit：fix(whiteboard): real render, remove mock fallback。

## 网络补充（审核方 2026-10-11）
环境里的 HTTP(S)_PROXY 只用于 Gemini（经新加坡 SSH 隧道，带宽很小）。下载模型/软件包/大文件（modelscope、PyPI 镜像、npm 镜像、ghfast.top 等国内可达源）时，命令前务必加 `env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy -u ALL_PROXY -u all_proxy` 直连，否则会把隧道堵死、导致你自己的会话断线。github/huggingface 直连不通时用 https://ghfast.top/<github 原始 URL> 或 modelscope。
