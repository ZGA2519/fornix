"""Project memory shared across AI sessions and models.

memories/<scope>.jsonl is the source of truth and is committed: one memory per line, git is the history.
index.db (sqlite-vec) is a derived cache: gitignored, rebuilt from the JSONL whenever the two drift.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import sqlite_vec
from sqlite_vec import serialize_float32

ROOT = Path(os.environ.get("CONTEXT_DIR", Path(__file__).resolve().parent.parent))
MODEL = os.environ.get("CONTEXT_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
SCOPE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")  # a scope becomes a filename, keep it boring
MAX_K = 100


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _serialized(fn):
    """One op at a time per process. The HTTP server calls in from a threadpool and shares one sqlite connection."""

    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        with self._guard:  # ponytail: one lock per process; a memory store never sees enough traffic to shard it
            return fn(self, *a, **kw)

    return wrapper


class Store:
    def __init__(self, root: Path = ROOT):
        self.mem = root / "memories"
        self.mem.mkdir(parents=True, exist_ok=True)
        self._guard = threading.RLock()
        self.db = sqlite3.connect(root / "index.db", timeout=30, isolation_level=None, check_same_thread=False)
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self._model = None
        self._records: dict[str, dict] = {}
        self._stamp: tuple | None = None
        self._init_index()

    # ---- the four operations ------------------------------------------------

    @_serialized
    def write(self, text: str, scope: str = "main", tags=(), source: str = "", supersedes=(), origin: str = "", id: str = "") -> dict:
        """Append a memory. With id: replace that memory in place, same id, new ts, old tags and source unless given."""
        scope = self._scope(scope)
        text = text.strip()
        if not text:
            raise ValueError("text is empty")
        if id:
            old = self._remove([id])[0]
            tags, source = tags or old["tags"], source or old["source"]
            supersedes, origin = supersedes or old.get("supersedes", ()), origin or old.get("origin", "")
        rec = {"id": id or uuid.uuid4().hex[:12], "ts": _now(), "text": text, "tags": sorted(set(tags)), "source": source}
        if supersedes:
            rec["supersedes"] = list(supersedes)
        if origin:
            rec["origin"] = origin
        with self._lock(), (self.mem / f"{scope}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._sync()
        return {**rec, "scope": scope}

    @_serialized
    def select(self, query: str = "", scope: str = "main", k: int = 8, tags=()) -> list[dict]:
        scope = self._scope(scope)
        k = max(1, min(int(k), MAX_K))
        self._sync()
        tags = set(tags)
        pool = {r["id"]: r for r in self._records.values() if r["scope"] == scope and (not tags or tags & set(r["tags"]))}
        if not query.strip():
            return self._newest(pool.values())[:k]
        rows = self.db.execute(
            "select id, distance from vec where embedding match ? and k = ? and scope = ? order by distance",
            # ponytail: over-fetch then tag-filter in python; add a tags metadata column if a scope gets huge
            (self._embed_query(query), k * 4 if tags else k, scope),
        ).fetchall()
        return [{**pool[i], "score": round(1 - d, 4)} for i, d in rows if i in pool][:k]

    @_serialized
    def compress(self, scope: str = "main", ids=(), summary: str = "", threshold: float = 0.92) -> dict:
        """With ids + summary: replace those memories (any scope) by one summary written to `scope`.
        Without: drop near-duplicates inside `scope`, keeping the newest of each cluster."""
        scope = self._scope(scope)
        self._sync()
        if summary.strip():
            if not ids:
                raise ValueError("summary needs the ids it replaces")
            gone = self._remove(ids)
            tags = {t for r in gone for t in r["tags"]}
            source = ", ".join(sorted({r["source"] for r in gone if r["source"]}))
            kept = self.write(summary, scope, tags, source, supersedes=[r["id"] for r in gone])
            return {"kept": kept, "removed": [r["id"] for r in gone]}
        pool = self._newest(r for r in self._records.values() if r["scope"] == scope)
        merged: dict[str, list[str]] = {}
        dropped: set[str] = set()
        for r in pool:  # newest first, so anything still standing when we reach r is older than r
            if r["id"] in dropped:
                continue
            (emb,) = self.db.execute("select embedding from vec where id = ?", (r["id"],)).fetchone()
            rows = self.db.execute(
                "select id, distance from vec where embedding match ? and k = 20 and scope = ?", (emb, scope)
            ).fetchall()
            dupes = [i for i, d in rows if i != r["id"] and i not in dropped and 1 - d >= threshold]
            if dupes:
                merged[r["id"]] = dupes
                dropped.update(dupes)
        if dropped:
            self._remove(dropped)
        return {"merged": merged, "removed": sorted(dropped)}

    @_serialized
    def isolate(self, scope: str, seed_from: str = "", query: str = "", k: int = 8, tags=()) -> dict:
        """Create or open a private scope. seed_from copies the k most relevant memories of another scope into it."""
        scope = self._scope(scope)
        (self.mem / f"{scope}.jsonl").touch()
        self._sync()
        seeded = []
        if seed_from:
            have = {r.get("origin") for r in self._records.values() if r["scope"] == scope}
            for r in self.select(query, seed_from, k, tags):
                if r["id"] not in have:
                    seeded.append(self.write(r["text"], scope, r["tags"], r["source"], origin=r["id"]))
        return {"scope": scope, "seeded": seeded, "memories": self.select("", scope, k=MAX_K)}

    @_serialized
    def scopes(self) -> list[dict]:
        self._sync()
        n = Counter(r["scope"] for r in self._records.values())
        return [{"scope": f.stem, "count": n.get(f.stem, 0)} for f in self._files()]

    # ---- plumbing -----------------------------------------------------------

    @staticmethod
    def _scope(s: str) -> str:
        if not SCOPE_RE.fullmatch(s):
            raise ValueError(f"bad scope {s!r}: lowercase [a-z0-9._-], 64 chars max")
        return s

    def _files(self) -> list[Path]:
        return sorted(self.mem.glob("*.jsonl"))

    @staticmethod
    def _newest(recs) -> list[dict]:
        # ts has second resolution, so ties fall back to file position: a later line is a later write
        return sorted(reversed(list(recs)), key=lambda r: r["ts"], reverse=True)

    @contextmanager
    def _lock(self):
        """Cross-process mutex on sqlite's write lock, so two AI sessions never clobber a file rewrite."""
        self.db.execute("begin immediate")
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        self.db.commit()

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(MODEL)
        return self._model

    def _embed_query(self, q: str) -> bytes:
        return serialize_float32(next(self.model.query_embed(q)))

    def _init_index(self):
        from fastembed import TextEmbedding

        dims = {m["model"]: m["dim"] for m in TextEmbedding.list_supported_models()}
        if MODEL not in dims:
            raise SystemExit(f"CONTEXT_EMBED_MODEL={MODEL!r} is not a fastembed model; known: {sorted(dims)}")
        with self._lock():
            self.db.execute("create table if not exists meta(k text primary key, v text)")
            row = self.db.execute("select v from meta where k = 'model'").fetchone()
            if row and row[0] != MODEL:
                self.db.execute("drop table if exists vec")  # vectors from another model are garbage
            self.db.execute("insert or replace into meta values ('model', ?)", (MODEL,))
            self.db.execute(
                "create virtual table if not exists vec using vec0("
                "id text primary key, scope text partition key, hash text, "
                f"embedding float[{dims[MODEL]}] distance_metric=cosine)"
            )

    def _sync(self):
        """Bring the in-memory records and the vector index in line with the JSONL files."""
        stamp = tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in self._files())
        if stamp == self._stamp:
            return
        recs: dict[str, dict] = {}
        for f in self._files():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    recs[r["id"]] = {**r, "scope": f.stem}
        want = {i: (r["scope"], _hash(r["text"])) for i, r in recs.items()}
        have = {i: (s, h) for i, s, h in self.db.execute("select id, scope, hash from vec")}
        stale = [i for i, v in have.items() if want.get(i) != v]
        fresh = [i for i, v in want.items() if have.get(i) != v]
        if stale or fresh:
            vecs = [serialize_float32(v) for v in self.model.embed([recs[i]["text"] for i in fresh])] if fresh else []
            with self._lock():  # delete-then-insert so a second session syncing the same lines is harmless
                self.db.executemany("delete from vec where id = ?", [(i,) for i in {*stale, *fresh}])
                self.db.executemany(
                    "insert into vec(id, scope, hash, embedding) values (?, ?, ?, ?)",
                    [(i, *want[i], v) for i, v in zip(fresh, vecs)],
                )
        self._records, self._stamp = recs, stamp

    def _remove(self, ids) -> list[dict]:
        ids = set(ids)
        self._sync()
        gone = [self._records[i] for i in ids if i in self._records]
        if missing := ids - {r["id"] for r in gone}:
            raise KeyError(f"unknown ids: {sorted(missing)}")
        with self._lock():
            for scope in {r["scope"] for r in gone}:
                f = self.mem / f"{scope}.jsonl"
                keep = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip() and json.loads(l)["id"] not in ids]
                f.write_text("".join(l + "\n" for l in keep), encoding="utf-8")
        self._sync()
        return gone
