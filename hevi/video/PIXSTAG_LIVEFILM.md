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
| `shot.json` | `{duration: 4..30, ratio: "9:16", resolution: "720P", model: "MiniMax-H3"}` |

调用示例(通过能力契约,任何产品线按名字取):

```python
from hevi.capabilities import get

cap = get("video.pixstag_generate")
result = cap.render_safe(
    {
        "prompt": motion_prompt,            # motion_prompt.txt 内容
        "duration": shot["duration"],
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
