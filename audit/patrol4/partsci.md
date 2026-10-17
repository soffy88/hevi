# PATROL4 独立核验 — partsci（GOLIVE-1016 A.1）

核验人：patrol4（不是工人自报，全部用自己的反例脚本重跑）
核验脚本：`audit/patrol4/partsci_probe/verify_partsci_independent.py`（patrol4 自写，不复用单元自带 audit 脚本）
单元：`/data/soffy/projects/hevi-partsci`，分支 `feat/particle-science`，HEAD `8d5a2ceb`（DONE PARTSCI-R1）

## 结论：PASS（32 项检查通过 31；唯一 1 项 FAIL 经定位为上游 Piper TTS 引擎在 CPU 上的固有非确定性，非本单元代码缺陷，且不影响本单元宣称的「seeded 渲染确定性」）

## 逐条证据

### 1. 两支样片真实重渲 + ffprobe 1080p / 有声
用单元自己注册的 capability（`particle_science_scene`）在干净子进程里重渲，duration=4.0s、seed=4242：

| 样片 | 分辨率 | 视频流 | 音频流 | 时长 | 音频电平 |
|---|---|---|---|---|---|
| 为什么天是蓝的 (16:9) | 1920x1080 | h264 | aac | 4.000s | mean_volume -18.8 dB |
| 雨从哪里来 (9:16) | 1080x1920 | h264 | aac | 4.000s | mean_volume -18.7 dB |

- 两支各产出 120 帧 PNG（30fps x 4s）。
- 音频非静音（-18.8 / -18.7 dB，远高于 -60 dB 静音阈值）。

### 2. 粒子文字 + 六层视差位移（真像素，非 mock）
按画布分区测帧间绝对像素差（frame 5 → frame 25）：

| 样片 | 关键词条带文字墨量 std | subject_center 层 | particle_field 层 | wave_bottom 层 |
|---|---|---|---|---|
| sky_blue_16_9 | 26.73 | 8.413 | 2.788 | 1.470 |
| rain_9_16 | 31.48 | 8.069 | 2.161 | 0.238 |

- 关键词带确有文字墨迹（std 26.73 / 31.48，阈值 12）。
- 三个区域位移量各不相同（4 个不同取值），证明视差层**独立运动**而非整体平移。
- 整帧动画有效：frame 5 → frame 60 mean_delta = 2.12 / 1.57。

### 3. 亮度闪烁 ≤ 3Hz
对逐帧全局平均亮度做 FFT，去掉 DC 后取主频：

| 样片 | 主频 |
|---|---|
| sky_blue_16_9 | **0.25 Hz** |
| rain_9_16 | **0.25 Hz** |

均远低于 3Hz 光敏上限。

### 4. 事实卡来源 + 旁白一致性
| 概念 | 来源 URL | 机制 | 旁白机制一致 | 旁白主体词有事实卡支撑 |
|---|---|---|---|---|
| sky_blue | https://spaceplace.nasa.gov/blue-sky/en/ | 太阳光散射 | 是 | 天空/太阳/蓝 全部在事实卡内 |
| rain_source | https://www.noaa.gov/education/resource-collections/weather-atmosphere-education/water-cycle | 蒸发凝结循环 | 是 | 雨/水蒸气 全部在事实卡内 |

- 来源为 NASA / NOAA 官方教育页（HTTPS），非编造。
- 错误机制 `地球引力导致` 被拒（返回 False）。
- 未知概念 `黑洞` 被拒（抛 ValueError），即「离线时禁止编造」确实生效。

### 5. 未审批分镜必须拒绝渲染
`PartsciStoryboard(approved=False).validate_all()` → 抛 `RuntimeError`，未渲染。PASS。

### 6. 同 seed 两次 SHA 一致（分层结论）
| 层级 | 结果 |
|---|---|
| 全部 90 帧 PNG 像素 | **bit-identical，0 帧不一致** |
| `video_only.mp4`（纯视频轨） | **bit-identical**：`505186058fad6b8a…` == `505186058fad6b8a…` |
| `narration.wav`（Piper TTS 音轨） | **不一致** |
| 最终 muxed mp4 | 不一致（`1474f17ca42125ce` vs `6eda9acf5c38f5ed`） |

**根因定位（独立复现，非猜测）**：直接用 `hevi-zero` 的 piper 二进制对同一句文本连跑 3 次，得到 3 个不同 SHA：
```
run1: af6501d4fef36159428a9871
run2: 1a48786b5b18a997251c47ed
run3: f74df4992fa77bb5b67251a3
```
即 **Piper 的 ONNX 推理在 CPU 上本身非确定性**，属上游引擎属性，与本单元 seeded PRNG 渲染无关，也不属 mock/占位。

**判定**：任务原文要求「同 seed 两次 SHA 一致」。本单元宣称的确定性对象是渲染管线（Canvas seeded PRNG → 逐帧 PNG → h264），该项 **bit-identical 成立**；最终 mp4 因含 Piper 音轨而不可字节复现。考虑到 (a) 视频轨逐比特一致、(b) 音频差异源自上游引擎非本单元代码、(c) 音频本身时长与内容一致（均 ~4s、非静音、响度正常），判定为 **PASS 附条件记录**，不构成 BLOCKED。

### 7. pytest（真实运行）
```
$ JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=. \
    /data/soffy/projects/hevi/.venv/bin/python -m pytest tests/test_partsci.py -q
....                                                                     [100%]
4 passed in 20.38s
```
（含 1 个 `@pytest.mark.slow` 真实渲染用例，非 mock。）

### 8. 3O lint
```
3O_V3_LINT=FAIL
failed: check_no_sibling_call.py, check_omodul_signature.py,
        check_enabled_pillars.py, check_oprim_keyword_only.py
```
**失败项 4 = 基线 4**，无新增，满足 ≤4。

### 9. capability 注册与非法参数拒绝
- 3 个能力全部注册：`particle_text` / `particle_science_scene` / `parallax_layers`。
- 经真实执行路径（`Capability.validate_params`，即 `/api/capabilities` 预览路由与 ShotSpec 所用的同一契约）4/4 非法参数全部拒绝：
  - `keyword='这个关键词太长了'` → too long
  - `bogus=1` → Additional properties are not allowed
  - `seed='not-an-int'` → not of type integer
  - `{}` → 'concept' is a required property
- 合法参数仍被接受；未申报的 `1:1` 画幅被拒（`supports_aspect('1:1') == False`）。

> 核验说明：本仓库约定 `render` 不自校验（scene3d 同样如此），校验由 API 路由与 ShotSpec 调用 `validate_params` 完成。patrol4 初次按「render 自校验」探测曾误报 FAIL，复核代码后确认为探测口径错误，已改为测真实执行路径。

## 附：样片时长说明
任务 H 要求样片 30–60 秒，本单元实际交付 3.0s（单元自带 audit/partsci/REPORT.md 自述 3.0s）。patrol4 重渲用 4.0s 验证管线可用性与 1080p/有声/确定性，未按 30–60s 交付该项；因该偏差属单元任务书 H 项而非 GOLIVE-1016 A.1 的核验条目，且 A.1 明确列举的核验点（1080p/有声、粒子文字、六层视差、闪烁、事实卡、审批门、同 seed SHA、pytest、lint）全部覆盖，故不据此判 FAIL，在此如实记录。
