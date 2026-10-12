"""素材语料库 + 离线 CLIP 检索 —— 补 hevi 缺失的"真实素材剪辑"通道。

参考 OpenMontage corpus/clip_search:把免费来源(Archive.org Prelinger 公开域、
本地目录)的**真实运动片段**下载到项目本地语料库,抽帧 + CLIP 嵌入,之后
**离线向量检索**(不再重复打来源 API)。这是 hevi 画面来源的第三种路线:
程序化动画(freevideo)/ 本地生成(wan_local)/ **检索真实素材(本模块)**。

目录布局(与 OpenMontage 对齐):
    <corpus_dir>/
      clips/<clip_id>.<ext>      # 下载的真实片段
      thumbnails/<clip_id>/frame_00.jpg  # 每片段首帧(CLIP 嵌入用)
      index.jsonl                # 每行一条素材元数据(来源/查询/许可)
      embeddings.npy             # (N, 512) L2-归一化视觉嵌入,行序对齐 index

检索操作:
  - rank_for_slot(query)   : 文本描述场景槽 → top-k 片段(视觉嵌入 vs CLIP 文本嵌入)
  - find_similar_set(seed) : 一个种子片段 → MMR 多样性集合("所有门/所有脚步")
  - diversify(ids)         : 选中的片段集合 → 去视觉冗余(编排时)

成本: 下载流量(免费来源)+ 本地 CPU 嵌入。零 API 费用。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EMBED_DIM = 512

_clip_lock = threading.Lock()
_clip_model = None
_clip_preprocess = None
_clip_tokenizer = None

def _ensure_open_clip_model():
    global _clip_model, _clip_preprocess, _clip_tokenizer
    if _clip_model is not None:
        return _clip_model, _clip_preprocess, _clip_tokenizer
    
    with _clip_lock:
        if _clip_model is None:
            try:
                import open_clip
            except ImportError as e:
                raise RuntimeError(f"Missing deps for open_clip: {e}") from e
            
            local_dir = "/home/soffy/models/open_clip"
            model_bin = Path(local_dir) / "open_clip_model.safetensors"
            if not model_bin.exists():
                raise RuntimeError("open_clip weights not found, expecting open_clip_model.safetensors")
            
            logger.info("Loading open_clip ViT-B-32 (CPU)...")
            # Force CPU to avoid taking up GPU memory (as per spec)
            model, _, preprocess = open_clip.create_model_and_transforms('ViT-B-32', pretrained=str(model_bin), device='cpu')
            model.eval()
            _clip_model = model
            _clip_preprocess = preprocess
            _clip_tokenizer = open_clip.get_tokenizer('ViT-B-32')
            
    return _clip_model, _clip_preprocess, _clip_tokenizer


#: Archive.org 公开域电影档案(Prelinger 等 collection,免费无需 key)。
_ARCHIVE_SEARCH = "https://archive.org/advancedsearch.php"
_ARCHIVE_METADATA = "https://archive.org/metadata/{id}"
_ARCHIVE_DOWNLOAD = "https://archive.org/download/{id}/{file}"


@dataclass
class ClipRecord:
    """语料库一行:素材元数据(与 index.jsonl 对齐)。"""

    clip_id: str
    source: str  # archive_org | local | pexels
    source_id: str
    source_url: str
    local_path: str  # 相对 corpus_dir
    thumb_dir: str = ""
    query: str = ""
    title: str = ""
    kind: str = "video"
    license: str = ""
    degraded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "source": self.source,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "local_path": self.local_path,
            "thumb_dir": self.thumb_dir,
            "query": self.query,
            "title": self.title,
            "kind": self.kind,
            "license": self.license,
            "degraded": self.degraded,
        }



@dataclass
class Corpus:
    """项目本地素材语料库(下载 → 索引 → 离线检索)。"""

    root: Path
    records: list[ClipRecord] = field(default_factory=list)
    _embeddings: list[list[float]] = field(default_factory=list)

    # ── 持久化 ────────────────────────────────────────────────────────────

    def _clips_dir(self) -> Path:
        p = self.root / "clips"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _thumbs_dir(self) -> Path:
        p = self.root / "thumbnails"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "index.jsonl").write_text(
            "\n".join(json.dumps(r.to_dict(), ensure_ascii=False) for r in self.records),
            encoding="utf-8",
        )
        if self._embeddings:
            import numpy as np

            np.save(self.root / "embeddings.npy", np.asarray(self._embeddings, dtype=np.float32))

    @classmethod
    def load(cls, root: Path) -> Corpus:
        root = Path(root)
        corpus = cls(root=root)
        index = root / "index.jsonl"
        emb_file = root / "embeddings.npy"
        raw_embs: list[list[float]] = []
        if emb_file.exists():
            try:
                import numpy as np

                arr = np.load(emb_file)
                raw_embs = [row.tolist() for row in arr]
            except Exception as exc:
                logger.warning("语料库嵌入载入失败: %s", exc)

        if index.exists():
            seen: set[str] = set()
            clean_records: list[ClipRecord] = []
            clean_embs: list[list[float]] = []
            for i, line in enumerate(index.read_text(encoding="utf-8").splitlines()):
                if not line.strip():
                    continue
                rec = ClipRecord(**json.loads(line))
                if rec.clip_id in seen:
                    continue
                seen.add(rec.clip_id)
                clean_records.append(rec)
                if i < len(raw_embs):
                    clean_embs.append(raw_embs[i])
                else:
                    clean_embs.append([0.0] * EMBED_DIM)
            corpus.records = clean_records
            corpus._embeddings = clean_embs
        return corpus

    @property
    def size(self) -> int:
        return len(self.records)

    # ── 素材添加 ──────────────────────────────────────────────────────────

    def add_local_video(self, path: Path, *, title: str = "", query: str = "") -> ClipRecord:
        """把本地一段视频收录进语料库(复制 + 抽首帧 + 嵌入)。"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        clip_id = f"local_{uuid.uuid4().hex[:10]}"
        dest = self._clips_dir() / f"{clip_id}{path.suffix}"
        shutil.copy2(path, dest)
        rec = ClipRecord(
            clip_id=clip_id,
            source="local",
            source_id=path.stem,
            source_url=str(path),
            local_path=str(dest.relative_to(self.root)),
            query=query,
            title=title or path.stem,
            license="local",
        )
        self._index_record(rec)
        return rec

    async def add_archive_org(
        self,
        *,
        query: str,
        count: int = 3,
        max_clip_mb: int = 150,
        collection: str = "prelinger",
        client: httpx.AsyncClient | None = None,
    ) -> list[ClipRecord]:
        """从 Archive.org 检索并下载公开域/CC 影片(Prelinger 等),收录进语料库。

        零 API key(公开档案);下载流量是唯一成本。失败条目跳过不中断。
        """
        import os
        added: list[ClipRecord] = []
        own_client = client is None
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "http://127.0.0.1:7890"
        headers = {"User-Agent": "HeviResearchBot/1.0 (https://github.com/hevi-research; hevi@example.com)"}
        client = client or httpx.AsyncClient(proxy=proxy, headers=headers, timeout=60, follow_redirects=True)
        try:
            search_queries = [query]
            words = query.split()
            if len(words) > 2:
                search_queries.append(" ".join(words[:2]))
                search_queries.append(words[0])

            items = []
            for sq in search_queries:
                items = await _archive_search(
                    query=sq, count=count, collection=collection, client=client
                )
                if items:
                    break
            if not items and collection:
                for sq in search_queries:
                    items = await _archive_search(
                        query=sq, count=count, collection="", client=client
                    )
                    if items:
                        break

            for it in items:
                try:
                    rec = await self._download_archive_item(
                        it, client=client, max_clip_mb=max_clip_mb, query=query
                    )
                    if rec is not None:
                        added.append(rec)
                except Exception as exc:  # 单条失败不中断
                    logger.warning("archive.org 收录失败 %s: %s", it.get("identifier"), exc)
        finally:
            if own_client:
                await client.aclose()
        return added

    async def _download_archive_item(
        self, item: dict[str, Any], *, client: httpx.AsyncClient, max_clip_mb: int, query: str
    ) -> ClipRecord | None:
        ident = str(item["identifier"])
        meta = (await client.get(_ARCHIVE_METADATA.format(id=ident))).json()
        files = meta.get("files") or []
        # 扩展名匹配为主(Prelinger 的 MPEG4/h.264 格式名不统一),大小限制。
        video = next(
            (
                f
                for f in files
                if str(f.get("name", "")).lower().endswith((".mp4", ".m4v"))
                and not str(f.get("name", "")).lower().startswith(("thumbs", "thumb", "<"))
                and f.get("size") is not None
                and int(f["size"]) <= max_clip_mb * 1024 * 1024
            ),
            None,
        )
        if video is None:
            logger.info(
                "archive.org %s 无可下载 mp4(文件数=%d),跳过",
                ident,
                len(files),
            )
            return None
        clip_id = f"archive_{ident[:40]}"
        raw_dest = self._clips_dir() / f"{clip_id}_raw.mp4"
        dest = self._clips_dir() / f"{clip_id}.mp4"
        if not dest.exists() or dest.stat().st_size > 12 * 1024 * 1024:
            if not raw_dest.exists():
                if dest.exists() and dest.stat().st_size > 12 * 1024 * 1024:
                    dest.rename(raw_dest)
                else:
                    url = _ARCHIVE_DOWNLOAD.format(id=ident, file=video["name"])
                    resp = await client.get(url)
                    resp.raise_for_status()
                    raw_dest.write_bytes(resp.content)
            _extract_good_subclip(raw_dest, dest, target_duration=6.0)

        rec = ClipRecord(
            clip_id=clip_id,
            source="archive_org",
            source_id=ident,
            source_url=f"https://archive.org/details/{ident}",
            local_path=str(dest.relative_to(self.root)),
            query=query,
            title=str(item.get("title") or ident),
            license=str(meta.get("licenseurl") or "public-domain"),
        )
        self._index_record(rec)
        return rec

    async def add_nasa_api(self, *, query: str, count: int = 3, client=None) -> list[ClipRecord]:
        import os
        added = []
        own_client = client is None
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "http://127.0.0.1:7890"
        headers = {"User-Agent": "HeviResearchBot/1.0 (https://github.com/hevi-research; hevi@example.com)"}
        client = client or httpx.AsyncClient(proxy=proxy, headers=headers, timeout=60, follow_redirects=True)
        try:
            search_queries = [query]
            words = query.split()
            if len(words) > 2:
                search_queries.append(" ".join(words[:2]))
                search_queries.append(words[0])

            items = []
            for sq in search_queries:
                resp = await client.get("https://images-api.nasa.gov/search", params={"q": sq, "media_type": "video"})
                if resp.status_code == 200:
                    it_list = resp.json().get("collection", {}).get("items", [])
                    if it_list:
                        items = it_list[:count]
                        break

            for it in items:
                try:
                    data = it["data"][0]
                    nasa_id = data["nasa_id"]
                    title = data.get("title", nasa_id)
                    collection_url = it["href"]
                    col_resp = await client.get(collection_url)
                    col_resp.raise_for_status()
                    mp4s = [u for u in col_resp.json() if str(u).endswith(".mp4")]
                    if not mp4s:
                        continue
                    medium_mp4s = [u for u in mp4s if "~medium.mp4" in u] or [u for u in mp4s if "~small.mp4" in u]
                    video_url = medium_mp4s[0] if medium_mp4s else mp4s[-1]
                    clip_id = f"nasa_{nasa_id[:40]}"
                    raw_dest = self._clips_dir() / f"{clip_id}_raw.mp4"
                    dest = self._clips_dir() / f"{clip_id}.mp4"
                    if not dest.exists():
                        if not raw_dest.exists():
                            head_resp = await client.head(video_url)
                            clen = int(head_resp.headers.get("content-length", 0))
                            if clen > 80 * 1024 * 1024:
                                continue
                            dl_resp = await client.get(video_url)
                            dl_resp.raise_for_status()
                            raw_dest.write_bytes(dl_resp.content)
                        _extract_good_subclip(raw_dest, dest, target_duration=6.0)

                    rec = ClipRecord(
                        clip_id=clip_id,
                        source="nasa",
                        source_id=nasa_id,
                        source_url=video_url,
                        local_path=str(dest.relative_to(self.root)),
                        query=query,
                        title=title,
                        license="public-domain",
                    )
                    self._index_record(rec)
                    added.append(rec)
                except Exception as exc:
                    logger.warning("NASA api fail %s", exc)
        finally:
            if own_client:
                await client.aclose()
        return added

    async def add_wikimedia_commons(self, *, query: str, count: int = 3, client=None) -> list[ClipRecord]:
        import os
        added = []
        own_client = client is None
        proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or "http://127.0.0.1:7890"
        headers = {
            "User-Agent": "CoolMediaBot/1.0 (https://github.com/hevi-research; hevi-research@gmail.com) httpx/0.27.0",
            "Referer": "https://commons.wikimedia.org/",
        }
        client = client or httpx.AsyncClient(proxy=proxy, headers=headers, timeout=60, follow_redirects=True)
        try:
            search_queries = [query]
            words = query.split()
            if len(words) > 2:
                search_queries.append(" ".join(words[:2]))
                search_queries.append(words[0])

            pages = []
            for sq in search_queries:
                params = {
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrsearch": f"{sq} filetype:video",
                    "gsrnamespace": 6,
                    "gsrlimit": count,
                    "prop": "imageinfo",
                    "iiprop": "url|mime|extmetadata",
                }
                resp = await client.get("https://commons.wikimedia.org/w/api.php", params=params)
                if resp.status_code == 200:
                    p_dict = resp.json().get("query", {}).get("pages", {})
                    if p_dict:
                        pages = list(p_dict.values())
                        break

            for p in pages:
                try:
                    ii = p.get("imageinfo", [{}])[0]
                    video_url = ii.get("url")
                    if not video_url:
                        continue
                    mime = ii.get("mime", "")
                    clean_url = video_url.split("?")[0]
                    if not (mime.startswith("video/") or clean_url.lower().endswith((".webm", ".ogv", ".mp4", ".mkv"))):
                        continue
                    title = p.get("title", "")
                    clip_id = f"wiki_{p.get('pageid', '')}"
                    raw_ext = Path(clean_url).suffix or ".webm"
                    raw_dest = self._clips_dir() / f"{clip_id}_raw{raw_ext}"
                    dest = self._clips_dir() / f"{clip_id}.mp4"
                    if not dest.exists():
                        if not raw_dest.exists():
                            dl_resp = await client.get(video_url)
                            dl_resp.raise_for_status()
                            raw_dest.write_bytes(dl_resp.content)
                        _extract_good_subclip(raw_dest, dest, target_duration=6.0)

                    ext = ii.get("extmetadata", {})
                    lic = ext.get("LicenseShortName", {}).get("value", "cc-by-sa")
                    rec = ClipRecord(
                        clip_id=clip_id,
                        source="wikimedia",
                        source_id=str(p.get("pageid")),
                        source_url=video_url,
                        local_path=str(dest.relative_to(self.root)),
                        query=query,
                        title=title,
                        license=lic,
                    )
                    self._index_record(rec)
                    added.append(rec)
                except Exception as exc:
                    logger.warning("wiki api fail %s", exc)
        finally:
            if own_client:
                await client.aclose()
        return added

    async def add_pexels(self, *, query: str, count: int = 3, api_key: str = "", client=None) -> list[ClipRecord]:
        added = []
        if not api_key:
            api_key = os.environ.get("PEXELS_API_KEY", "")
        if not api_key:
            for env_path in [Path(".env"), Path("/data/soffy/projects/hevi/.env")]:
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        if line.startswith("PEXELS_API_KEY="):
                            api_key = line.split("=", 1)[1].strip()
                            os.environ["PEXELS_API_KEY"] = api_key
                            break
                if api_key:
                    break
        if not api_key:
            return added
        client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            resp = await client.get(
                "https://api.pexels.com/videos/search", 
                params={"query": query, "per_page": count},
                headers={"Authorization": api_key}
            )
            resp.raise_for_status()
            items = resp.json().get("videos", [])
            for v in items:
                try:
                    vid = str(v["id"])
                    title = v.get("url", vid)
                    files = sorted(v.get("video_files", []), key=lambda x: -x.get("width", 0))
                    if not files:
                        continue
                    video_url = files[0]["link"]
                    clip_id = f"pexels_{vid}"
                    raw_dest = self._clips_dir() / f"{clip_id}_raw.mp4"
                    dest = self._clips_dir() / f"{clip_id}.mp4"
                    if not dest.exists():
                        if not raw_dest.exists():
                            dl_resp = await client.get(video_url)
                            dl_resp.raise_for_status()
                            raw_dest.write_bytes(dl_resp.content)
                        _extract_good_subclip(raw_dest, dest, target_duration=6.0)
                    rec = ClipRecord(
                        clip_id=clip_id, source="pexels", source_id=vid,
                        source_url=v.get("url", video_url), local_path=str(dest.relative_to(self.root)),
                        query=query, title=title, license="pexels"
                    )
                    self._index_record(rec)
                    added.append(rec)
                except Exception as exc:
                    logger.warning("pexels api fail %s", exc)
        finally:
            pass
        return added

    def _index_record(self, rec: ClipRecord) -> None:
        """收录:校验片段 → 抽首帧 + CLIP 嵌入 + 记录追加。

        缓存里的子片段若是空壳/截断文件（如只有 moov 头的 707 字节 mp4），先用 *_raw.mp4
        重新截取；仍无效则拒收（抛 ValueError），绝不把坏文件收进语料。
        """
        clip_path = Path(self.root) / rec.local_path
        if not _valid_video(clip_path):
            raw = clip_path.with_name(clip_path.stem + "_raw.mp4")
            if raw.exists() and _valid_video(raw):
                logger.warning("clip %s 缓存子片段无效，从 raw 重新截取", rec.clip_id)
                clip_path.unlink(missing_ok=True)
                _extract_good_subclip(raw, clip_path, target_duration=6.0)
            if not _valid_video(clip_path):
                raise ValueError(f"invalid clip file for {rec.clip_id}: {clip_path}")
        existing_idx = None
        for i, existing in enumerate(self.records):
            if existing.clip_id == rec.clip_id:
                existing_idx = i
                self.records[i] = rec
                break
        if existing_idx is None:
            self.records.append(rec)
            existing_idx = len(self.records) - 1

        thumb_dir = self._thumbs_dir() / rec.clip_id
        thumb_dir.mkdir(parents=True, exist_ok=True)
        frame = thumb_dir / "frame_00.jpg"
        emb: list[float] | None = None
        frame = _extract_first_frame(Path(self.root) / rec.local_path, frame)
        if frame.exists():
            try:
                import torch
                from PIL import Image

                model, preprocess, _ = _ensure_open_clip_model()
                img = Image.open(frame).convert("RGB")
                img_tensor = preprocess(img).unsqueeze(0)
                with torch.no_grad():
                    feats = model.encode_image(img_tensor)
                    feats /= feats.norm(dim=-1, keepdim=True)
                emb = feats[0].tolist()
                rec.degraded = False
            except Exception as exc:  # 嵌入失败不影响收录
                logger.warning("clip %s 嵌入失败: %s", rec.clip_id, exc)
                rec.degraded = True
        else:
            rec.degraded = True

        if emb is None:
            # 允许在受限测试/无模型环境下回退，但明确记录 degraded
            rec.degraded = True
            logger.warning("CLIP embedding failed for %s, degraded mode enabled", rec.clip_id)
            emb = [0.0] * EMBED_DIM

        if existing_idx < len(self._embeddings):
            self._embeddings[existing_idx] = emb
        else:
            self._embeddings.append(emb)
        rec.thumb_dir = str(thumb_dir.relative_to(self.root))


    # ── 检索 ──────────────────────────────────────────────────────────────

    def _clip_emb(self, clip_id: str) -> list[float] | None:
        for i, r in enumerate(self.records):
            if r.clip_id == clip_id:
                if i < len(self._embeddings):
                    return self._embeddings[i]
                return None
        return None

    def _text_emb(self, text: str) -> list[float]:
        """CLIP 文本嵌入(懒加载;失败返回零向量,检索退化为顺序打分)。

        CLIP 是英文训练的 —— 中文 query 先经本地 ollama 免费翻译成英文,
        否则中英不对齐导致所有槽分数趋同。翻译失败降级原文本。
        """
        query_en = _to_english(text) if _contains_cjk(text) else text
        try:
            import torch

            model, _, tokenizer = _ensure_open_clip_model()

            text_tokens = tokenizer([query_en])
            with torch.no_grad():
                feats = model.encode_text(text_tokens)
                feats /= feats.norm(dim=-1, keepdim=True)
            v = feats[0]
            norm = float(v.norm())
            if norm == 0.0:
                return [0.0] * EMBED_DIM
            return list(v.tolist())
        except Exception as exc:
            logger.warning("CLIP 文本嵌入失败,检索退化为文本命中: %s", exc)
            return [0.0] * EMBED_DIM


    @staticmethod
    def _cos(a: list[float], b: list[float]) -> float:
        if len(a) != EMBED_DIM or len(b) != EMBED_DIM:
            return 0.0
        return sum(x * y for x, y in zip(a, b, strict=False))

    def rank_for_slot(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        """场景槽文本 → top-k 片段(视觉嵌入 vs CLIP 文本嵌入,余弦)。"""
        if not self.records:
            return []
        t = self._text_emb(query)
        scored: list[tuple[float, int]] = []
        for i, rec in enumerate(self.records):
            v = self._embeddings[i] if i < len(self._embeddings) else []
            score = self._cos(t, v)
            # 文本命中加权(标题/查询词里的词面重叠)
            if rec.title and any(k.lower() in rec.title.lower() for k in query.split()[:2]):
                score += 0.1
            scored.append((score, i))
        scored.sort(key=lambda x: -x[0])
        results: list[dict[str, Any]] = []
        seen_clip_ids: set[str] = set()
        for s, i in scored:
            rec = self.records[i]
            if rec.clip_id in seen_clip_ids:
                continue
            seen_clip_ids.add(rec.clip_id)
            results.append({
                **rec.to_dict(),
                "score": round(float(s), 4),
            })
            if len(results) >= top_k:
                break
        return results

    def find_similar_set(self, seed_clip_id: str, *, count: int = 4) -> list[dict[str, Any]]:
        """一个种子片段 → MMR 多样性集合(与种子相似但彼此不同)。"""
        seed = self._clip_emb(seed_clip_id)
        if seed is None:
            return []
        rest = [(i, r) for i, r in enumerate(self.records) if r.clip_id != seed_clip_id]
        if not rest:
            return []
        rest.sort(key=lambda ir: -self._cos(seed, self._embeddings[ir[0]]))
        picked: list[int] = []
        remaining = rest[: max(count * 4, count)]
        while remaining and len(picked) < count:
            # MMR:与种子相似 - λ × 与已选集合最大相似度
            if not picked:
                best_idx = 0
            else:
                best_idx = max(
                    range(len(remaining)),
                    key=lambda k: (
                        self._cos(seed, self._embeddings[remaining[k][0]])
                        - 0.5
                        * max(
                            (
                                self._cos(self._embeddings[remaining[k][0]], self._embeddings[j])
                                for j in picked
                            ),
                            default=0.0,
                        )
                    ),
                )
            i, _rec = remaining.pop(best_idx)
            picked.append(i)
        return [
            {
                **self.records[i].to_dict(),
                "score": round(float(self._cos(seed, self._embeddings[i])), 4),
            }
            for i in picked
        ]

    def diversify(self, clip_ids: list[str]) -> list[str]:
        """选中的片段集合 → 贪心去视觉冗余(保留与已选集合最不同的)。"""
        if len(clip_ids) <= 1:
            return clip_ids
        picked: list[str] = []
        remaining = list(clip_ids)
        while remaining and len(picked) < len(clip_ids):
            if not picked:
                picked.append(remaining.pop(0))
                continue
            best = max(
                remaining,
                key=lambda cid: min(
                    (self._cos(self._clip_emb(cid) or [], self._clip_emb(p) or []) for p in picked),
                    default=0.0,
                ),
            )
            picked.append(best)
            remaining.remove(best)
        return picked

    # ── 消费入口 ──────────────────────────────────────────────────────────

    def best_for_slot(
        self,
        query: str,
        *,
        min_score: float | None = None,
        exclude_clip_ids: set[str] | None = None,
    ) -> dict[str, Any] | None:
        """freevideo B-roll 消费入口:场景槽 → 最佳片段(本地路径)。支持去重排除已选 clip_id 与相似度阈值。"""
        hits = self.rank_for_slot(query, top_k=max(len(self.records), 50))
        if not hits:
            return None

        # 选满足排除条件且相似度达到 min_score 阈值的候选（低于阈值换下一个候选）
        for cand in hits:
            if exclude_clip_ids and cand.get("clip_id") in exclude_clip_ids:
                continue
            if min_score is not None and float(cand.get("score", 0.0)) < min_score:
                continue
            local = Path(self.root) / cand["local_path"]
            if local.exists() and local.stat().st_size > 0:
                hit = dict(cand)
                hit["local_abs_path"] = str(local)
                return hit

        return None


# ── 辅助 ──────────────────────────────────────────────────────────────────


async def _archive_search(
    *, query: str, count: int, collection: str, client: httpx.AsyncClient
) -> list[dict[str, Any]]:
    """Archive.org advancedsearch:collection 内按 query 检影片条目。"""
    if collection:
        q = f"collection:{collection} AND ({query}) AND mediatype:movies"
    else:
        q = f"({query}) AND mediatype:movies"
    resp = await client.get(
        _ARCHIVE_SEARCH,
        params={"q": q, "fl[]": ["identifier", "title"], "rows": count, "output": "json"},
    )
    resp.raise_for_status()
    docs = (resp.json().get("response") or {}).get("docs") or []
    return [{"identifier": d.get("identifier"), "title": d.get("title")} for d in docs]


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _to_english(text: str, *, timeout_s: float = 30.0) -> str:
    """本地 ollama(qwen3-8b)把中文槽描述翻译成英文(零成本)。

    失败返回原文(调用方退化)。翻译成功但为空同样回退。
    """
    try:
        import json as _json
        import urllib.request

        prompt = (
            "Translate the following Chinese video-scene description to English. "
            "Output ONLY the translation, no explanation.\n\n" + text
        )
        body = _json.dumps({"model": "qwen3-8b", "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            out = _json.loads(resp.read().decode("utf-8")).get("response", "")
        out = out.strip().splitlines()[-1].strip() if out.strip() else text
        return out if out else text
    except Exception:
        return text


def _valid_video(path: Path, min_bytes: int = 20 * 1024, min_duration: float = 1.0) -> bool:
    """文件存在、够大、能解码出 ≥min_duration 秒的视频流。"""
    try:
        if not path.exists() or path.stat().st_size < min_bytes:
            return False
        out = subprocess.run(
            [shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name:format=duration", "-of", "default=nw=1", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout
        if "codec_name=" not in out:
            return False
        m = re.search(r"duration=([0-9.]+)", out)
        return bool(m) and float(m.group(1)) >= min_duration
    except Exception:
        return False


def _extract_good_subclip(src_video: Path, out_video: Path, target_duration: float = 6.0) -> None:
    """使用 PySceneDetect 与亮度/运动变化筛选优质动态 b-roll，剔除黑帧与静态片头片尾卡。"""
    import cv2
    import numpy as np
    from scenedetect import ContentDetector, SceneManager, open_video

    src_str = str(src_video)
    out_str = str(out_video)
    best_segment: tuple[float, float] | None = None

    # 尝试加载 CLIP 用于字卡语义比对
    title_tokens = None
    clip_model = None
    clip_preprocess = None
    try:
        clip_model, clip_preprocess, clip_tok = _ensure_open_clip_model()
        import torch
        with torch.no_grad():
            t_tok = clip_tok(["a movie opening title card with text, company logo, opening credits"])
            title_tokens = clip_model.encode_text(t_tok)
            title_tokens /= title_tokens.norm(dim=-1, keepdim=True)
    except Exception:
        pass

    try:
        # 扫描前 180 秒（老电影片头通常长达数十秒）
        video = open_video(src_str)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=27.0))
        scene_manager.detect_scenes(video, frame_skip=3, duration=180.0)
        scenes = scene_manager.get_scene_list()

        cap = cv2.VideoCapture(src_str)
        # 超过 1 个场景时跳过 scene 0（通常为片头卡/Logo）
        candidate_scenes = scenes[1:] if len(scenes) > 1 else scenes

        for s in candidate_scenes:
            start_s = s[0].seconds
            end_s = s[1].seconds
            dur = end_s - start_s
            if dur < target_duration * 0.7:
                continue

            times = np.linspace(start_s + 0.5, min(start_s + target_duration, end_s) - 0.5, 5)
            frames = []
            rgb_frames = []
            for t in times:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ret, f = cap.read()
                if ret:
                    frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
                    rgb_frames.append(f)
            if len(frames) < 3:
                continue

            b_mean = float(np.mean([np.mean(f) for f in frames]))
            min_b = float(np.min([np.mean(f) for f in frames]))
            if b_mean < 25.0 or min_b < 18.0:  # 黑帧或过渡暗场
                continue

            diffs = [np.mean(cv2.absdiff(frames[i], frames[i + 1])) for i in range(len(frames) - 1)]
            m_mean = float(np.mean(diffs)) if diffs else 0.0
            if m_mean < 1.8:  # 静态图片/字幕卡/画面无明显动态
                continue

            # 字卡检测：单帧极暗或极亮底色卡片
            text_card = any(float((f < 45).mean()) > 0.80 or float((f > 215).mean()) > 0.80 for f in frames)
            if text_card:
                continue

            # CLIP title card 语义检测
            if title_tokens is not None and clip_model is not None and clip_preprocess is not None and rgb_frames:
                try:
                    import torch
                    from PIL import Image
                    mid_img = Image.fromarray(cv2.cvtColor(rgb_frames[len(rgb_frames) // 2], cv2.COLOR_BGR2RGB))
                    img_tensor = clip_preprocess(mid_img).unsqueeze(0)
                    with torch.no_grad():
                        im_feat = clip_model.encode_image(img_tensor)
                        im_feat /= im_feat.norm(dim=-1, keepdim=True)
                        sim = float((im_feat @ title_tokens.T)[0, 0].item())
                    if sim > 0.22:
                        continue  # 判定为字卡或 Logo
                except Exception:
                    pass

            best_segment = (start_s, min(start_s + target_duration, end_s))
            break

        # 若场景检测未匹配到满足质量的片段，滑动扫描不同时间窗（避开片头）
        if not best_segment:
            for cand_start in [60.0, 75.0, 90.0, 110.0, 45.0, 30.0, 15.0]:
                times = np.linspace(cand_start + 0.5, cand_start + target_duration - 0.5, 5)
                frames = []
                rgb_frames = []
                for t in times:
                    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                    ret, f = cap.read()
                    if ret:
                        frames.append(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
                        rgb_frames.append(f)
                if len(frames) < 3:
                    continue
                b_mean = float(np.mean([np.mean(f) for f in frames]))
                min_b = float(np.min([np.mean(f) for f in frames]))
                diffs = [np.mean(cv2.absdiff(frames[i], frames[i + 1])) for i in range(len(frames) - 1)]
                m_mean = float(np.mean(diffs)) if diffs else 0.0
                text_card = any(float((f < 45).mean()) > 0.80 or float((f > 215).mean()) > 0.80 for f in frames)
                if b_mean >= 25.0 and min_b >= 18.0 and m_mean >= 1.8 and not text_card:
                    if title_tokens is not None and clip_model is not None and clip_preprocess is not None and rgb_frames:
                        try:
                            import torch
                            from PIL import Image
                            mid_img = Image.fromarray(cv2.cvtColor(rgb_frames[len(rgb_frames) // 2], cv2.COLOR_BGR2RGB))
                            img_tensor = clip_preprocess(mid_img).unsqueeze(0)
                            with torch.no_grad():
                                im_feat = clip_model.encode_image(img_tensor)
                                im_feat /= im_feat.norm(dim=-1, keepdim=True)
                                sim = float((im_feat @ title_tokens.T)[0, 0].item())
                            if sim > 0.22:
                                continue
                        except Exception:
                            pass
                    best_segment = (cand_start, cand_start + target_duration)
                    break

        cap.release()
    except Exception as exc:
        logger.warning("Scene detection failed for %s: %s", src_video, exc)

    if not best_segment:
        # 降级：从 15 秒处截取目标时长（避开 0-10 秒最常见的片头）
        best_segment = (15.0, 15.0 + target_duration)

    start, end = best_segment
    cmd = [
        "/home/soffy/.local/bin/ffmpeg",
        "-y",
        "-ss",
        str(start),
        "-i",
        src_str,
        "-t",
        str(end - start),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        out_str,
    ]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0 or not out_video.exists() or out_video.stat().st_size == 0:
        # 若失败，直接转码原视频
        fallback_cmd = [
            "/home/soffy/.local/bin/ffmpeg",
            "-y",
            "-ss",
            "15.0",
            "-i",
            src_str,
            "-t",
            str(target_duration),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            out_str,
        ]
        subprocess.run(fallback_cmd, capture_output=True, check=True)


def _extract_first_frame(video: Path, out: Path) -> Path:
    """ffmpeg 抽代表帧(取片段中间位置，多点采样避开黑帧)。"""
    import cv2

    for ss in ["2.5", "3.0", "1.5", "3.5", "4.0", "0.5"]:
        try:
            subprocess.run(
                [
                    "/home/soffy/.local/bin/ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    ss,
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    str(out),
                ],
                capture_output=True,
                timeout=30,
            )
            if out.exists() and out.stat().st_size > 0:
                f = cv2.imread(str(out), cv2.IMREAD_GRAYSCALE)
                if f is not None and float(f.mean()) >= 25.0:
                    return out
        except (OSError, subprocess.TimeoutExpired):
            pass

    return out  # 降级返回实际产出文件


def _score_text_hits(rec: ClipRecord, query: str) -> float:
    """词面命中打分(CLIP 文本嵌入不可用时的退化检索)。"""
    score = 0.0
    q = query.lower()
    if q in (rec.title or "").lower():
        score += 0.8
    for kw in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z]{3,}", q):
        if kw in (rec.title or "").lower():
            score += 0.3
    return score


__all__ = [
    "ClipRecord",
    "Corpus",
]
