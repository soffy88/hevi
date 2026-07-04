# SPEC: oprim 新增原语(L2)—— hevi 会话产出,待回迁

- **状态**: Proposed
- **层**: oprim(L2 原语),与 `ltx2_cloud_generate` / `vibevoice_synthesize` / `avatar_generate` 并列
- **目标版本**: oprim vX.Y.0(feat 分支,按 RELEASE_POLICY)
- **背景**: hevi 本会话为落地"能出片/真人写实/角色库/对口型",临时把这些 **L2 原语写进了 hevi**(违背 3O 范式)。本 spec 规整为 oprim 应实现的原语;hevi 落地后仅在 registry `from oprim import ...` wire。
- **接口约定**: kw-only、`output_path: Path`、返回 `Path`(与既有 oprim 媒体原语一致)。

---

## 1. `edge_tts_synthesize` —— 多语言云 TTS(audio)

- **参考实现**: hevi `hevi/audio/edge_tts_service.py`(已上线,单测 `test_edge_tts_voice_selection`)
- **新依赖**: `edge-tts>=7.2`(MIT);运行期需 ffmpeg(obase.ffmpeg 已有)

### 接口
```python
async def edge_tts_synthesize(
    *, script: list[Line], output_path: Path,
    language: str | None = None, config: dict | None = None,
    watermark: bool = False,   # 接口兼容占位;edge-tts 无水印
) -> Path
```

### 行为
1. 逐行 `edge_tts.Communicate(text, voice).save(seg.mp3)`;voice 由 `_voice_for(text, language)` 定。
2. 单行失败仅 warn 跳过;全失败 → `RuntimeError`。
3. ffmpeg 合并 → 统一 **WAV pcm_s16le / 44100 / mono**(装配器期望格式)。

### 契约 / 错误
- `Line` duck-typing:`.text`(必需)、`.speaker_id`(默认 "host"),与 vibevoice 一致(复用 omodul 的 `all_lines`)。
- language 缺省时**按文本 CJK 自动选中/英**(支持混排)。
- 空 script → `ValueError`;全段失败 → `RuntimeError`;网络失败由 edge_tts 抛出,调用方按"配音非必需"降级。

### 音色映射(env 可覆盖 `EDGE_TTS_VOICE_ZH/EN`)
`zh→zh-CN-XiaoxiaoNeural en→en-US-AriaNeural ja→ja-JP-NanamiNeural ko→ko-KR-SunHiNeural es/fr/de…`

### 验收
- 3 行中英混排 → 合法 WAV(时长>0);`_voice_for` 中/英/显式语言判定正确;空/全失败抛对应异常。

---

## 2. `veo3_generate` / `kling_v2_generate` / `hailuo_generate` —— 高写实视频(video)

- **参考实现**: hevi `hevi/video/fal_providers.py`(已上线,单测 `test_fal_providers_build_payloads` / `test_fal_aspect_ratio`)
- **动机**: fal `ltx-video` 基础版写实/解剖弱(手崩、768×512);这三者对标 HeyGen/真人级。均支持 `negative_prompt` + 朝向。

### 接口
```python
async def veo3_generate(*, prompt: str, output_path: Path, aspect_ratio: str = "9:16",
    duration_s: float = 8, negative_prompt: str = "", generate_audio: bool = True,
    resolution: str = "720p") -> Path
async def kling_v2_generate(*, prompt: str, output_path: Path, aspect_ratio: str = "9:16",
    duration_s: float = 5, negative_prompt: str = "", cfg_scale: float = 0.5) -> Path
async def hailuo_generate(*, prompt: str, output_path: Path, duration_s: float = 6,
    resolution: str = "768P") -> Path
```

### fal 端点 & payload
| 原语 | 端点 | payload 关键字段 |
|---|---|---|
| veo3 | `fal-ai/veo3/fast` | prompt, aspect_ratio, duration="8s", generate_audio, resolution, [negative_prompt] |
| kling_v2 | `fal-ai/kling-video/v2/master/text-to-video` | prompt, duration="5", aspect_ratio, cfg_scale, negative_prompt |
| hailuo | `fal-ai/minimax/hailuo-02/standard/text-to-video` | prompt, duration="6", resolution="768P", prompt_optimizer=true |

### 契约 / 错误
- 均为 fal **队列制**:走 `fal_queue_generate`(§3)。
- 朝向:`aspect_ratio ∈ {9:16,16:9,1:1}`;可由 (w,h) 推导(w>h→16:9,w==h→1:1,否则 9:16)。
- 忽略不支持的 kw(mode/reference_image/size 等)——纯 t2v(i2v 变体后续另开)。
- fal 403 "User is locked / Exhausted balance" → 抛 RuntimeError,由 classify_error 归 Unretryable(不重试)。

### 验收
- 各原语命中正确端点;payload 含 negative_prompt(veo3/kling)与正确 aspect_ratio;veo3 `generate_audio=true`。
- 实测(需 fal 余额):veo3 → 720×1280 h264+aac 8s;kling/hailuo → 竖屏可播成片。

---

## 3. `fal_queue_generate` —— fal 队列通用工具(oprim util 或 obase 网络层)

- **参考实现**: hevi `hevi/video/fal_providers.py::_fal_queue_generate`

### 接口
```python
async def fal_queue_generate(*, endpoint: str, payload: dict, output_path: Path,
    timeout_s: float = 600) -> Path
```

### 行为
1. `POST queue.fal.run/{endpoint}`(Header `Authorization: Key $FAL_API_KEY`)。
2. 若返回 `status_url`:轮询至 `COMPLETED`(**带总 deadline `timeout_s`**,治 fal 轮询无限挂);`FAILED/CANCELLED/ERROR` → 抛。
3. 取 `response_url` → 解析 `video.url | video_url | output.video_url` → 下载到 output_path。
4. 产物 `<1024B` 视为失败。

### 契约 / 错误
- `FAL_API_KEY` 缺失 → RuntimeError。
- 所有 fal 队列制模型共用(veo3/kling/hailuo + 后续 lipsync)。放 oprim 内部工具或下沉 obase 网络层。

---

## 4.(计划)`lipsync_generate` —— 对口型(video / audio,本地优先)

- **参考实现**: 无(设计中);现有 `avatar_generate`(Duix,本地)可作首个 provider
- **动机**: 补"头像解说"品类的对口型(HeyGen 核心能力),对标数字人。

### 接口
```python
async def lipsync_generate(*, provider: str, audio_path: Path, output_path: Path,
    portrait_image: Path | None = None,   # 肖像驱动:图 + 音频 → 会说话的头
    source_video: Path | None = None,     # 视频驱动:视频 + 音频 → 重对口型
) -> Path
```

### provider 矩阵
| 模式 | provider | 渠道 | 备注 |
|---|---|---|---|
| 肖像驱动 | `duix`(已接) / `sadtalker` / `hedra` / `sonic` | 本地 / fal | 复用角色库肖像 |
| 视频驱动 | `sync` / `latentsync` / `musetalk` | fal / 本地 | 给生成视频里的人对口型 |

### 落地策略(契合 hevi 本地零成本卖点)
- **本地优先**:SadTalker/Hallo2/MuseTalk/LatentSync 在 RTX3080 **子进程隔离**跑(退出释放显存),经 `obase` GPU 调度与 qwen/wan 串行;fal 版作可选云档。
- 与 `avatar_generate` 并列;fal 版走 `fal_queue_generate`(§3)。

### 验收
- 肖像+音频 → 口型同步的会说话视频;本地 provider 零云成本;fal provider 走队列工具。

---

## 5. 落地(RELEASE_POLICY)
- §1–3 有现成 hevi 实现 + 单测,可**直接搬进 oprim + 补 oprim 测试**;hevi registry 改 `from oprim import ...`,删对应 hevi 文件。
- §4 为设计,先实现本地 SadTalker/Duix,后补 fal 云档。
- 合并序 oprim→oskill→omodul;走 `feat/v{semver}-*` 分支。上游修复项(拆 21 处猴补丁)见 `3O-new-elements-manifest.md` B 组。

*备注*:fal 余额耗尽(403)+ 本机 GPU 挂起——云原语与本地 lipsync 的 e2e 验证需分别在充值/修 GPU 后进行;接口与实现设计不受影响。
