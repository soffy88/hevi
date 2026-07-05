# HEVI-SPEC-03: 资产库(Hevi Asset Vault)持久化存储设计

- **状态**: DRAFT
- **版本**: v0.1
- **定位**: 角色/风格/场景/声音资产的持久化底座,服务 SPEC-01/02 双管线;设计为独立 omodul(`asset_vault`),接口通用化,未来可下沉为 3O 跨项目组件(Mneme 的教具素材、Helios 的图表模板同样是"生成一次、跨 run 复用"的资产)
- **核心命题**: 资产是通鉴 294 卷量产的复利来源——智伯的身份包做一次,此后所有涉及智伯的章节零成本复用。资产库的质量决定边际成本曲线的斜率

---

## 1. 三层存储架构

```
┌─────────────────────────────────────────────────┐
│  L-Blob   MinIO(S3 兼容,本地部署)              │
│           内容寻址:sha256 命名,不可变,自动去重  │
├─────────────────────────────────────────────────┤
│  L-Meta   PostgreSQL                             │
│           资产包/版本/文件/平台绑定/血缘          │
├─────────────────────────────────────────────────┤
│  L-Vector pgvector(同库扩展)                    │
│           身份/风格 embedding:QA 比对 + 相似检索  │
└─────────────────────────────────────────────────┘
```

- **L-Blob**: 所有二进制(图/视频/音频/npy)以 `sha256[:2]/sha256` 分桶存 MinIO,文件名即哈希 → 天然去重、天然可校验、引用永不失效。bucket 划分:`vault-identity` / `vault-style` / `vault-scene` / `vault-audio` / `vault-derived`(成片与中间 clip)
- **L-Meta**: 结构与语义,见 §3 DDL
- **L-Vector**: 每个资产版本的 embedding 入 pgvector。三个用途:① CG5/CG6 门的身份比对基准;② 新建资产查重(新角色与库内角色相似度过高 → 提示复用或强制差异化,防止 294 卷里两个配角撞脸);③ 按视觉相似度检索场景资产复用

选型理由:全部组件(MinIO/PG/pgvector)已在你现有栈内或零新增学习成本,单机 WSL2 可跑,Aegis 可纳管。

---

## 2. 资产包模型(Pack = 目录 + Manifest)

沿用 SKILL.md/marketplace.json 的分发范式:每个资产包是一个自描述目录,`manifest.json` 是唯一入口,人可读、机可校验、可整包导出迁移。

### 2.1 包类型与目录规范

```
vault://identity/C001-智伯/
├── manifest.json            # 唯一入口,schema 强校验
├── PACK.md                  # 人读说明:角色设定、构建记录、已知问题
├── refs/
│   ├── front.png            # 正面权威像
│   ├── grid9.png            # 九宫格多视角
│   ├── action_pose.png      # 动态姿势参考(§SPEC-02-11.1 强制)
│   ├── turnaround_5s.mp4    # 转身视频
│   └── expressions/         # 表情表
├── voice/
│   ├── voice_ref_8s.wav
│   └── tts_config.json
├── embeddings/
│   ├── identity.npy         # photoreal: ArcFace / animated: anime embedding
│   └── style_affinity.npy
└── renders/                 # 分风格渲染变体
    ├── animated@guofeng-ink/   # 国风水墨版全套 refs
    └── photoreal@default/      # 写实版全套 refs
```

四种包类型,同构管理:
- **identity**(角色): 上述结构;`renders/` 支持同一角色多风格变体共存
- **style**(风格包,animated 分支): 风格参考图组 + LoRA 权重文件 + 负面清单 + 调色 LUT
- **scene**(场景锚): 场景全景权威图 + 衍生机位裁切 + 空间标注(座次/门窗方位,供越轴检查)
- **voice**(独立声音资产): 旁白声线、臣光曰声线等非角色绑定声音

### 2.2 manifest.json 契约(identity 示例)

```json
{
  "pack_id": "identity/C001",
  "pack_type": "identity",
  "version": "2.1.0",
  "name": "智伯",
  "immutable_traits": "四十余岁,魁伟美髯,玄色深衣镶红边,束发玉冠",
  "era_lock": "战国早期服制",
  "files": {
    "refs/front.png": {"sha256": "9d2e...", "role": "canonical_portrait"},
    "refs/action_pose.png": {"sha256": "77af...", "role": "kinetic_ref"}
  },
  "embeddings": {"identity": {"model": "arcface-r100", "dim": 512}},
  "voice": {"tts_voice_id": "cosyvoice:c001_cloned"},
  "provenance": {
    "built_by_run": "run-uuid",
    "source_chapter": "周纪一",
    "gen_models": ["sdxl-1.0+ipadapter", "kling-3.0-turnaround"]
  },
  "stability_check": {"passed": true, "score": "3/3", "checked_at": "..."},
  "lifecycle": "published",
  "reuse_stats": {"runs_used": 17, "last_used": "..."}
}
```

---

## 3. 元数据 DDL

```sql
CREATE TABLE vault_packs (
  pack_id TEXT PRIMARY KEY,              -- identity/C001
  pack_type TEXT NOT NULL,               -- identity/style/scene/voice
  name TEXT NOT NULL,
  canonical_version TEXT,                -- 当前指针,如 '2.1.0'
  lifecycle TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE vault_versions (
  pack_id TEXT REFERENCES vault_packs,
  version TEXT NOT NULL,                 -- semver,不可变
  manifest JSONB NOT NULL,
  manifest_hash TEXT NOT NULL,           -- 整包指纹(全文件哈希的默克尔根)
  stability_passed BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (pack_id, version)
);

CREATE TABLE vault_files (
  sha256 TEXT PRIMARY KEY,               -- 即 MinIO 对象名
  bucket TEXT NOT NULL,
  bytes BIGINT,
  mime TEXT,
  ref_count INT DEFAULT 0                -- 被多少版本引用,GC 依据
);

CREATE TABLE vault_embeddings (
  pack_id TEXT, version TEXT,
  kind TEXT,                             -- identity/style
  embedding vector(512),
  PRIMARY KEY (pack_id, version, kind)
);
CREATE INDEX ON vault_embeddings USING hnsw (embedding vector_cosine_ops);

-- 平台绑定注册表(本设计的关键增量,见 §5)
CREATE TABLE vault_platform_bindings (
  pack_id TEXT, version TEXT,
  platform TEXT NOT NULL,                -- vidu/kling/seedance/...
  remote_ref_id TEXT NOT NULL,           -- Vidu My References 档案ID / Kling 元素ID
  remote_kind TEXT,                      -- reference_profile/element/...
  synced_files JSONB,                    -- 已上传文件哈希清单
  status TEXT DEFAULT 'active',          -- active/stale/revoked
  last_verified TIMESTAMPTZ,
  PRIMARY KEY (pack_id, version, platform)
);

-- 血缘:任何生成物记录其消费的资产版本
CREATE TABLE vault_lineage (
  derived_sha256 TEXT NOT NULL,          -- 产出物(clip/成片)
  run_id UUID, shot_id TEXT,
  pack_id TEXT, version TEXT,            -- 消费的资产
  PRIMARY KEY (derived_sha256, pack_id)
);
```

---

## 4. 版本化与生命周期

### 4.1 不可变版本 + canonical 指针

- 版本一经创建**永不修改**,任何变更(换权威像、重训声纹)产生新 semver 版本
- `canonical_version` 指针决定新 run 默认取哪个版本;**每个 run 在启动时把所消费的资产版本钉死写入 run 记录** → 断点续跑、重跑、审计的可复现性由此保证
- 语义约定:major = 形象重设(观众可感知换脸)/ minor = 参考集增补优化 / patch = 元数据修正

### 4.2 生命周期状态机

```
draft ──(稳定性预检 3 取 2 通过 + VLM 年代审通过)──▶ validated
validated ──(首次在正式 run 中过 CG6 门)──▶ published
published ──(major 新版本发布)──▶ superseded(旧版保留,历史 run 仍可复现)
任意态 ──(人工标记)──▶ deprecated(禁止新 run 引用)
```

稳定性预检(来自 SPEC-02 §11.2):同参考同 prompt 重生成 3 次,≥2 次通过身份门才允许 validated——防止把 outlier 当成合格资产入库。

### 4.3 GC 策略(按资产的"再生成本"分级)

| 资产类 | 策略 |
|---|---|
| identity/style/voice 包 | **永不 GC**(再生成本高且形象连续性不可再造) |
| scene 包 | LRU + ref_count=0 且 180 天未用 → 冷归档(移出 MinIO 热桶) |
| derived(中间 clip/draft 片) | run 完成 30 天后仅保留过审终版 clip 与成片,draft 遍产物删除(血缘表保留记录) |

---

## 5. 平台绑定注册表(远端资产驻留管理)

实证确认平台侧支持资产驻留(Vidu My References 可保存角色/道具/场景档案跨次复用,Kling 有元素机制),因此资产库必须管"一份本地权威资产,多个平台远端分身":

1. **懒同步**: oskill `asset_resolve(pack_id, platform)` 被 C6 调用时,查绑定表——有 active 绑定直接返回 remote_ref_id;无则自动上传参考集、创建远端档案、写入绑定
2. **失效检测**: 绑定记录 `synced_files` 哈希清单;资产出新 canonical 版本 → 对应绑定自动置 `stale`,下次使用触发重同步。每周巡检任务验证远端档案仍存在(平台可能清理),失联置 `revoked`
3. **本地权威原则**: 平台侧档案永远是缓存分身,truth 只在 vault。平台倒闭/换代/封号,资产零损失,换个平台重新懒同步即可——这是"不被任何单一模型厂商锁定"在资产层的落实
4. **路由加权**: C6 路由表将"该角色在该平台已有 active 绑定"作为加分项(省上传、历史良品率数据可查)

---

## 6. 接口(oskill 层)

```
asset_resolve(pack_id, platform?, style?) → refs[] + remote_ref_id?   # 生成端取用
asset_create(pack_type, source_run, files, manifest_draft) → draft 版本
asset_promote(pack_id, version)            # 触发稳定性预检 → validated
asset_verify(pack_id, version, frame)      # 门调用:embedding 距离 + 服装锁审
asset_search(embedding | text) → packs[]   # 查重与复用检索
asset_export(pack_id) / asset_import(tar)  # 整包迁移(目录+manifest 自足性保证)
```

血缘写入不走显式接口:orchestrator 在每次 `video_generate` 成功后自动落 `vault_lineage`。由此免费获得两个量产刚需查询:"智伯 3.0 形象改版会影响哪些已发布成片"(向前追);"这支成片用了哪些资产版本"(向后溯,内容审计)。

---

## 7. 备份与部署

- 部署: `hevi-vault`(MinIO)+ 既有 PostgreSQL 加 schema,Docker Compose 纳入 Aegis 纳管;MinIO 桶策略:热桶(NVMe)+ 冷归档桶
- 备份 3-2-1: PG 每日 pg_dump + MinIO `mc mirror` 增量同步至 VPS;identity/style 包(永不 GC 层)每月快照一份至云冷存储。**资产库是全项目最不可再生的数据,备份优先级高于代码仓**
- 磁盘预算: 每 identity 包约 80-150MB(含转身视频与多风格 renders);294 卷预估 400-600 个人物 → 60-90GB;scene 与 derived 热层预留 500GB,冷归档走 VPS

## 8. 实施切分

- **V-P0(与 C-P0 同步,1 周)**: MinIO + DDL + manifest schema + `asset_resolve/create/verify` 三接口 + 血缘落库——C-P0 首战直接踩在 vault 上跑,不做临时文件方案再迁移
- **V-P1**: 平台绑定注册表 + 懒同步 + 失效巡检;稳定性预检自动化;GC 任务
- **V-P2**: 查重检索(pgvector HNSW)、整包导入导出、跨项目接口通用化评估(下沉 3O)
