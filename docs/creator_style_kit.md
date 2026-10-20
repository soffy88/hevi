# creator-style-kit 风格线（HyperFrames）

来源：[threeaus/creator-style-kit](https://github.com/threeaus/creator-style-kit)（MIT）。
18 套 9:16 竖屏视频风格（字体/配色/动效/音效/构图成套），经两个 hevi 能力接入：

| 能力 | 用途 |
|---|---|
| `video.hyperframes_styles` | 列出 18 套风格目录（id、中英文名、best_for、essence、配色、动效语法、hard rules），产物 `styles_catalogue.json`，每次渲染从 kit 检出重新生成并钉住 kit commit |
| `video.hyperframes_styled_render` | `beats.json + style_id` → 确定性 1080×1920 成片 `styled.mp4`（kit 的 scaffold 建工程，Playwright seek 式逐帧渲染） |

## 部署约定

- kit 本体不进 hevi 仓库（字体+SFX 约 180MB），检出在 `~/projects/_refs/creator-style-kit`，
  可用环境变量 `HEVI_CSK_HOME` 覆盖。缺失时两个能力都明确报 `CapabilityError`，不假成功。
- 字体：随仓字体全部 OFL-1.1，build 时按工程文本子集化。
  **MiSans、优设标题黑**免费商用但不可再分发，仓库不带，用 kit 自带脚本拉取并校验 sha256：
  `python3 $HEVI_CSK_HOME/scripts/fetch_fonts.py`（用到的风格：dark-keynote、isometric-stack、poster-kinetic）。
  未拉取前这三套风格渲染会明确报错，其余 15 套不受影响。
- 渲染不用 `hyperframes_service` 的截图路径（它每帧新开浏览器、只推进 100ms 虚拟时间，
  动画会被冻在第一瞬）；seek 渲染实现在 `hevi/video/csk_styled_render.py`，
  ffmpeg 编码参数与 hyperframes_service 保持一致。

## 音效对应关系（不要重复造）

- 每套风格自带 cue kit（Kenney/uisfx，CC0），由 kit 的 build 步骤烘进工程，
  节奏/密度由风格 `sound.rules` 约束；渲染后混音+质检用 kit 的 `sound_pass.py`。
- hevi 的 `audio.sfx_render`（earshot 201 个代码化音效）是另一套资源：一次性音效点用它，
  整套风格的声音语法跟风格走时用本线。两边不要互相替代。
