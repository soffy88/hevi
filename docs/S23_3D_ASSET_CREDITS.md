# S23 3D 资产许可与 CREDITS

S23 的 3D 剖面 / 时代场景计划默认**先找真实资产**，但只接受 **CC0 / CC BY /
public domain**。不接受 NC（非商用）、ND（禁止演绎）、来源不明的扫描或图片。

## 资产准入门槛

| 项 | 规则 |
|---|---|
| 许可 | `CC0`、`CC BY`、`public-domain` |
| 署名 | CC BY 必须写作者；CC0 也建议写来源 |
| 单文件 | ≤300MB |
| 缓存总量 | ≤5G（与简报「CC0/CC BY 素材缓存 ≤5G」一致） |
| 真实优先 | 有扫描/照片级模型时优先于自建几何 |
| 禁止 | 付费资产、Google Flow 产物、未授权品牌/人脸/音乐 |

## 资产来源清单（只作政策，不自动下载）

| 来源 | 许可 | 用途 |
|---|---|---|
| Poly Haven | CC0 | HDRI、PBR 材质、少量模型 |
| ambientCG | CC0 | PBR 材质、简单道具 |
| Sketchfab（过滤 CC0/CC BY） | CC0 / CC BY | 扫描件、时代道具 |
| BlenderKit（免费档） | CC0 / CC BY | 道具与材质 |
| Wikimedia Commons | CC0 / CC BY | 参考图、档案照片 |

## CREDITS 写法

每一件进片的外部资产写一行，顺序固定：

```
- 名称 — 作者 — 许可 — 原始链接
```

片尾 CREDITS 由 `hevi/studio/generalist_s23.py` 的 `credits_markdown(plan)` 生成。
没有任何外部资产时，明确写“本片未使用外部 3D 资产；全部几何在 Blender 内自建”，
不要用空的 CREDITS 冒充已经署名。

## S23 黑盒的实际情况

`verify_s23/blackbox/` 的 12 条片全部用 Blender / Pillow / FFmpeg 现场生成，
没有下载任何外部资产，因此 `credits` 为空、CREDITS 文案为自建说明。这是
如实记录，不是遗漏。
