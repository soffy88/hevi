"""Translate a substrate's markdown content and store as a derivative."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import oprim.meta_db as _oprim_meta_db_mod
from oprim._logging import log
from oprim.embedding import embed_text
from oprim.errors import StratumError
from oprim.meta_db import open_meta_db
from oprim.translate import TerminologyGlossary, TranslationResult, translate_document_async
from oprim.vector_db import open_vector_db
from oprim.vector_db.lancedb import VectorRecord
from ulid import ULID

from oskill.knowledge._context import lancedb_path, meta_db_path

_MIGRATIONS_DIR = Path(_oprim_meta_db_mod.__file__).parent / "migrations"
_VECTOR_DIM = 1024
_VECTOR_TABLE = "vectors_text"
_CHUNK_SIZE = 512


@dataclass
class TranslateResult:
    derivative_id: str
    substrate_id: str
    target_lang: str
    provider: str
    chunks_translated: int
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    cost_usd: float = 0.0
    embedding_ids: list[str] = field(default_factory=list)
    chunk_results: list[TranslationResult] = field(default_factory=list)


async def translate_substrate(
    substrate_id: str,
    target_lang: str,
    source_lang: str = "auto",
    provider: str = "deepseek",
    *,
    model: str | None = None,
    domain: str | None = None,
    max_chars: int = 2000,
    checkpoint_dir: Path | None = None,
    glossary: TerminologyGlossary | None = None,
    overwrite: bool = False,
    embed_translation: bool = True,
) -> TranslateResult:
    """Translate a substrate's markdown content into target_lang.

    Reads the substrate's markdown derivative (falling back to source_path for
    plain-text files), translates via the chosen provider, writes a new derivative
    row with ``kind = "translation_<target_lang>"``, and optionally embeds the
    translated text into the shared vector index so cross-language queries work.

    Args:
        substrate_id: ID of the substrate to translate.
        target_lang: ISO language code for the translation target (e.g. "zh", "en").
        source_lang: ISO language code for the source, or "auto" to let the provider detect.
        provider: Translation provider name ("deepseek", "claude", "qwen3").
        model: Optional model override for the provider.
        domain: Optional domain hint ("academic", "literary", "technical").
        max_chars: Max characters per translation chunk.
        checkpoint_dir: Directory for checkpoint files (enables resumable translation).
        glossary: Optional TerminologyGlossary for domain-specific terms.
        overwrite: If True, replace an existing translation derivative.
        embed_translation: If True (default), embed translated text into the shared
            vector index alongside the original, enabling cross-language retrieval.

    Returns:
        TranslateResult with derivative_id, cost summary, and embedding IDs.

    Raises:
        StratumError: Substrate not found, no translatable content, or DB error.
    """
    db_path = meta_db_path()
    if not db_path.exists():
        raise StratumError(f"MetaDB not found at {db_path}")

    db = open_meta_db(db_path)
    db.migrate(_MIGRATIONS_DIR)

    rows = db.execute(
        "SELECT id, source_path, meta_json FROM substrates WHERE id = ?",
        [substrate_id],
    ).fetchall()
    if not rows:
        db.close()
        raise StratumError(f"Substrate not found: {substrate_id}")

    _id, source_path, meta_json_str = rows[0]

    derivative_kind = f"translation_{target_lang}"
    if not overwrite:
        existing = db.execute(
            "SELECT id FROM derivative WHERE substrate_id = ? AND kind = ?",
            [substrate_id, derivative_kind],
        ).fetchall()
        if existing:
            db.close()
            existing_id = existing[0][0]
            log.info(
                "translate_substrate.already_exists",
                derivative_id=existing_id,
                substrate_id=substrate_id,
                kind=derivative_kind,
            )
            return TranslateResult(
                derivative_id=existing_id,
                substrate_id=substrate_id,
                target_lang=target_lang,
                provider=provider,
                chunks_translated=0,
            )

    markdown_rows = db.execute(
        "SELECT content FROM derivative WHERE substrate_id = ? AND kind = 'markdown' LIMIT 1",
        [substrate_id],
    ).fetchall()

    if markdown_rows and markdown_rows[0][0]:
        source_text: str = markdown_rows[0][0]
    elif source_path and Path(source_path).exists():
        source_text = Path(source_path).read_text(encoding="utf-8", errors="replace")
    else:
        db.close()
        raise StratumError(
            f"No translatable content for substrate {substrate_id}: "
            "no markdown derivative and source_path not accessible"
        )

    effective_source = "auto" if source_lang == "auto" else source_lang

    checkpoint_path: Path | None = None
    if checkpoint_dir:
        checkpoint_dir = Path(checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / f"{substrate_id}_{target_lang}.json"

    log.info(
        "translate_substrate.start",
        substrate_id=substrate_id,
        target_lang=target_lang,
        provider=provider,
        chars=len(source_text),
        embed=embed_translation,
    )

    translated_text, chunk_results = await translate_document_async(
        source_text,
        source_lang=effective_source,
        target_lang=target_lang,
        provider=provider,
        checkpoint_path=checkpoint_path,
        max_chars=max_chars,
        domain=domain,
        model=model,
        glossary=glossary,
    )

    total_in = sum(r.input_tokens for r in chunk_results)
    total_out = sum(r.output_tokens for r in chunk_results)
    total_cost = sum(r.cost_usd for r in chunk_results)

    derivative_id = str(ULID())
    now = datetime.now(UTC).isoformat()
    meta = json.dumps(
        {
            "source_lang": effective_source,
            "target_lang": target_lang,
            "provider": provider,
            "chunks": len(chunk_results),
            "cost_usd": round(total_cost, 6),
            "embed_translation": embed_translation,
        }
    )

    if overwrite:
        db.execute(
            "DELETE FROM derivative WHERE substrate_id = ? AND kind = ?",
            [substrate_id, derivative_kind],
        )

    db.execute(
        """INSERT INTO derivative (id, substrate_id, kind, content, meta_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [derivative_id, substrate_id, derivative_kind, translated_text, meta, now],
    )
    db.execute(
        """INSERT INTO changefeed_local (seq, table_name, row_id, op, payload)
           VALUES (nextval('changefeed_seq'), ?, ?, ?, ?)""",
        [
            "derivative",
            derivative_id,
            "insert",
            json.dumps(
                {
                    "substrate_id": substrate_id,
                    "kind": derivative_kind,
                    "derivative_id": derivative_id,
                }
            ),
        ],
    )
    db.close()

    # Embed translation so cross-language queries hit this derivative
    embedding_ids: list[str] = []
    if embed_translation:
        embedding_ids = _embed_translation(derivative_id, translated_text)

    log.info(
        "translate_substrate.done",
        derivative_id=derivative_id,
        substrate_id=substrate_id,
        target_lang=target_lang,
        provider=provider,
        chunks=len(chunk_results),
        cost_usd=round(total_cost, 6),
        embedding_vectors=len(embedding_ids),
    )

    return TranslateResult(
        derivative_id=derivative_id,
        substrate_id=substrate_id,
        target_lang=target_lang,
        provider=provider,
        chunks_translated=len(chunk_results),
        total_tokens_in=total_in,
        total_tokens_out=total_out,
        cost_usd=total_cost,
        embedding_ids=embedding_ids,
        chunk_results=chunk_results,
    )


def _embed_translation(derivative_id: str, text: str) -> list[str]:
    """Chunk and embed translated text into the shared vector index.

    Failures are logged but do not abort the translate_substrate call —
    the derivative was already written successfully.
    """
    try:
        words = text.split()
        # Split into ~_CHUNK_SIZE-word chunks
        raw_chunks: list[str] = []
        for i in range(0, len(words), _CHUNK_SIZE):
            chunk = " ".join(words[i : i + _CHUNK_SIZE])
            if chunk.strip():
                raw_chunks.append(chunk)

        if not raw_chunks:
            return []

        from oprim._config import cfg

        _emb_provider = str(cfg.get("EMBEDDING_PROVIDER", "qwen3_dashscope"))
        embeddings = embed_text(raw_chunks, provider=_emb_provider, dim=_VECTOR_DIM)
        vdb_path = lancedb_path()
        vdb_path.mkdir(parents=True, exist_ok=True)
        vdb = open_vector_db(vdb_path, table_name=_VECTOR_TABLE, dim=_VECTOR_DIM)
        records = [
            VectorRecord(
                id=f"{derivative_id}#{i}",
                embedding=emb,
                metadata={"derivative_id": derivative_id, "chunk_idx": i},
            )
            for i, emb in enumerate(embeddings)
        ]
        vdb.upsert(records)
        ids = [r.id for r in records]
        log.info(
            "translate_substrate.embed_done",
            derivative_id=derivative_id,
            vectors=len(ids),
        )
        return ids
    except Exception as e:
        log.error(
            "translate_substrate.embed_failed",
            derivative_id=derivative_id,
            error=str(e),
        )
        return []
