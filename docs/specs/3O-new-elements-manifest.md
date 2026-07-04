# 3O 主库新元素清单(hevi → obase/oprim/oskill/omodul)

状态: Proposed · 2026-07-03 · 来源: hevi 出片链修复与能力扩展会话
目的: hevi 本会话为把"点生成能出片、真人写实、有角色库/对口型"落地,**临时把若干 L2 原语
写进了 hevi**(违背 3O 范式)。本清单把这些能力**规整为应交给 3O 主库的新元素**,并一并
列出 hevi 现有 21 处运行时猴补丁对应的**上游修复项**(修好即可拆补丁)。hevi 落地后只在
registry `from oprim/oskill/omodul import ...` wire。

范式:`obase(L0基座) ← oprim(L2原语) ← oskill(L3技能) ← omodul(L1编排) ← hevi(应用)`。

---

## A. 新增原语(oprim,L2)—— 本会话在 hevi 实现、应回迁

接口沿用 oprim 既有约定(kw-only,`output_path: Path`,返回 `Path`;与 `ltx2_cloud_generate`
/ `vibevoice_synthesize` 一致)。hevi 现成实现可直接搬(附带 hevi 单测)。

### A1. `edge_tts_synthesize` —— 多语言云 TTS(edge-tts)
```python
async def edge_tts_synthesize(*, script: list[Line], output_path: Path,
    language: str | None = None, config: dict | None = None) -> Path
```
- 微软 Edge 神经语音,免费、无需模型、不占 GPU、30+ 语言;按行合成 mp3 → ffmpeg concat 为 WAV。
- 按 language 或文本 CJK 自动选音色(zh/en/ja/ko/es/fr/de…)。
- 与 `vibevoice_synthesize` 并列作 audio 原语。**hevi 现:`hevi/audio/edge_tts_service.py`。**

### A2. `veo3_generate` / `kling_v2_generate` / `hailuo_generate` —— 高写实视频原语(fal)
```python
async def veo3_generate(*, prompt: str, output_path: Path, aspect_ratio: str = "9:16",
    duration_s: float = 8, negative_prompt: str = "", generate_audio: bool = True,
    resolution: str = "720p") -> Path
async def kling_v2_generate(*, prompt, output_path, aspect_ratio="9:16",
    duration_s=5, negative_prompt="", cfg_scale=0.5) -> Path
async def hailuo_generate(*, prompt, output_path, duration_s=6, resolution="768P") -> Path
```
- fal 上 Veo3 / 可灵v2 / 海螺,写实/人体解剖远优于 `ltx-video` 基础版;均支持 negative_prompt + 朝向。
- 端点:`fal-ai/veo3/fast`、`fal-ai/kling-video/v2/master/text-to-video`、`fal-ai/minimax/hailuo-02/standard/text-to-video`。
- 与 `ltx2_cloud_generate` 并列作 video 原语。**hevi 现:`hevi/video/fal_providers.py`。**

### A3. `fal_queue_generate` —— fal 队列通用工具(oprim util 或 obase)
```python
async def fal_queue_generate(*, endpoint: str, payload: dict, output_path: Path,
    timeout_s: float = 600) -> Path  # submit → poll status → 取 response → 下载
```
- 所有 fal 队列制模型共用;带总超时(治 fal 轮询无限挂)。放 oprim 内部或 obase 网络层。

### A4.(计划)对口型原语 `lipsync_generate`
```python
async def lipsync_generate(*, provider: str, audio_path: Path, output_path: Path,
    portrait_image: Path | None = None, source_video: Path | None = None) -> Path
```
- 肖像驱动(portrait+audio→会说话的头):sadtalker/hedra/sonic;视频驱动(video+audio→重对口型):sync/latentsync/musetalk。
- 本地优先(RTX3080,零成本):SadTalker/Hallo2/MuseTalk 子进程隔离,与现有 `avatar_generate`(Duix)并列。

---

## B. 上游修复项(拆除 hevi 21 处猴补丁的前提)

hevi 出片链正确性目前靠这些补丁保证;逐项修到 3O 层后即可删 hevi 补丁 + 加契约测试保护。

### oprim(L2)
| # | hevi 现补丁 | 应修 | 说明 |
|---|---|---|---|
| B1 | `_patched_wan_invoke` | wan_cloud 默认值 | endpoint 用 video-synthesis、model 用 wanx2.1、过滤 video_generate 多传的 `fps` |
| B2 | ltx2 payload 无 negative | `_ltx2_cloud_generate` 加 `negative_prompt` 字段 | fal ltx-video 接受负向,oprim payload 漏发 |
| B3 | fal 轮询 `while True` 无超时 | 轮询加总 deadline / 最大次数 | 卡队列会无限挂(hevi 现用 asyncio.wait_for 兜) |
| B4 | vibevoice 空 `__init__` 再导出 | vibevoice 打包或 oprim 导入兼容 | `patch_vibevoice.py` 现补 transformers5 兼容 + 顶层导出 |
| B5 | `AsyncDashScopeAdapter` + JSON 矫正 | oprim dashscope LLM 走 OpenAI-compat 端点 + 类型矫正 | 原生 SDK 400;矫正 id→str / scenes→dict 供 oskill Pydantic |
| B6 | `video_generate` 硬编码 dispatch | 支持 registry/可插拔 dispatch | hevi 现绕过直接走 registry |

### oskill(L3)
| # | hevi 现补丁 | 应修 |
|---|---|---|
| B7 | `ScriptWrapper` | `storyboard_planner` 不应对 `Chapter.scenes: list[dict]` 调 `.model_dump()` |
| B8 | 旁白过薄(1-5min 只出 ~7s → 成片被压成 6s) | `script_writer` 按 target_duration 生成足量旁白 |

### omodul(L1)
| # | hevi 现补丁 | 应修 |
|---|---|---|
| B9 | `_order_and_dedup_shots` | 装配前按镜头序号排序 + 每序号去重变体(现 `glob("*.mp4")` 乱序留废片) |
| B10 | audio_fn 零容错(抛异常整链崩) | 原生降级:配音失败 → 纯视频出片,不崩 |
| B11 | 镜头失败返回 placeholder 静默 | 暴露失败/策略,便于上层 fallback |
| B12 | `_duration_archetype_to_seconds` 打补丁 | 支持显式 target_duration_s / "short" 短档 |
| B13 | `_default_llm` 用 `ProviderRegistry.get(category=)` 与 obase 单例不兼容 | 统一 obase provider 取法 |
| B14 | 逐镜头 prompt 绕过 hevi 提示词工程 | 暴露 per-shot prompt 钩子 |
| B15 | **RFC-003 多镜头并发**(已设计+分支+17测试) | `max_concurrent_shots` 窗口并发(见 RFC-003-*) |

---

## C. 感知/裁决原语(2026-07-03 · 依 SSOT 核验新识别)

来源:`docs/HEVI-ARCHITECTURE.md`(SSOT)L2/L3 护城河所需的"感知类"能力。**核验结论:3O 已有大半**——`oprim.vlm_video_analyze`、`oprim.transcribe_audio`、`oskill.mllm_frame_consistency_check`、`oskill.video_cost_proposal` + `obase.ProviderContractRegistry`、`oskill.regenerate_animation` 均已存在;A 组(edge_tts/veo3/kling/hailuo/fal_queue/lipsync)已在 `oprim-b5a4` 待合。**故本组只列真正缺口。**

### C1. `subject_embed` —— 身份/视觉向量(oprim,embedding 子模块)
```python
async def subject_embed(*, image_path: Path, kind: str = "face",
    config: dict | None = None) -> list[float]
```
- **缺口确认**:全 3O 无任何人脸/图像 embedder(无 arcface/insightface/clip/facenet)。是**唯一真·新原语**。
- `kind="face"` → 人脸身份向量(insightface/arcface 类);`kind="style"` → 全帧美学/风格向量(CLIP 类)。返回 L2-归一化向量,余弦/欧氏距离即相似度。
- 用途:L2 建 Subject 时离线算 `identity_embedding`;L3 审片算"帧 vs Subject 基准"(身份)、"帧 vs StylePack 基准帧"(风格)距离。
- 落地:CLIP(通用视觉向量,贴风格化角色域,优于真人 ArcFace)**CPU 运行**——不抢 3080(与 stratum/wan/vibevoice 无 GPU 争用);后续 kind="face" 可接 insightface + 人脸裁剪。与 `embedding/bge_m3`(文本)并列。
- **验收**:同人两图距离 < 阈值 < 异人;`kind="style"` 对同 StylePack 帧聚类;向量维度稳定、可 JSON 序列化落库。
- **hevi 现实现(2026-07-04,待回迁 oprim.embedding)**:`hevi/subjects/subject_embed.py`(CLIP ViT-B/32,512 维,L2-归一化,CPU 单例)+ `Subject.identity_embedding` 列(迁移 `d1e2f3a4b5c6`)+ 建角色时 best-effort 落库(`subject_service._compute_identity_embedding`)。核验:同 subject 距 0.018 < 异 subject 0.072;DB 往返无损。测试 `tests/test_subject_embed.py`。

### C2. `qwen3_vl` provider 注册 —— 本地 VLM(obase/provider,非新原语)
- **性质**:不是新原语——`oprim.vlm_video_analyze(provider="qwen3_vl", frames, prompt)` 与 `oskill.mllm_frame_consistency_check(mllm=...)` **已存在**,缺的是一个真实 VLM provider。这是 SSOT 的"单点命门"。
- **契约**:实现 registry 的 mllm 调用约定 —— `mllm(messages, image_paths: list[str]) -> {"content": str}`(见 `oskill/mllm_frame_consistency_check.py:108`),即像 hevi `local_qwen_adapter` 但**不丢 `image_paths`**,把帧编码进 VL 请求。
- **后端**:本地 ollama 拉 `qwen2.5vl`;抽帧策略每镜头 3–5 帧 + 首尾。**VRAM 现实**:3080 与 stratum/aii(~4.6GB 常驻)共享,仅 ~5.6GB 空余 → 7b(6GB)会 CPU 卸载 + 视觉编码器 OOM,**默认 3b**(env `OLLAMA_VL_MODEL` 可切 7b)。
- **验收**:对"同角色/异角色"两帧给出可区分一致性判断;economy 档零云成本;并发经 obase 与 wan/vibevoice 串行不 OOM。
- **hevi 现实现(2026-07-04,待回迁 oprim/obase)**:`hevi/providers/local_qwen_vl_adapter.py`(mllm 契约,base64 图 → ollama OpenAI-compat,keep_alive:0 卸载,JSON 抽取)+ orchestrator 注入 `_providers["mllm"]`(`vl_model_available()` 探针门控,不可用则回退旧态)。核验:VL 读像素(anti-cheat 误导文件名仍答对)、双变体不再瞎选第一个。测试 `tests/test_local_vl_adapter.py`。**遗留**:`mllm_frame_consistency_check` 仍把 reference 当文本路径发,真·图对图比对留 C4。

### C3. omodul:结构化 per-shot 结果 + 镜头级返工(omodul,契约扩展)

> **✅ 已合并 + hevi 已钉版(2026-07-04)**:omodul **v1.36.0** 已发布([#8](https://github.com/helios-plat/omodul/pull/8) merged),hevi `pyproject` 已 bump `@v1.36.0`,`ShotRecord`/`regenerate_shots` 在装机可用(425 测试绿)。**剩最后一里(hevi 侧,后续)**:orchestrator 读 `result.shots` 落 `ShotState` + 评分卡 `hints`→`regenerate_shots`。

```python
class ShotRecord(BaseModel):     # 新增
    index: int; path: Path; provider: str
    variant_chosen: int; consistency_score: float; passed: bool; duration_s: float

class LongVideoResult(BaseModel): # 扩展
    ...                           # 现有字段
    shots: list[ShotRecord]       # 新增:替代只暴露 shots_generated: int

async def regenerate_shots(*, task_dir: Path, shot_ids: list[int],
    hints: dict[int, str] | None = None, **pipeline_kwargs) -> LongVideoResult
```
- **缺口确认**:`LongVideoResult` 现仅 `shots_generated: int`(`agentic_longvideo_pipeline.py:74`),内部 `best_frame`/分数算了即弃;无 shot 定向入口。
- `regenerate_shots` 复用镜头级 checkpoint:只重生成指定 shot,`hints[idx]` 注入该镜头 prompt 富化,其余复用。与 B9(装配前排序去重)/B11(失败暴露)兼容;可复用 `oskill.regenerate_animation`。
- 用途:直接支撑 hevi 侧 `ShotState` 落库 + L3 verdict→返工闭环 + L4 Editor。
- **验收**:`regenerate_shots(shot_ids=[2,5])` 只重跑这 2 镜头;返回 `shots` 含每镜头 variant/score;`hints` 进 prompt;未指定镜头字节不变。

### C4. `shot_scorecard` —— 评分卡技能(oskill)
```python
async def shot_scorecard(*, frames: list[Path], mllm: Any,
    subject_ref_embedding: list[float] | None = None,
    style_ref_frame: Path | None = None,
    deterministic: dict | None = None, config: dict | None = None) -> Scorecard
# Scorecard = {identity_score, style_score, vlm_score, checks: dict, passed: bool, hints: list[str]}
```
- 是 `mllm_frame_consistency_check`(仅 `vlm_score`)的**超集**:加 `subject_embed` 距离(identity/style_score)+ 确定性检查(时长/字幕/响度)聚合。
- 渐进:v0 = 包 `mllm_frame_consistency_check` + 确定性;v1 加 embedding 锚。**裁决阈值/策略留 hevi(护城河),可复用打分机制放 oskill。**
- **验收**:及格帧 `passed=True`;砸帧给可操作 `hints`(喂 C3 的 `hints`);`identity_score` 对异人帧显著降。
- **hevi 现实现(2026-07-04,待回迁 oskill)**:`hevi/verdict/scorecard.py`(`shot_scorecard` + `Scorecard` + `make_scorecard_consistency_fn`)+ `hevi/verdict/frame_extract.py`(PyAV 抽代表帧,不依赖系统 ffmpeg)。**已接线**:orchestrator 在角色锁定(非 short)时算参考图向量 → 注入 `_providers["consistency_fn"]`,双变体按身份选优 —— **补上 C2 遗留**(不再把 reference 当文本发,而是 C1 向量真·图对图)。核验:图候选 [0.928 异/0.996 同]→选同;mp4 候选 [0.799/1.0]→选同(PyAV 抽帧)。测试 `tests/test_shot_scorecard.py`。**v0 范围**:identity 锚 + 确定性 pass-through;`vlm_score`/`style_ref` 钩子留待。新依赖 `av>=12`。

### C5. `fal_balance_probe` + provider 健康/余额状态(obase,或 Aegis)
```python
async def fal_balance_probe(*, config: dict | None = None) -> dict  # {balance_usd, ok, source}
```
- `ProviderContractRegistry` 已给成本,缺"活的状态"(SSOT §4-3):查 fal balance API,查不到用滚动 403 率代理。
- 归属 obase 网络层或 Aegis runtime;hevi 只读状态做路由/熔断;低阈值 → Prometheus/Aegis 告警。
- **验收**:余额低于阈值触发告警;探针失败降级为 403 率代理不崩。
- **✅ 已合并 + hevi 已钉版(2026-07-04)**:obase **v0.17.0** 已发布([#5](https://github.com/helios-plat/obase/pull/5) merged),hevi `pyproject` 已 bump `@v0.17.0`,`obase.provider_live_state`(`ProviderLiveState`/`Rolling403Rate`/`fal_balance_probe`)装机可用。⚠️ 上游小疵:`v0.17.0` tag 的 commit 内部版本号仍是 `0.16.1`(版本同步漏了此 commit)——代码无碍,建议上游对齐。**剩最后一里(hevi 侧,后续)**:L0 路由/熔断读 `ProviderLiveState`。

### C 组落地序 & 优先级
- **Phase 0 命门(先做)**:C1 `subject_embed` + C2 `qwen3_vl` provider —— 一次点亮 L1 真双变体校验 + L3 审片,GPU 已就绪。
- 其后:C4(评分卡,依赖 C1/C2)→ C3(omodul 返工契约,支撑落库/闭环)→ C5(余额探针,L0 交易所)。
- 合并序仍 `oprim(C1) → obase/provider(C2,C5) → oskill(C4) → omodul(C3)`,各走 `feat/v{semver}-*`。

---

## D. 落地方式(按 RELEASE_POLICY)
1. 合并序 **oprim → oskill → omodul**;各走 `feat/v{semver}-*` 分支,发版后 hevi 钉新版本。
2. A 组(媒体生成原语)**已在 `oprim-b5a4` 实现**,待合入 oprim main;合后 hevi registry 改 `from oprim import ...`,删对应 hevi 文件。
3. B 组(修复)逐项修 + 在 hevi 侧留契约测试(本会话已起 `tests/test_upstream_contracts.py`),上游修好即删对应补丁。
4. RFC-003(B15):并发引擎**已合入 omodul(现 v1.35.0,`max_concurrent_shots` 窗口并发)**;剩 hevi 侧 `config_builder` 按档位注入 >1(见 SSOT §7-3)。
5. C 组(感知/裁决):C1/C2 为 **Phase 0 命门**(GPU 已就绪);`transcribe_audio` / `video_cost_proposal` + `ProviderContractRegistry` 已在 3O,hevi **直接采用**(非新建)。

---

*现状备注(2026-07-03)*:本机 GPU **已恢复**(ollama/Wan2GP/VibeVoice/faster-whisper 已接通),C1/C2
本地实现可即刻验证;fal 余额仍需充值,A 组云原语与 fal-lipsync 的 e2e 验证待充值后进行。接口设计不受影响。
