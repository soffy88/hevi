"""End-to-end substrate ingestion pipeline."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb as _duckdb
from oprim._logging import log
from oprim.classifier.detect_mime import detect_mime
from oprim.embedding import embed_text
from oprim.errors import IngestError, MetaDBError
from oprim.fulltext import open_fulltext_index
from oprim.fulltext.tantivy import FulltextDoc
from oprim.meta_db import open_meta_db
from oprim.vector_db import open_vector_db
from oprim.vector_db.lancedb import VectorRecord
from ulid import ULID

from oskill.knowledge._context import (
    lancedb_path,
    meta_db_path,
    substrate_data_path,
    tantivy_path,
)
from oskill.knowledge.classify_inbox_file import classify_inbox_file
from oskill.knowledge.detect_duplicate_substrate import detect_duplicate_substrate
from oskill.knowledge.generate_derivative import generate_derivative

_VECTOR_DIM = 1024
_VECTOR_TABLE = "vectors_text"
_CHUNK_SIZE = 512


@dataclass
class IngestResult:
    substrate_id: str
    medium: str
    derivatives: list[str] = field(default_factory=list)
    duplicate_of: str | None = None
    elapsed_seconds: float = 0.0
    cost_usd: float = 0.0


async def _detect_bundle_duplicate(bundle_file_hash: str, user_id_hash: str) -> int:
    """检测同一 bundle_file_hash 是否已有衍生项入库（D-assert 用）。
    返回已有记录数，0 表示首次入库。
    """
    try:
        db_p = meta_db_path()
        if not db_p.exists():
            return 0
        db = open_meta_db(db_p)
        rows = db.execute(
            """SELECT COUNT(*) FROM substrates
               WHERE user_id = ?
               AND json_extract(meta_json, '$.bundle_file_hash') = ?""",
            [user_id_hash, bundle_file_hash],
        ).fetchone()
        return int(rows[0]) if rows else 0
    except Exception as e:
        log.warning("D-assert._detect_bundle_duplicate failed", error=str(e))
        return 0


async def ingest_substrate(
    path: Path,
    source: dict,
    user_id_hash: str,
    target_storage: str = "local",
    user_hint: dict | None = None,
    content_override: str | None = None,
    metadata_override: dict | None = None,
) -> IngestResult:
    """End-to-end ingestion: classify → deduplicate → parse → embed → index.

    Args:
        content_override: 直接使用此内容作为 markdown（跳过文件解析）。
            用于 EPUB 套装拆分，每本书传入 book.content，不重新解析原文件。
        metadata_override: 覆盖 meta_db 中的元数据字段（如 title/author）。
    """
    if target_storage != "local":
        raise IngestError(
            f"target_storage '{target_storage}' not supported in Phase 1 (only 'local')"
        )

    t0 = time.monotonic()
    if not path.exists():
        raise FileNotFoundError(str(path))

    # Step 1: sha256
    file_hash = _sha256(path)

    # Step 2: deduplicate (skip when content_override: bundle books share the same source file)
    if content_override is None:
        existing = await detect_duplicate_substrate(file_hash)
        if existing:
            log.info("oskill.ingest.duplicate", path=str(path), existing=existing)
            return IngestResult(
                substrate_id=existing,
                medium="",
                duplicate_of=existing,
                elapsed_seconds=time.monotonic() - t0,
            )
    else:
        # D-assert: bundle 衍生项入口去重（WARN 模式，不阻断）
        # bundle 单本 file_hash=NULL，三道信号盲区在此兜底
        _bundle_file_hash = (metadata_override or {}).get("bundle_file_hash")
        if _bundle_file_hash:
            _dup_count = await _detect_bundle_duplicate(_bundle_file_hash, user_id_hash)
            if _dup_count > 0:
                log.warning(
                    "D-assert: bundle dup via non-folder path",
                    bundle_file_hash=_bundle_file_hash[:16],
                    user_id_hash=user_id_hash,
                    dup_count=_dup_count,
                )
                # 计数 +1（可观测，不阻断）
                # Owner 裁定阻断时改为 return IngestResult(duplicate_of=...)

    # Step 3: classify
    hint = user_hint or {}
    use_llm = hint.pop("use_llm", False)
    classify_result = classify_inbox_file(path, use_llm=use_llm)
    medium = classify_result.medium or "other"

    # Step 4: ULID
    substrate_id = str(ULID())

    # Step 5: copy to local storage
    dest_dir = substrate_data_path() / medium
    dest_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(path.stem)[:40]
    dest = dest_dir / f"{substrate_id}--{slug}{path.suffix}"
    shutil.copy2(path, dest)

    # Step 6: generate derivatives
    if content_override is not None:
        derivatives_dict = {"markdown": content_override, "plaintext": None, "chapters": None}
        markdown_text = content_override
    else:
        derivatives_dict = await generate_derivative(substrate_id, dest, medium)
        markdown_text = derivatives_dict.get("markdown", "")

    # Step 7: chunk + embed
    chunks = _chunk_text(markdown_text)
    if chunks:
        try:
            from oprim._config import cfg

            _emb_provider = str(cfg.get("EMBEDDING_PROVIDER", "qwen3_dashscope"))
            embeddings = embed_text(
                [c for c in chunks],
                provider=_emb_provider,
                dim=_VECTOR_DIM,
            )
            vdb_path = lancedb_path()
            vdb_path.mkdir(parents=True, exist_ok=True)
            vdb = open_vector_db(vdb_path, table_name=_VECTOR_TABLE, dim=_VECTOR_DIM)
            records = [
                VectorRecord(
                    id=f"{substrate_id}#{i}",
                    embedding=emb,
                    metadata={"substrate_id": substrate_id, "chunk_idx": i},
                )
                for i, emb in enumerate(embeddings)
            ]
            vdb.upsert(records)
            [r.id for r in records]
        except Exception as e:
            log.warning("oskill.ingest.embed_failed", error=str(e))

    # Step 8: write fulltext index
    try:
        ft_path = tantivy_path()
        ft_path.mkdir(parents=True, exist_ok=True)
        ft_idx = open_fulltext_index(ft_path)
        ft_idx.add(
            [
                FulltextDoc(
                    id=substrate_id,
                    fields={
                        "title": path.stem,
                        "content": (markdown_text or "")[:10_000],
                    },
                )
            ]
        )
    except Exception as e:
        log.warning("oskill.ingest.fulltext_failed", error=str(e))

    # Step 9: write meta_db
    db_p = meta_db_path()
    db_p.parent.mkdir(parents=True, exist_ok=True)
    path_mime = detect_mime(path)
    try:
        db = open_meta_db(db_p)
        now = datetime.now(UTC).isoformat()
        _meta_extra = metadata_override or {}
        _meta_dict = {
            "medium": medium,
            "source_type": source.get("type", "inbox_local"),
            "source": source,
            **_meta_extra,
        }
        meta = json.dumps(_meta_dict, ensure_ascii=False)
        title = _meta_extra.get("book_title") or _meta_extra.get("title") or path.stem
        db.execute(
            """INSERT INTO substrates
               (id, user_id, title, mime, source_path, file_hash, byte_size, meta_json,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                substrate_id,
                user_id_hash,
                title,
                path_mime or None,
                str(dest),
                file_hash if content_override is None else None,
                path.stat().st_size,
                meta,
                now,
                now,
            ],
        )
        for deriv_kind, deriv_content in derivatives_dict.items():
            deriv_id = str(ULID())
            if deriv_content is not None:
                # Write content for both bundle books (content_override path) and
                # normal books where generate_derivative returned non-null content.
                db.execute(
                    "INSERT INTO derivative (id, substrate_id, kind, content) VALUES (?,?,?,?)",
                    [deriv_id, substrate_id, deriv_kind, deriv_content],
                )
            else:
                db.execute(
                    "INSERT INTO derivative (id, substrate_id, kind) VALUES (?,?,?)",
                    [deriv_id, substrate_id, deriv_kind],
                )
        # Step 10: changefeed_local
        db.execute(
            """INSERT INTO changefeed_local (seq, table_name, row_id, op, payload)
               VALUES (nextval('changefeed_seq'),?,?,?,?)""",
            ["substrate", substrate_id, "insert", json.dumps({"substrate_id": substrate_id})],
        )
        db.close()
    except MetaDBError as e:
        if isinstance(e.__cause__, _duckdb.BinderException):
            log.error("oskill.ingest.schema_mismatch", error=str(e))
            raise
        if isinstance(e.__cause__, _duckdb.ConnectionException):
            log.warning("oskill.ingest.db_unavailable", error=str(e))
        else:
            log.error("oskill.ingest.meta_db_failed", error=str(e))
            raise

    elapsed = time.monotonic() - t0
    log.info("oskill.ingest.done", substrate_id=substrate_id, medium=medium, elapsed=elapsed)
    return IngestResult(
        substrate_id=substrate_id,
        medium=medium,
        derivatives=list(derivatives_dict.keys()),
        elapsed_seconds=elapsed,
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _chunk_text(text: str, size: int = _CHUNK_SIZE) -> list[str]:
    """Simple paragraph-based chunker."""
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= size:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            current = para[:size]
    if current:
        chunks.append(current)
    return chunks
