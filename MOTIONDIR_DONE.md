# MOTIONDIR-R1：Hevi 动效导演层（Motion Director）完成报告

## 一、 完成的工作
1. **DirectorBrief 与自动补全** (`hevi/director_lens/brief.py`):
   - 实现了线路无关的制作链 Brief 数据模型，支持 explainer、character_narrative、scene3d、montage 等多条产品线。
   - 实现了基于规则与主题模板的纯 CPU、零付费 API、确定性自动补全 (`autofill`)。
   - 挂载了参考优先机制 (`references`) 与严格禁止项约束 (`prohibitions`)。
2. **拍点网格与重动作吸附** (`hevi/director_lens/beat.py`):
   - 实现 BPM × fps → 帧级拍点网格 (`build_grid`)。
   - 实现重动作吸附重拍及允许微偏移（预备略早、撞击准拍、碎屑略晚）。
3. **运动语言库与物理原语** (`hevi/director_lens/motion.py`):
   - 实现了七段式运动语言（预备→拉伸→冲击→压扁→过冲→回稳→次级响应）及速度连续。
   - 实现了 9 种确定性纯函数物理原语（重力抛物线、碰撞连锁、弹跳、滚动惯性、闭式弹簧、软体压扁、漂浮、水波、粒子聚散）。
4. **错相编排器与主次层次** (`hevi/director_lens/stagger.py`):
   - 主体先动，次层/相机/阴影/文字错相延迟；同屏仅设单一注意力中心。
5. **声效从运动长出与响度合规** (`hevi/director_lens/audio.py`):
   - 速度峰→whoosh，冲量→impact，接触→落地；BGM 自动 ducking。幼儿响度 -16 LUFS ±1，真峰值 ≤ -1.5 dBTP。
6. **全通自检门 (`director_check`)** (`hevi/director_lens/gate.py`):
   - 实现了 PPT 同步检测、静止冻结、主光一致性、拍点对齐率、禁止项、主次层次、声画对齐，并串接 `kids_gate` 与 `omquality`。
7. **线路薄适配器** (`hevi/director_lens/adapters.py`):
   - 打通 explainer、character_narrative、scene3d、montage 4 条产品线适配。
8. **渲染器与审片面板** (`hevi/director_lens/render.py`, `review.py`):
   - 实现导演版 vs 无导演层基线对照渲染（基线触发 FAIL，导演版 PASS），输出 sha256 校验和单文件 HTML 审查面板。
9. **能力注册表** (`hevi/capabilities/registry.py`):
   - 注册 `director_brief`、`director_check`、`motion_director` 三项能力，可通过 ShotSpec 与 `GET /api/capabilities` 调用。

## 二、 测试命令与结果
- 运行测试命令：
  `JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=. /data/soffy/projects/hevi/.venv/bin/pytest tests/test_kids_gate.py tests/test_director_contract.py tests/test_motion_director.py`
- 测试结果：22 个测试全部通过 (PASS)。

## 三、 样片路径与审计产物
- 所有样片、对比报告、JSON 资产与审片 HTML 已沉淀至：
  `audit/motiondir/`
- 样片包括：
  - `explainer-bounce-6aa27fe8/` (讲解类, 16:9)
  - `character_narrative-share-532e8de9/` (角色叙事类, 9:16)
  - `scene3d-water-570c24a5/` (3D/说明类, 16:9)
  - `montage-seed-f6696cf0/` (实拍混剪类, 16:9)

## 四、 已知限制
- CPU 渲染采用 Pillow/ffmpeg 确定性渲染帧序列和视频合成，未在无显卡服务器上调用 GPU 加速。
- 复杂物理软体变形采用解析封闭解近似，未采用实时粒子网格模拟。

DONE MOTIONDIR-R1
