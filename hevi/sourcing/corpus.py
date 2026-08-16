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
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EMBED_DIM = 512

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
        if index.exists():
            corpus.records = [
                ClipRecord(**json.loads(line))
                for line in index.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        emb_file = root / "embeddings.npy"
        if emb_file.exists():
            import numpy as np

            arr = np.load(emb_file)
            corpus._embeddings = [row.tolist() for row in arr]
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
        max_clip_mb: int = 60,
        collection: str = "prelinger",
        client: httpx.AsyncClient | None = None,
    ) -> list[ClipRecord]:
        """从 Archive.org 检索并下载公开域/CC 影片(Prelinger 等),收录进语料库。

        零 API key(公开档案);下载流量是唯一成本。失败条目跳过不中断。
        """
        added: list[ClipRecord] = []
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
        try:
            items = await _archive_search(
                query=query, count=count, collection=collection, client=client
            )
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
                f for f in files
                if str(f.get("name", "")).lower().endswith((".mp4", ".m4v"))
                and not str(f.get("name", "")).lower().startswith(("thumbs", "thumb", "\u003c"))
                and f.get("size") is not None
                and int(f["size"]) <= max_clip_mb * 1024 * 1024
            ),
            None,
        )
        if video is None:
            logger.info(
                "archive.org %s 无可下载 mp4(文件数=%d),跳过",
                ident, len(files),
            )
            return None
        clip_id = f"archive_{ident[:40]}"
        dest = self._clips_dir() / f"{clip_id}.mp4"
        if not dest.exists():
            url = _ARCHIVE_DOWNLOAD.format(id=ident, file=video["name"])
            resp = await client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
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

    def _index_record(self, rec: ClipRecord) -> None:
        """收录:抽首帧 + CLIP 嵌入 + 记录追加。嵌入失败降级为零向量(检索仍可用文本侧)。"""
        self.records.append(rec)
        thumb_dir = self._thumbs_dir() / rec.clip_id
        thumb_dir.mkdir(parents=True, exist_ok=True)
        frame = thumb_dir / "frame_00.jpg"
        emb: list[float] | None = None
        if not frame.exists():
            frame = _extract_first_frame(Path(self.root) / rec.local_path, frame)
        if frame.exists():
            try:
                from hevi.subjects.subject_embed import subject_embed

                emb = subject_embed(image_path=frame, kind="style")
            except Exception as exc:  # 嵌入失败不影响收录
                logger.warning("clip %s 嵌入失败: %s", rec.clip_id, exc)
        self._embeddings.append(emb or [0.0] * EMBED_DIM)
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
            from hevi.subjects.subject_embed import _ensure_model

            model, processor = _ensure_model()
            import torch

            with torch.no_grad():
                feats = model.get_text_features(
                    **processor(text=[query_en], return_tensors="pt")
                )
            v = feats[0]
            norm = float(v.norm())
            if norm == 0.0:
                return [0.0] * EMBED_DIM
            return list((v / norm).tolist())
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
            if rec.title and any(k in rec.title for k in query.split()[:2]):
                score += 0.1
            scored.append((score, i))
        scored.sort(key=lambda x: -x[0])
        return [
            {
                **self.records[i].to_dict(),
                "score": round(float(s), 4),
            }
            for s, i in scored[:top_k]
        ]

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
                    key=lambda k: self._cos(seed, self._embeddings[remaining[k][0]])
                    - 0.5
                    * max(
                        (
                            self._cos(self._embeddings[remaining[k][0]], self._embeddings[j])
                            for j in picked
                        ),
                        default=0.0,
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

    def best_for_slot(self, query: str) -> dict[str, Any] | None:
        """freevideo B-roll 消费入口:场景槽 → 最佳片段(本地路径)。"""
        hits = self.rank_for_slot(query, top_k=1)
        if not hits:
            return None
        hit = hits[0]
        local = Path(self.root) / hit["local_path"]
        if not local.exists():
            return None
        hit["local_abs_path"] = str(local)
        return hit


# ── 辅助 ──────────────────────────────────────────────────────────────────


async def _archive_search(
    *, query: str, count: int, collection: str, client: httpx.AsyncClient
) -> list[dict[str, Any]]:
    """Archive.org advancedsearch:collection 内按 query 检影片条目。"""
    q = f'collection:{collection} AND ({query}) AND mediatype:movies'
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
        body = _json.dumps(
            {"model": "qwen3-8b", "prompt": prompt, "stream": False}
        ).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            out = _json.loads(resp.read().decode("utf-8")).get("response", "")
        out = out.strip().splitlines()[-1].strip() if out.strip() else text
        return out if out else text
    except Exception:
        return text


def _extract_first_frame(video: Path, out: Path) -> Path:
    """ffmpeg 抽首帧(失败返回不存在路径,调用方降级)。"""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", "0.5", "-i", str(video),
             "-frames:v", "1", str(out)],
            capture_output=True, timeout=60,
        )
        if out.exists() and out.stat().st_size > 0:
            return out
    except (OSError, subprocess.TimeoutExpired):
        pass
    return out  # 不存在 → 调用方检查 exists


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
