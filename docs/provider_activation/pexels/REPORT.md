# Pexels — Provider Activation Report

**Status:** `VERIFIED` ✅
**9 段验收链:** 全部 PASS
**Activated at:** 2026-09-04T01:50+00:00

## 9 段真实验收链证据

| # | 段位 | 状态 | 证据 |
|---|---|---|---|
| 1 | credential/config | ✅ PASS | `01_credential_status.json` — `configured:true`, `missing:[]` |
| 2 | readiness probe | ✅ PASS | `02_probe_status.json` — `reachable:true`, `http_status:200` (query=hevi) |
| 3 | real submit (image) | ✅ PASS | `03_resolve_image.log` — `media_cli resolve --type image` 真实 HTTP 调用 |
| 4 | ACK / job_id (image) | ✅ PASS | photos[] len>0, asset_id=1819660 |
| 5 | real artifact (image) | ✅ PASS | `artifacts/pexels_image_aurora.jpg` 真实 JPEG 1551×1300, 165414 B |
| 5' | real submit (video) | ✅ PASS | `04_resolve_video.log` — `media_cli resolve --type video` |
| 4' | ACK / job_id (video) | ✅ PASS | asset_id=8438341, duration_s=16 |
| 5'' | real artifact (video) | ✅ PASS | `artifacts/pexels_video_waves.mp4` 真实 MP4 1080×1920, 5.3 MB |
| 6 | local freeze | ✅ PASS | `data/material_cache/<sha20>.{jpg,mp4}` + 同名 `.source.json` |
| 7 | provenance | ✅ PASS | source manifest 完整字段: provider, asset_id, source_page, photographer, sha256, mime, size, downloaded_at |
| 8 | evaluation | ✅ PASS | `08_evaluation_readiness.json` — `status:READY`, `artifact_ready:true`, `provider_job_id:pexels:1819660` |
| 9 | billing/usage | ✅ PASS | `09_billing_usage.json` — 3 calls / 5.9 MB frozen, free Pexels License |

## 真实产物 (落到 `artifacts/`)

- `pexels_image_aurora.jpg` — Tobias Bjørkli, Pexels #1819660, "snow mountain night sky" (165 KB)
- `pexels_video_waves.mp4` — RDNE Stock, Pexels #8438341, "birds-eye crashing waves" (5.3 MB, 16s)
- 各自 `.source.json` 旁挂

## 主题选型理由

- **图片:** `northern lights aurora over snow mountain` — 风景类 Pexels 命中率高,构图干净, 版权清晰
- **视频:** `ocean waves crashing on rocks 16:9` — 自然动态素材, HEVI stock 链路多源 (Pexels/Pixabay/Coverr/Archive) 平行回退

## 总账影响

- `EXTERNAL PROVIDER TRACK` 计数: 1/8 → **2/8 verified** (Wan/local, Pexels)
- `HEVI V1.0 CORE` = VERIFIED (不变)
- `HEVI FRONTEND` = READY (不变)
- `HEVI CODE BLOCKERS` = 0 (不变)
- `FULL ALL-PROVIDER SYSTEM` = NOT YET VERIFIED (待剩 6 个 Provider 跑完)

## 下一步

按优先序，下一个 Provider: **LongCat**。
同样需要 9 段链 + 真实凭证。
阻塞原因: `LONGCAT_BASE_URL` + `LONGCAT_API_KEY` 均为空。
