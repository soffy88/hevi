# EmbeddingGemma 2 共享嵌入服务 — 接入说明（Hevi omfootage）

> 2026-10-13 部署并实测。本文只是说明，omfootage 代码未改动。
> 同一服务也给 AII/Stratum 用（见 `/data/soffy/projects/stratum/docs/EMBEDDINGGEMMA2_SERVICE.md`）。

## 1. 服务概况

| 项 | 值 |
|---|---|
| 模型 | `google/embeddinggemma-2`（Apache-2.0，修订 `914f7f89`，经 hf-mirror.com 下载），文本 + 图像 + 视频共用一个 768 维空间，支持 MRL 512/256/128 |
| 机器 | 笔记本 DESKTOP-72AVCFH，WSL Ubuntu-26.04，GTX 1050 Ti 4GB |
| 运行设备 | **GPU，float32**（这张卡不支持 bf16；float16 会出 NaN，禁止使用） |
| 显存 / 内存 | 模型约 1.68 GB 显存（torch 预留峰值约 2.0 GB，nvidia-smi 空闲时约 1.76 GB）；进程内存约 1.1–2.2 GB |
| 已加载模态 | 文本 + 图像 + 视频；音频编码器**按需**在 CPU 上加载，闲置 10 分钟后卸载 |
| **推荐地址** | **`http://100.68.226.13:8790`**（Windows 的 tailnet IP，经 netsh portproxy 转到 WSL） |
| 不推荐 | `http://100.119.113.90:8790`（WSL 自己的 tailscale IP）：从 ubuntu26 访问时，几 KB 以上的响应体会卡住，拿到 200 响应头后 body 一直到超时都不来。同一台机器上 AII 的 :8102 服务走这个 IP 也一样。 |
| 自启 | systemd `embgemma2.service`（已 enable，`Restart=always`）。`ExecStartPre` 会等数据盘 LABEL=airllm 挂载到 systemd 的命名空间。Windows 计划任务 `Hark-EmbGemma2-Portproxy`（开机延迟 60 秒 + 每 30 分钟一次）在 WSL IP 变化后刷新 8790 portproxy；防火墙规则名 "Hark EmbGemma2 (8790)" |
| 鉴权 | 默认不开（只在 tailnet 内）。服务上设环境变量 `EMB_API_KEY` 就会要求 `Authorization: Bearer <key>` |
| 文件 | 模型 `/mnt/airllm/embgemma2/model`，venv `/mnt/airllm/embgemma2/venv`（py3.14，torch 2.14.1+cu126，transformers 5.19.0，sentence-transformers 6.1.0），代码 `/mnt/airllm/embgemma2/app/server.py` |

运维：`sudo systemctl status|restart embgemma2`，`journalctl -u embgemma2`。可调环境变量：`EMB_MAX_SEQ`（默认 2048，最大 8192，越大越吃显存）、`EMB_MAX_BATCH`（默认 32）、`EMB_BATCH_WAIT_MS`（默认 10）、`EMB_DEFAULT_TASK`、`EMB_DEVICE=cpu`。

## 2. 接口

### POST /v1/embeddings（OpenAI 标准兼容）
```json
{"input": "文本" 或 ["文本1","文本2"], "model": "embeddinggemma-2",
 "dimensions": 768|512|256|128, "encoding_format": "float"|"base64",
 "task": "SearchQuery"|"Document"|...   // 扩展字段，可选
}
```
- 返回 OpenAI 格式 `{"object":"list","data":[{"object":"embedding","index":i,"embedding":[...]}],"model":..,"usage":{..}}`，向量已做 L2 归一化（截断维度后会重新归一化）。
- 任务前缀（提升检索质量）有三种给法：`task` 字段，或 `input_type: "query"|"document"`，或只能设 model 名的标准 OpenAI 客户端用 model 别名：`embeddinggemma-2-query`（= SearchQuery 前缀）/ `embeddinggemma-2-document`（= Document 前缀）/ `embeddinggemma-2`（不加前缀）。
- 支持的 task 名：SearchQuery, Document, QuestionAnswering, FactChecking, CodeRetrieval, Classification, Clustering, SentenceSimilarity, STS, Retrieval-query, Retrieval-document 等（`/health` 里有完整列表）。
- 支持批量和并发：一次最多 2048 条输入，服务端会拆成 32 条一块。并发请求进动态批处理队列（等 10 ms 合批），GPU 一次只跑一个前向，按先后顺序排队，不会报错。
- 不支持 token id 输入。

### POST /v1/embeddings/multimodal
```json
{"input": [{"image": "<base64 | data:URL | http(s) URL | 笔记本本地路径>"},
           {"video": "..."}, {"audio": "..."},
           {"text": "说明 <|image|>", "image": "..."}],
 "dimensions": 768}
```
- **ubuntu26 上的文件路径笔记本看不到**，远程调用必须传 base64（或 http URL）。
- 图像、视频、音频不加任务前缀。查询文本用 `/v1/embeddings` 加 `task=SearchQuery`，两边在同一个空间里，可以直接算余弦。
- 视频默认按 1 fps 抽帧（最多 32 帧）；音频要 16 kHz 单声道，第一次调用要在 CPU 上加载音频编码器，会慢。

### GET /health, GET /v1/models
`/health` 返回设备、dtype、显存、队列深度、计数器。

### POST /embed（兼容 AII 旧接口的形状）
`{"texts":[...]}` → `{"embeddings":[...],"dim":768,"device":"cuda"}`。注意这是 EmbeddingGemma2 的向量空间，不是 BGE-M3。

## 3. 用法示例
```bash
curl -s --noproxy '*' http://100.68.226.13:8790/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"input":["冬天静电","静电产生原因"],"task":"SentenceSimilarity","dimensions":768}'
```
```python
from openai import OpenAI          # 标准 SDK 直接用
c = OpenAI(base_url="http://100.68.226.13:8790/v1", api_key="none")
q = c.embeddings.create(model="embeddinggemma-2-query", input="雪山日落").data[0].embedding
```
```python
import base64, httpx               # 图像
b = base64.b64encode(open("frame_00.jpg","rb").read()).decode()
v = httpx.post("http://100.68.226.13:8790/v1/embeddings/multimodal",
               json={"input":[{"image": b}]}, timeout=120).json()["data"][0]["embedding"]
```
⚠ ubuntu26 上 soffy 的登录 shell 设置了 http_proxy，调用时要绕过代理（curl 加 `--noproxy '*'`；Python 设 `NO_PROXY=100.68.226.13`，或者 `httpx.Client(trust_env=False)`），否则会被代理返回 502。

## 4. 实测数字（2026-10-13，客户端在 ubuntu26，经 100.68.226.13:8790）

原始结果在 Hark 审计目录 `audit/embeddinggemma2/results.json`，脚本是 `bench.py`。

**文本正确性**：维度 768，全部有限值，范数都是 1.0。
| 句对 | 无前缀 | SentenceSimilarity 前缀 |
|---|---|---|
| 冬天静电 ↔ 静电产生原因 | 0.795 | **0.891** |
| 冬天静电 ↔ 蓝鲸 | 0.731 | **0.814** |
| 冬天静电 ↔ winter static electricity | 0.884 | 0.965 |
| 蓝鲸 ↔ blue whale | 0.931 | 0.955 |
| 冬天静电 ↔ 为什么冬天容易被电到 | 0.880 | 0.924 |

MRL（SentenceSimilarity）静电-原因 / 静电-蓝鲸：512 维 0.892/0.810，256 维 0.897/0.822，128 维 0.930/0.893（128 维时两者差距明显变小，模型卡也说 128 维会降低多模态质量）。

**延迟和吞吐（GPU fp32）**
- 单条短文本：p50 **91 ms**（最快 83 ms，含网络往返）
- 批量 32 条短文本：p50 **309 ms**，约 **104 条/秒**
- 长文本约 1800 字：p50 **507 ms**
- 并发 16 个客户端 × 4 次 × 每次 8 条：用时 3.39 秒，约 **151 条/秒**，单请求 p50 715 ms、最长 1.7 秒，0 错误
- 图像：**约 0.98 秒/张**（153 张缩略图共 150 秒）。原因是每张图默认用 280 个 soft token（2520 个 patch）过视觉编码器，1050 Ti 跑 fp32 就是这么慢；预处理只要 0.01 秒。按 8 张一批发送也没有加速（服务端逐条编码）。

**图文检索**（omfootage 真实语料 `data/corpus`：index 167 行，其中 153 行有 `frame_00.jpg`。21 个查询；标签用每条素材的 `query` 字段，也就是当初去 archive.org/pexels 搜它用的词，比较粗糙）
| 方案 | hit@1 | hit@5 | P@5 |
|---|---|---|---|
| 现状 CLIP ViT-B-32，英文查询 | **0.857** | 0.905 | 0.505 |
| 现状 CLIP，直接用中文查询 | 0.238 | 0.571 | 0.162 |
| EmbeddingGemma2，中文查询 + SearchQuery 前缀 | 0.619 | 0.905 | 0.476 |
| EmbeddingGemma2，中文查询，无前缀 | 0.619 | 0.905 | **0.524** |
| EmbeddingGemma2，英文查询 + SearchQuery 前缀 | 0.714 | 0.905 | 0.505 |

中文查询示例 top-3：「从太空看地球」→ Earth in 4K – Space Station…、The Secrets behind Earth's Multi-colored Glow…；「草原上的野生动物」→ giraffe-in-the-wild、Midway Atoll Bird Sightings、giraffe-walking-in-savanna。

结论：中文直接查询时，EG2 远好于 CLIP（hit@5 0.905 对 0.571），而且不用先翻译。CLIP 英文查询的 hit@1 更高，但 hit@5 和 P@5 跟 EG2 持平。样本只有 21 个查询、标签也粗，替换前最好用人工标注的查询集再评一次。

## 5. 能否、怎样替换 omfootage 的 CLIP 检索（只是方案，没动代码）

现状（`hevi/sourcing/corpus.py`）：open_clip ViT-B-32（`/home/soffy/models/open_clip`，在 CPU 上跑），`EMBED_DIM = 512`，每个片段取首帧 `thumbnails/<clip_id>/frame_00.jpg` 编码，结果存到 `data/corpus/embeddings.npy`（形状 (N,512)，行序和 `index.jsonl` 对齐）。`_text_emb()` 遇到中文会先用本地 ollama 翻成英文，再交给 CLIP 文本编码。入口是 `rank_for_slot()`，被 `hevi/explainer/assembly.py:243` 和 `corpus.py:723` 调用。

**可以替换，而且必须重建索引**：EG2 的向量是 768 维（或 512/256/128），和 CLIP 不在同一个空间。旧的 `embeddings.npy` 不能复用，查询和索引必须同时切到 EG2、用同一个维度。

建议步骤：
1. 在 `corpus.py` 加一个嵌入后端开关，例如 `HEVI_CORPUS_EMBED=clip|eg2`，默认先保持 clip。eg2 后端：
   - 图像：`frame_00.jpg` 转 base64，POST `/v1/embeddings/multimodal`
   - 文本：POST `/v1/embeddings`，`task=SearchQuery`（或无前缀，实测 P@5 略高），**去掉 ollama 翻译这一步**
   - 维度用 768。想省空间可以用 512，接近无损；128 不建议
2. 索引另存一个文件，例如 `data/corpus/embeddings_eg2_768.npy`，和旧 CLIP 索引并存。在 `index.jsonl` 或旁边的 meta 文件里写上 `embed_model` 和 `dim`，加载时校验，防止两个空间混用。
3. 重建方法：一次性脚本遍历 `index.jsonl`。按实测约 1 秒/张，153 张大约 2.5 分钟；1000 张大约 17 分钟。另外有 14 条记录没有缩略图，要先补抽帧。
4. 可以进一步做（可选）：EG2 支持视频输入（1 fps，最多 32 帧），可以把整段 clip 当视频编码，代替只看首帧。代价是更慢，需要再评测。
5. 服务不可用时要降级：回退到 CLIP 后端，或者直接报错。不能拿 EG2 的查询向量去比 CLIP 索引。
6. 先拿人工标注的中文查询集做 A/B，确认后再改默认值。`subjects/subject_embed.py` 和 `vault/identity_pack.py` 里的 CLIP 用法是做身份/主体相似度，不属于素材检索，建议不在这次替换范围内。

性能注意：笔记本 GPU 一次只编码一个请求。批量建索引时会和其他调用方（AII 等）排队，最好放在空闲时段跑。如果要提速，可以在服务端加降低视觉 token 预算的选项（模型支持 70–1120 个 soft token，默认 280），但这还没有实现。
