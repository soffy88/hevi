# PixStag 外接渲染:真人故事片的分工与镜头包交接契约

日期:2026-10-20 · 定调人:Soffy · 能力:`video.pixstag_generate`
客户端:`hevi/video/pixstag_client.py` · 注册:`hevi/capabilities/pixstag.py`

## 分工

- **hevi 出整个流程**:一句话故事 → 故事/分镜 → 角色定妆图(GPT-Image)→ 每镜镜头包。
- **PixStag 出最终成片**:真人故事片的每镜视频由 `video.pixstag_generate` 外接渲染
  (pixstag.com,MiniMax-H3 / doubao-seedance),hevi 收到每镜 mp4 后用
  HyperFrames 拼成母带 + 字幕/配音合成出片。

## 镜头包(shot package)格式

story-to-film / livefilm 线在调用前为每镜落一个镜头包目录,内含:

| 文件 | 内容 |
|---|---|
| `first_frame.png/jpg` | 该镜关键帧/定妆合成图(≤3MB,jpg/png) |
| `motion_prompt.txt` | 运动提示词(中文):镜头运动 + 人物表演 + 情绪 |
| `shot.json` | `{duration: 4..30, ratio: "9:16", resolution: "720P", model: "MiniMax-H3", use_duration_s, handle_head_s, handle_tail_s, source_in_s, handles_clipped}` |

## 生成时长 ≠ 采用时长(handles 约定)

PixStag 按请求的整数秒精确计费、精确生成,所以镜头包把两个时长分开:

- `use_duration_s`:本镜在成片里**采用**的时长(= 原 `duration_s`,向后兼容保留)。
- `handle_head_s` / `handle_tail_s`:首/尾**余量**,默认各 0.5 s;shot 自带
  `handle_head_s`/`handle_tail_s` 时以 shot 的为准(见 `ShotSpec.handle_*_s`)。
- `duration`:**请求 PixStag 生成的时长**(整数秒)=
  `ceil(use_duration_s + handle_head_s + handle_tail_s)`,clamp 到 4..30。
  超过 30 s 时优先保 `use_duration_s`、压缩 handles,并置
  `handles_clipped: true`(此时 `handle_*_s`/`source_in_s` 是压缩后的有效值)。
- `source_in_s`:**回片裁切 in 点** = 有效 `handle_head_s`。装配时从回片的
  `source_in_s` 处起、裁 `use_duration_s` 长的一段入片(例:
  `ffmpeg -ss <source_in_s> -i clip.mp4 -t <use_duration_s> ...`),
  首尾余量一律不进入成片。

调用示例(通过能力契约,任何产品线按名字取):

```python
from hevi.capabilities import get

cap = get("video.pixstag_generate")
result = cap.render_safe(
    {
        "prompt": motion_prompt,            # motion_prompt.txt 内容
        "duration": shot["duration"],       # 生成时长(含 handles,整数秒)
        # 回片装配:按 shot["source_in_s"] 裁 in 点、取 shot["use_duration_s"] 长
        "ratio": "9:16",
        "resolution": "720P",
        "first_frame_path": str(pkg / "first_frame.png"),
        # 可选:"last_frame_path"、"reference_image_paths"(角色一致性参考图)
        # 可选:"use_context_ir": True(PixStag 的提示词优化,质量更高、更慢)
    },
    out_dir=pkg / "render",
    duration=shot["duration"], aspect="9:16", seed=shot_no,
)
# result.mp4 -> 本镜视频;result.qa["sidecar_json"] -> 任务/用量/余额记录
```

## 计费与余额

- 720P = 1 credit/秒;MiniMax-H3 约 $0.015/秒(数据来自 PixStag 定价页,2026-10-20)。
- 积分约 31 天过期:渲染前先 `pixstag_client.me()` 查 `credit` 与
  `credit_valid_time`,余额不足以覆盖整片镜头数时先停下报告,不要逐镜硬跑。
- 每次 render 的 sidecar(pixstag_sidecar.json)记录 task_id、usage、预估积分与渲染后余额。

## 凭据

- `PIXSTAG_API_KEY` env(账号页生成,`Authorization: Bearer`)。未配置时能力
  raise CapabilityError 明示,不会假成功。
