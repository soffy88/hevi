"""Asynchronous review queue for the canvas (ChatGPT via local2 MCP).

Rendering never waits for a reviewer.  After a node finished and the
deterministic offline rules wrote their verdict, the node is appended to
``canvas_review_queue`` as ``pending``.  A remote reviewer claims it
(``claimed``) and submits a verdict (``done``); unreviewed rows expire after
24 hours.  A claim lease makes an abandoned claim available again without
losing the item's original 24h lifetime.

``HEVI_REVIEW_CHATGPT`` defaults to ``1``: the queue is on.  Offline rules
always run first and their verdict is never replaced by the remote reviewer;
the remote verdict is stored beside it.  ``HEVI_REVIEW_CHATGPT=0`` disables the
queue entirely (offline rules only).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import re
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from obase.persistence import PgPool

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_CLAIMED = "claimed"
STATUS_DONE = "done"
STATUS_EXPIRED = "expired"

VERDICTS = ("pass", "fail")
_ITEM_TTL_S = 24 * 3600
_CLAIM_LEASE_S = 30 * 60
_THUMB_TTL_S = 15 * 60
_MAX_THUMBS = 6
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_AUTO_REDO_TASKS: set[asyncio.Task[Any]] = set()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def chatgpt_enabled() -> bool:
    raw = os.getenv("HEVI_REVIEW_CHATGPT", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def review_providers() -> list[str]:
    providers = ["offline_rules"]
    if chatgpt_enabled():
        providers.append("chatgpt_queue")
    return providers


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    return str(value)


# ── thumbnail collection ─────────────────────────────────────────────────────

def _valid_image(path: str | Path) -> str | None:
    p = Path(str(path)).expanduser()
    try:
        if not p.is_file() or p.stat().st_size <= 0 or p.stat().st_size > 20 * 1024 * 1024:
            return None
    except OSError:
        return None
    if p.suffix.lower() not in _IMAGE_SUFFIXES:
        return None
    return str(p)


def _extract_video_frames(path: Path, out_dir: Path, count: int = 3) -> list[str]:
    """Grab representative frames without a provider call (ffmpeg only)."""
    import shutil

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return []
    duration = 5.0
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, timeout=30, check=False,
        )
        duration = float(proc.stdout.decode().strip() or duration)
    except Exception:
        pass
    out_dir.mkdir(parents=True, exist_ok=True)
    frames: list[str] = []
    for index in range(count):
        frac = (index + 1) / (count + 1)
        target = out_dir / f"{path.stem}_{index + 1}_{int(time.time() * 1000)}.jpg"
        proc = subprocess.run(
            [ffmpeg, "-y", "-ss", f"{max(0.0, duration * frac):.3f}", "-i", str(path),
             "-frames:v", "1", "-vf", "scale=480:-1", str(target)],
            capture_output=True, timeout=90, check=False,
        )
        if proc.returncode == 0 and target.is_file():
            frames.append(str(target))
    return frames


def collect_thumbnails(
    node: dict[str, Any],
    output: Any,
    review: dict[str, Any] | None,
) -> list[str]:
    """3-6 representative images, or fewer when the node has no visuals."""
    cfg = node.get("config") or {}
    review = review or {}
    signals = review.get("signals") or {}
    found: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            valid = _valid_image(value)
            if valid:
                found.append(valid)
        elif isinstance(value, (list, tuple)):
            for item in value:
                add(item)

    add(cfg.get("review_thumbnails"))
    add(cfg.get("thumbnails"))
    add(signals.get("contact_sheet"))
    out = output if isinstance(output, dict) else {}
    artifacts = out.get("artifacts")
    if isinstance(artifacts, list):
        for item in artifacts:
            if isinstance(item, dict) and str(item.get("kind") or "") == "image":
                add(item.get("path"))
            elif isinstance(item, str):
                add(item)
    if out.get("image"):
        add(out.get("image"))
    if out.get("output") and str(out.get("type") or "") == "image":
        add(out.get("output"))

    if len(found) < _MAX_THUMBS:
        video = None
        for key in ("output", "video", "mp4", "path"):
            value = out.get(key)
            if isinstance(value, str) and Path(value).suffix.lower() in (".mp4", ".mov", ".webm", ".mkv"):
                video = Path(value)
                break
        if video is not None and video.is_file():
            cache = Path(os.getenv("HEVI_REVIEW_THUMB_DIR", "output/canvas/review_thumbs"))
            try:
                found.extend(_extract_video_frames(video, cache, count=3))
            except Exception as exc:
                logger.warning("review thumbnails: frame extraction failed: %s", exc)

    unique: list[str] = []
    for path in found:
        if path not in unique:
            unique.append(path)
        if len(unique) >= _MAX_THUMBS:
            break
    return unique


# ── signed read-only thumbnail links ─────────────────────────────────────────

def _sign_secret() -> bytes:
    raw = os.getenv("HEVI_REVIEW_SIGN_SECRET", "").strip()
    if not raw:
        try:
            from hevi.core.config import settings

            raw = str(getattr(settings, "jwt_secret", "") or "")
        except Exception:
            raw = ""
    if not raw:
        raw = "hevi-review-local-development"
    return raw.encode("utf-8")


def make_thumb_token(item_id: str, index: int, expiry: int) -> str:
    payload = f"{item_id}:{index}:{expiry}".encode()
    sig = hmac.new(_sign_secret(), payload, hashlib.sha256).hexdigest()[:40]
    return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + sig


def verify_thumb_token(token: str) -> tuple[str, int] | None:
    try:
        encoded, sig = token.split(".", 1)
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = base64.urlsafe_b64decode(padded.encode()).decode()
        item_id, index, expiry = payload.rsplit(":", 2)
        expected = hmac.new(
            _sign_secret(), payload.encode(), hashlib.sha256
        ).hexdigest()[:40]
        if not hmac.compare_digest(sig, expected):
            return None
        if int(expiry) < int(time.time()):
            return None
        return item_id, int(index)
    except Exception:
        return None


def public_base_url() -> str:
    return os.getenv("HEVI_REVIEW_PUBLIC_BASE_URL", "https://hevi.kanpan.co").rstrip("/")


def thumbnail_urls(item_id: str, thumbnails: list[str]) -> list[dict[str, str]]:
    expiry = int(time.time()) + _THUMB_TTL_S
    urls: list[dict[str, str]] = []
    for index, path in enumerate(thumbnails[:_MAX_THUMBS]):
        token = make_thumb_token(str(item_id), index, expiry)
        urls.append(
            {
                "index": str(index),
                "file": Path(path).name,
                "url": f"{public_base_url()}/api/canvas/review/thumb/{token}",
                "expires_in_s": str(_THUMB_TTL_S),
            }
        )
    return urls


# ── queue operations ─────────────────────────────────────────────────────────

async def enqueue_for_node(
    pool: PgPool,
    *,
    graph_id: str,
    node_key: str,
    node_type: str,
    sentence_text: str,
    output: Any,
    review: dict[str, Any] | None,
    node_config: dict[str, Any] | None = None,
) -> str | None:
    """Append one pending review item (idempotent per node revision result)."""
    if not chatgpt_enabled():
        return None
    now = _now()
    item_id = uuid.uuid4()
    node = {"config": dict(node_config or {}), "node_type": node_type}
    thumbs = collect_thumbnails(node, output, review)
    payload_review = _jsonable(review or {})
    sentence = str(sentence_text or "")[:6000]
    try:
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT id FROM canvas_review_queue WHERE graph_id=$1 AND node_id=$2 "
                "AND status IN ('pending','claimed') AND sentence_text=$3 "
                "AND offline_review = $4::jsonb LIMIT 1",
                uuid.UUID(str(graph_id)), node_key, sentence, payload_review,
            )
            if existing is not None:
                return str(existing)
            await conn.execute(
                "INSERT INTO canvas_review_queue "
                "(id, graph_id, node_id, node_type, sentence_text, thumbnails, "
                "offline_review, status, expires_at, created_at, updated_at) "
                "VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,'pending',$8,$9,$9)",
                item_id, uuid.UUID(str(graph_id)), node_key, node_type, sentence,
                _jsonable(thumbs), payload_review, now + timedelta(seconds=_ITEM_TTL_S), now,
            )
            await conn.execute(
                "UPDATE canvas_nodes SET review = COALESCE(review,'{}'::jsonb) || $3::jsonb, "
                "updated_at=$4 WHERE graph_id=$1 AND node_key=$2",
                uuid.UUID(str(graph_id)), node_key,
                {
                    "review_sources": review_providers(),
                    "chatgpt": {
                        "status": "pending",
                        "item_id": str(item_id),
                        "queued_at": now.isoformat() + "Z",
                    },
                },
                now,
            )
    except Exception:
        logger.exception("canvas review queue: enqueue failed for %s/%s", graph_id, node_key)
        return None
    return str(item_id)


async def _expire(conn: Any, now: datetime) -> None:
    await conn.execute(
        "UPDATE canvas_review_queue SET status='expired', updated_at=$1 "
        "WHERE status IN ('pending','claimed') AND expires_at < $1",
        now,
    )
    await conn.execute(
        "UPDATE canvas_review_queue SET status='pending', claimed_at=NULL, "
        "lease_expires_at=NULL, updated_at=$1 "
        "WHERE status='claimed' AND lease_expires_at IS NOT NULL AND lease_expires_at < $1 "
        "AND expires_at >= $1",
        now,
    )


async def claim(pool: PgPool, limit: int = 3) -> list[dict[str, Any]]:
    limit = max(1, min(3, int(limit or 3)))
    now = _now()
    async with pool.acquire() as conn, conn.transaction():
        await _expire(conn, now)
        rows = await conn.fetch(
            "WITH picked AS ("
            "  SELECT id FROM canvas_review_queue WHERE status='pending' AND expires_at >= $1 "
            "  ORDER BY created_at LIMIT $2 FOR UPDATE SKIP LOCKED"
            ") UPDATE canvas_review_queue q SET status='claimed', claimed_at=$1, "
            "lease_expires_at=$3, updated_at=$1 FROM picked WHERE q.id=picked.id "
            "RETURNING q.*",
            now, limit, now + timedelta(seconds=_CLAIM_LEASE_S),
        )
        claimed = [dict(row) for row in rows]
    items: list[dict[str, Any]] = []
    for row in claimed:
        thumbs = list(row.get("thumbnails") or [])
        items.append(
            {
                "item_id": str(row["id"]),
                "graph_id": str(row["graph_id"]),
                "node_id": str(row["node_id"]),
                "node_type": str(row["node_type"]),
                "sentence_text": str(row.get("sentence_text") or ""),
                "offline_review": row.get("offline_review") or {},
                "images": thumbnail_urls(row["id"], thumbs),
                "image_count": len(thumbs),
                "created_at": str(row.get("created_at") or ""),
                "expires_at": str(row.get("expires_at") or ""),
                "lease_expires_at": str(row.get("lease_expires_at") or ""),
            }
        )
    return items

async def queue_status(pool: PgPool) -> dict[str, Any]:
    now = _now()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _expire(conn, now)
        rows = await conn.fetch(
            "SELECT status, count(*) AS n FROM canvas_review_queue GROUP BY status"
        )
        counts = {str(r["status"]): int(r["n"]) for r in rows}
        oldest = await conn.fetchval(
            "SELECT min(created_at) FROM canvas_review_queue WHERE status='pending'"
        )
    return {
        "provider": "chatgpt_queue" if chatgpt_enabled() else "offline_rules",
        "chatgpt_queue_enabled": chatgpt_enabled(),
        "counts": {
            "pending": counts.get(STATUS_PENDING, 0),
            "claimed": counts.get(STATUS_CLAIMED, 0),
            "done": counts.get(STATUS_DONE, 0),
            "expired": counts.get(STATUS_EXPIRED, 0),
        },
        "total": sum(counts.values()),
        "oldest_pending_at": str(oldest) if oldest else None,
        "item_ttl_s": _ITEM_TTL_S,
        "claim_lease_s": _CLAIM_LEASE_S,
    }


def _clean_list(value: Any, *, field: str, max_items: int, max_len: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field} must contain only strings")
        text = item.strip()
        if not text:
            continue
        if len(text) > max_len:
            raise ValueError(f"{field} entry longer than {max_len} characters")
        result.append(text)
        if len(result) > max_items:
            raise ValueError(f"{field} has more than {max_items} entries")
    return result


async def submit(
    pool: PgPool,
    *,
    item_id: str,
    verdict: str,
    issues: Any = None,
    redo_nodes: Any = None,
    reason: Any = "",
) -> dict[str, Any]:
    """Strictly validated write-back of one review verdict."""
    try:
        item_uuid = uuid.UUID(str(item_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("item_id must be a UUID") from exc
    verdict = str(verdict or "").strip().lower()
    if verdict not in VERDICTS:
        raise ValueError("verdict must be exactly 'pass' or 'fail'")
    issue_list = _clean_list(issues, field="issues", max_items=12, max_len=600)
    redo_list = _clean_list(redo_nodes, field="redo_nodes", max_items=10, max_len=255)
    reason_text = str(reason or "").strip()
    if len(reason_text) > 2000:
        raise ValueError("reason longer than 2000 characters")
    if verdict == "fail" and not reason_text:
        raise ValueError("reason is required when verdict is 'fail'")

    now = _now()
    async with pool.acquire() as conn, conn.transaction():
        await _expire(conn, now)
        row = await conn.fetchrow(
            "SELECT * FROM canvas_review_queue WHERE id=$1 FOR UPDATE", item_uuid
        )
        if row is None:
            raise LookupError("review item not found")
        status = str(row["status"])
        if status == STATUS_DONE:
            raise ValueError("review item already submitted")
        if status != STATUS_CLAIMED:
            raise ValueError(
                f"review item is {status}; claim it with hevi_review_next before submitting"
            )
        graph_uuid = row["graph_id"]
        node_key = str(row["node_id"])
        existing_nodes = {
            str(r["node_key"])
            for r in await conn.fetch(
                "SELECT node_key FROM canvas_nodes WHERE graph_id=$1 AND deleted_at IS NULL",
                graph_uuid,
            )
        }
        rejected = [key for key in redo_list if key not in existing_nodes]
        accepted_redo = [key for key in redo_list if key in existing_nodes]
        if verdict == "fail" and not accepted_redo:
            accepted_redo = [node_key]
        result = {
            "verdict": verdict,
            "issues": issue_list,
            "redo_nodes": accepted_redo,
            "rejected_redo_nodes": rejected,
            "reason": reason_text,
            "reviewed_at": now.isoformat() + "Z",
        }
        await conn.execute(
            "UPDATE canvas_review_queue SET status='done', result=$2::jsonb, "
            "submitted_at=$3, updated_at=$3 WHERE id=$1",
            item_uuid, result, now,
        )

        node_row = await conn.fetchrow(
            "SELECT review, locked FROM canvas_nodes WHERE graph_id=$1 AND node_key=$2 "
            "AND deleted_at IS NULL",
            graph_uuid, node_key,
        )
        if node_row is None:
            raise LookupError("reviewed node no longer exists")
        previous = node_row["review"] if isinstance(node_row["review"], dict) else {}
        offline_result = str(previous.get("result") or "pass")
        # Deterministic hard checks are never overridden by a remote pass; the
        # free-LLM text reviewer's warn/fail is advisory, so ChatGPT's pass wins.
        offline_mode = str(previous.get("review_mode") or "deterministic")
        offline_hard_fail = offline_result == "fail" and offline_mode in (
            "deterministic", "offline_rules"
        )
        if verdict == "fail" or offline_hard_fail:
            final_result = "fail"
        elif verdict == "pass":
            final_result = "pass"
        else:
            final_result = offline_result
        reasons = list(previous.get("reasons") or [])
        reasons.extend(f"[ChatGPT] {issue}" for issue in issue_list)
        if verdict == "fail" and not issue_list:
            reasons.append(f"[ChatGPT] {reason_text}")
        review = {
            **previous,
            "result": final_result,
            "reasons": reasons[:20],
            "review_sources": review_providers(),
            "chatgpt": {
                "status": "done" if verdict == "pass" else "fail",
                "verdict": verdict,
                "issues": issue_list,
                "redo_nodes": accepted_redo,
                "reason": reason_text,
                "item_id": str(item_uuid),
                "reviewed_at": now.isoformat() + "Z",
            },
        }
        if final_result == "pass":
            node_status = "ok"
        elif final_result == "fail":
            node_status = "needs_redo"
        else:
            node_status = "warn"
        await conn.execute(
            "UPDATE canvas_nodes SET status=$3, review=$4::jsonb, updated_at=$5 "
            "WHERE graph_id=$1 AND node_key=$2",
            graph_uuid, node_key, node_status, review, now,
        )
        if accepted_redo:
            await conn.execute(
                "UPDATE canvas_nodes SET status='needs_redo', updated_at=$3 "
                "WHERE graph_id=$1 AND node_key=ANY($2::text[]) AND locked=false "
                "AND deleted_at IS NULL",
                graph_uuid, accepted_redo, now,
            )
        prior_fail = await conn.fetchval(
            "SELECT count(*) FROM canvas_review_queue WHERE graph_id=$1 AND node_id=$2 "
            "AND status='done' AND result->>'verdict'='fail' AND id<>$3",
            graph_uuid, node_key, item_uuid,
        )
    auto_redo = verdict == "fail" and int(prior_fail or 0) == 0 and not bool(node_row["locked"])
    if auto_redo:
        _schedule_auto_redo(str(graph_uuid), node_key)
    return {
        "item_id": str(item_uuid),
        "status": "done",
        "verdict": verdict,
        "node_id": node_key,
        "node_status": node_status,
        "final_result": final_result,
        "redo_nodes": accepted_redo,
        "rejected_redo_nodes": rejected,
        "auto_redo_scheduled": auto_redo,
        "auto_redo_limit": 1,
    }


def _schedule_auto_redo(graph_id: str, node_key: str) -> None:
    """One automatic local rerun of the failed node; never a second one."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("auto redo %s/%s skipped: no running loop", graph_id, node_key)
        return
    task = loop.create_task(_auto_redo(graph_id, node_key))
    _AUTO_REDO_TASKS.add(task)
    task.add_done_callback(_AUTO_REDO_TASKS.discard)


async def _auto_redo(graph_id: str, node_key: str) -> None:
    try:
        from hevi.canvas.executor_service import ExecutorService
        from hevi.canvas.graph_repository import GraphRepository
        from hevi.canvas.graph_service import GraphService
        from hevi.canvas.node_store import PgNodeStore
        from hevi.db.pg_pool import get_hevi_pg_pool

        pool = await get_hevi_pg_pool()
        store = PgNodeStore(pool)
        service = GraphService(GraphRepository(pool), node_store=store)
        await ExecutorService(service).execute_graph(
            graph_id,
            scope="selected",
            selected_ids=[node_key],
            max_retries=0,
        )
        logger.info("ChatGPT review: auto redo finished for %s/%s", graph_id, node_key)
    except Exception:
        logger.exception("ChatGPT review: auto redo failed for %s/%s", graph_id, node_key)


async def cleanup_test_rows(pool: PgPool, graph_id: str, node_keys: list[str]) -> int:
    """Remove queue rows for a graph (used by the S7 self-test teardown)."""
    async with pool.acquire() as conn:
        deleted = await conn.execute(
            "DELETE FROM canvas_review_queue WHERE graph_id=$1",
            uuid.UUID(str(graph_id)),
        )
    return int(str(deleted).split()[-1]) if deleted else 0


def extract_sentence(node: dict[str, Any], output: Any) -> str:
    cfg = node.get("config") or {}
    out = output if isinstance(output, dict) else {}
    for source in (out.get("output"), out.get("content"), cfg.get("content"),
                   cfg.get("script_text"), cfg.get("prompt"), cfg.get("text")):
        if isinstance(source, str) and source.strip():
            return source.strip()
    import json as _json

    try:
        return _json.dumps(out, ensure_ascii=False)[:2000]
    except Exception:
        return ""


def valid_node_key(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,255}", text):
        raise ValueError("invalid node id")
    return text
