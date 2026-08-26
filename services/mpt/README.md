# MoneyPrinterTurbo - hevi 集成版

## 集成策略

根据 hevi 架构分析（见 `docs/COMPETITIVE-GAP.md`），**hevi 无法完整内化 MPT 的整条能力线**：
- ❌ 免费素材搜索/下载
- ❌ 参考视频分析
- ❌ 一键发布闭环
- ❌ Streamlit WebUI
- ❌ LLM 网关聚合

因此采用 **fork + 容器化** 方案：MPT 作为 hevi 的**外壳服务**运行，共享 hevi 基础设施。

## 架构

```
┌─────────────────┐     ┌─────────────────┐
│  hevi-frontend  │     │  mpt-webui      │
│  (Next.js)      │     │  (Streamlit)    │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────┐
│         hevi-api (FastAPI)               │
└─────────────────────────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
┌────────┐    ┌──────────┐    ┌────────┐
│Postgres│    │  MinIO   │    │ Redis  │
│(vault) │    │ (vault)  │    │        │
└────────┘    └──────────┘    └────────┘
```

## 启动

```bash
# 单独启动 MPT
docker compose -f docker-compose.mpt.yml up -d

# 或作为 hevi 栈一部分
docker compose -f docker-compose.yml -f docker-compose.mpt.yml up -d
```

## 配置

`config.toml` 已预置共享基础设施连接：
- PostgreSQL: `postgres:5432/hevi_vault`
- MinIO: `minio:9000`
- Redis: `redis:6379`

## 数据流向

1. 用户通过 hevi-web (Next.js) 或直接访问 mpt-webui (Streamlit)
2. MPT 生成视频后，推送到 hevi-api 进行质检/约束评估
3. hevi-api 返回评估结果，MPT 决定是否发布
4. 共享 Postgres/MinIO/Redis 保证数据一致性

## 后续内化路线

优先级（按用户感知度）：
1. **素材搜索 API** → 新增 `hevi/services/material.py`（对接 Pexels/Pixabay）
2. **参考视频分析** → 新增 `hevi/services/reference_video.py`（转录/节奏/场景）
3. **发布闭环** → 增强 `hevi/publishers/` 调用 MPT 的 upload_post
4. **WebUI 集成** → hevi-web 新增 MPT 面板路由

