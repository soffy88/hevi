# brandfilm — Hevi CPU 15 秒品牌片内化层

本目录是从上游 [`nutllwhy/code-brand-film`](https://github.com/nutllwhy/code-brand-film)
（MIT License, Copyright (c) 2026 nutllwhy）vendor 进来的完整品牌片流水线，
存放于 `hevi/layer4_legacy/brandfilm/`，许可与归属登记见
[`docs/third_party/provenance-ledger.yaml`](../../../docs/third_party/provenance-ledger.yaml)。

原则：**上游材料保持原样**（含 `LICENSE`、`THIRD_PARTY_NOTICES.md`、`references/`、
`examples/`），Hevi 侧的适配代码另行新增，见 `../brandfilm_line.py` 与
`hevi/validation/layout_gate.py`，以便追溯到上游基线。

## 目录

| 路径 | 内容 |
| --- | --- |
| `LICENSE` | 上游 MIT 许可证（原样保留） |
| `THIRD_PARTY_NOTICES.md` | 上游第三方声明（Noto OFL、GSAP Standard License、HyperFrames CLI） |
| `README.md` | 上游说明（原样保留） |
| `SKILL.md` | 上游工作流文档（原样保留） |
| `references/` | 上游创作方法 9 篇：creative / layout / assets / quality-bar / shot-list / recipes / pipeline / scoring / footage-led |
| `scripts/` | 上游三道质量闸门与配乐库。**已做的最小适配**：`layout_audit.mjs` 增补 Linux headless 必需参数 `--no-sandbox` / `--disable-dev-shm-usage`，Chrome 探测顺序增加 `~/.cache/hyperframes` 与 `~/.cache/ms-playwright`，并支持 `--width/--height` 覆盖与从 `data-width/data-height` 读取竖屏画幅；检测逻辑一行未改 |
| `assets/hyperframes.json` | 上游 HyperFrames 工程配置 |
| `examples/office-agent/` | 上游完整参考片（含 `film/`、`src/`、`audio/score.py`、`shot-list.md`、`copy.md`、`assets.md`） |

## 可用闸门（返回 `0 failed` 才算交付）

```bash
cd hevi/layer4_legacy/brandfilm
python3 scripts/film_audit.py examples/office-agent/film/index.html     # 代码闸门
node scripts/layout_audit.mjs examples/office-agent/film/index.html     # 摆位闸门
python3 scripts/frame_audit.py examples/office-agent/film/renders/silent.mp4  # 像素闸门
```

配乐库 `scripts/score_lib.py` 可单独作为 Hevi 原创曲合成器使用；Brief 采样见
`scripts/score_template.py`。
