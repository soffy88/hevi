"""Local practice-loop prototype for the Xiaoya English 陪练 (English coaching)
library built by build_unit.py.

Flow (local only, no network on the hot path):

    student input (text)  ->  retrieve nearest library item (EG2 text vec)
                          ->  Xiaoya replies with the cached EN audio + motion
                          ->  score the student's attempt with mneme's
                              check_english_answer (reused in-process)

The library + EG2 vectors are precomputed; retrieval is a handful of 768-d dot
products.  Scoring reuses ``vendor/oskill/english_answer_check_skill`` exactly
as shipped in mneme (we import it, we do not reimplement it).

Run the HTTP API:

    PYTHONPATH=/data/soffy/projects/hevi-live:/data/soffy/projects/mneme:/data/soffy/projects/mneme/vendor \\
    /data/soffy/venvs/hevi-oskill/bin/python \\
        -m hevi.live_host.eng_lib.practice --book pep-g7a --unit u1 --port 8791

(The scoring half imports mneme's ``oskill``/``oprim``, which need mneme's deps;
``/data/soffy/venvs/hevi-oskill`` has them.  If that import fails scoring
degrades to a plain equality check, so the EG2 retrieval path still works with
any interpreter.)

Or call :func:`PracticeSession.respond` directly (function API).
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from hevi.live_host.avatar.motionrag import DIM

DEFAULT_ROOT = Path(os.environ.get("HEVI_ENGLIB_ROOT", "/data/soffy/englib"))


def _l2(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(n, 1e-9)


class EngUnit:
    """One practice unit: pre-generated EN audio + EG2 text index."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.items: list[dict] = self.manifest["items"]
        self.ids: list[str] = [i["id"] for i in self.items]
        z = np.load(self.root / "index.npz", allow_pickle=False)
        order = list(z["ids"])
        self.text_emb = np.stack(
            [
                z["text"][self.ids.index(i)] if i in self.ids else z["text"][order.index(i)]
                for i in self.ids
            ]
        )
        # align embeddings to self.ids order
        self.text_emb = _l2(self.text_emb)
        self._by_id = {i["id"]: i for i in self.items}

    def nearest(self, vec: np.ndarray) -> tuple[dict, float]:
        sims = self.text_emb @ np.asarray(vec, dtype=np.float32)
        i = int(np.argmax(sims))
        return self.items[i], float(sims[i])

    def by_id(self, item_id: str) -> dict | None:
        return self._by_id.get(item_id)

    def wav_path(self, item: dict) -> Path:
        return self.root / item["wav"]


# --------------------------------------------------------------------------
# scoring — reuse mneme's oskill, imported in-process
# --------------------------------------------------------------------------


def score_answer(
    text: str,
    accepted: list[str],
    *,
    atype: str = "fill",
    context: str = "",
    pattern: str | None = None,
) -> dict:
    """Wrap mneme's ``check_english_answer``.  Returns a JSON-serialisable dict.
    Import errors degrade gracefully to a simple equality check."""
    try:
        from oskill.english_answer_check_skill import check_english_answer, EnglishCheckRequest

        v = check_english_answer(
            EnglishCheckRequest(
                text=text, accepted=accepted, type=atype, context=context, pattern=pattern
            )
        )
        return v.model_dump()
    except Exception:
        ok = (
            text.strip().lower() in {a.strip().lower() for a in accepted}
            if accepted
            else bool(text.strip())
        )
        return {
            "ok": ok,
            "answer_ok": ok,
            "messages": ["（本地评分不可用，使用基础匹配）"],
            "kernel": "fallback",
        }


# --------------------------------------------------------------------------
# session
# --------------------------------------------------------------------------


class PracticeSession:
    """Stateful-ish practice loop over one EngUnit."""

    def __init__(self, unit: EngUnit, *, embed_fn=None) -> None:
        self.unit = unit
        self.embed = embed_fn  # (text,) -> (768,) L2-normalised (Document vec)
        self.last_target: dict | None = None

    def _present(self, item: dict) -> dict:
        self.last_target = item
        return {
            "role": "xiaoya",
            "action": "present",
            "id": item["id"],
            "text": item["text"],
            "gloss": item.get("gloss", ""),
            "motion": item.get("motion", "talk_a"),
            "audio": str(self.unit.wav_path(item)),
        }

    def present_by_id(self, item_id: str) -> dict:
        it = self.unit.by_id(item_id)
        if it is None:
            raise KeyError(item_id)
        return self._present(it)

    def present_nearest(self, query: str) -> dict:
        """Pick the library item whose text is nearest the query (used when the
        coach chooses what to practice next)."""
        if self.embed is None:
            it = self.unit.items[0]
        else:
            vec = self.embed(query, query=False)
            it, _ = self.unit.nearest(vec)
        return self._present(it)

    def respond(self, student_text: str) -> dict:
        """Student says/types a sentence.  We (1) retrieve the nearest library
        item as the target/reference, (2) score the attempt against it, (3)
        return Xiaoya's cached audio for the target so she can model it."""
        if self.embed is not None:
            vec = self.embed(student_text, query=True)
            target, sim = self.unit.nearest(vec)
        else:
            target, sim = self.unit.items[0], 0.0
        verdict = score_answer(
            student_text,
            accepted=[target["text"]],
            atype="fill",
            context=target.get("gloss", ""),
        )
        reply_audio = self.unit.wav_path(target)
        return {
            "role": "xiaoya",
            "action": "respond",
            "target_id": target["id"],
            "target_text": target["text"],
            "target_gloss": target.get("gloss", ""),
            "motion": target.get("motion", "talk_a"),
            "audio": str(reply_audio),
            "retrieval_sim": round(sim, 3),
            "score": verdict,
        }


# --------------------------------------------------------------------------
# embedder wiring (offline build-time EG2; not used on the live hot path)
# --------------------------------------------------------------------------


def _make_embedder():
    try:
        from hevi.live_host.avatar.motionrag import Config, get_embedder

        return get_embedder(Config(), allow_audio=False)
    except Exception:
        return None


# --------------------------------------------------------------------------
# HTTP API
# --------------------------------------------------------------------------


def make_app(session: PracticeSession):
    class H(BaseHTTPRequestHandler):
        def _j(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/health":
                return self._j({"status": "ok", "unit": session.unit.manifest.get("title")})
            if self.path == "/items":
                return self._j({"items": session.unit.items})
            return self._j({"error": "not found"}, 404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/present":
                q = body.get("query", "")
                if body.get("id"):
                    return self._j(session.present_by_id(body["id"]))
                return self._j(session.present_nearest(q))
            if self.path == "/respond":
                return self._j(session.respond(body.get("text", "")))
            return self._j({"error": "not found"}, 404)

    return H


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="pep-g7a")
    ap.add_argument("--unit", default="u1")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--port", type=int, default=8791)
    args = ap.parse_args()

    unit_dir = Path(args.root) / args.book / args.unit
    unit = EngUnit(unit_dir)
    emb = _make_embedder()
    session = PracticeSession(
        unit, embed_fn=(lambda t, query=False: emb.text([t], query=query)[0]) if emb else None
    )

    print(
        f"practice loop ready: {unit.manifest.get('title')} ({len(unit.items)} items) on :{args.port}",
        flush=True,
    )
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_app(session))
    srv.serve_forever()


if __name__ == "__main__":
    main()
