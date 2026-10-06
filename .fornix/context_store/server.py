"""Two doors to the same Store: MCP tools (stdio, or /mcp over HTTP) and a plain JSON API."""

from __future__ import annotations

import argparse
import functools
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .store import Store

store = Store()

mcp = MCPServer(
    "fornix",
    instructions=(
        "Project memory shared by every AI session and model working on this repo. "
        "Start a session with select(query=<what you are about to do>). "
        "Write decisions, gotchas and preferences as you learn them, one fact per write. "
        "Use isolate for a sub-task's private scope, then compress its ids back into main with a summary."
    ),
)


def _surface(fn):
    """Validation failures are the caller's to fix, so hand the message to the model instead of a bare 'error'."""

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except (ValueError, KeyError) as e:
            raise ToolError(str(e)) from e

    return wrapper


def _client(ctx: Context) -> str:
    try:
        info = ctx.session.client_params.client_info
        return f"{info.name} {info.version or ''}".strip()
    except AttributeError:
        return ""


@mcp.tool()
@_surface
def write(text: str, scope: str = "main", tags: list[str] | None = None, source: str = "", id: str = "", ctx: Context = None) -> dict:
    """Save one fact, decision, gotcha or preference so later sessions of any model can recall it.
    Keep it to a sentence or two. tags are free-form labels such as ["decision", "db"].
    Pass the id of an existing memory to correct it in place: same id, new text, tags kept unless given."""
    return store.write(text, scope, tags or [], source or _client(ctx), id=id)


@mcp.tool()
@_surface
def select(query: str = "", scope: str = "main", k: int = 8, tags: list[str] | None = None) -> list[dict]:
    """Recall memories. With a query: semantic search, best first, each with a score.
    Without a query: the k newest. tags keeps only memories carrying any of them. Call this before starting work."""
    return store.select(query, scope, k, tags or [])


@mcp.tool()
@_surface
def compress(scope: str = "main", ids: list[str] | None = None, summary: str = "", threshold: float = 0.92) -> dict:
    """Shrink memory. ids + summary: replace those memories (from any scope) with one summary written to scope.
    Neither: near-duplicates inside scope are merged automatically, newest kept, and the merges reported."""
    return store.compress(scope, ids or [], summary, threshold)


@mcp.tool()
@_surface
def isolate(scope: str, seed_from: str = "", query: str = "", k: int = 8, tags: list[str] | None = None) -> dict:
    """Open a private scope for a sub-task or agent. seed_from + query copies the k most relevant memories
    of another scope into it. Then write/select with scope=<name>, and compress its ids into main when done."""
    return store.isolate(scope, seed_from, query, k, tags or [])


@mcp.tool()
@_surface
def forget(ids: list[str]) -> dict:
    """Delete memories by id, from any scope, when a fact is wrong or obsolete. To fix one instead, write(id=...).
    git keeps the deleted lines."""
    return store.forget(ids)


@mcp.tool()
def scopes() -> list[dict]:
    """Map of what project memory holds: every scope with its memory count and tag counts, most used first.
    Tags are the topics; select(tags=[...]) recalls one."""
    return store.scopes()


@asynccontextmanager
async def _lifespan(_app):
    async with mcp.session_manager.run():
        yield


api = FastAPI(title="context", lifespan=_lifespan)
api.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/", stateless_http=True))
for exc in (ValueError, KeyError):
    api.add_exception_handler(exc, lambda _r, e: JSONResponse({"detail": str(e)}, 400))


@api.get("/health")
def health():
    return {"ok": True, "scopes": store.scopes()}


@api.post("/write")
def write_api(text: str = Body(), scope: str = Body("main"), tags: list[str] = Body([]), source: str = Body(""), id: str = Body("")):
    return store.write(text, scope, tags, source, id=id)


@api.post("/select")
def select_api(query: str = Body(""), scope: str = Body("main"), k: int = Body(8), tags: list[str] = Body([])):
    return store.select(query, scope, k, tags)


@api.post("/compress")
def compress_api(scope: str = Body("main"), ids: list[str] = Body([]), summary: str = Body(""), threshold: float = Body(0.92)):
    return store.compress(scope, ids, summary, threshold)


@api.post("/isolate")
def isolate_api(scope: str = Body(), seed_from: str = Body(""), query: str = Body(""), k: int = Body(8), tags: list[str] = Body([])):
    return store.isolate(scope, seed_from, query, k, tags)


@api.post("/forget")
def forget_api(ids: list[str] = Body(embed=True)):
    return store.forget(ids)


def main():
    p = argparse.ArgumentParser(prog="context", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mcp", help="MCP server on stdio, what .mcp.json launches")
    s = sub.add_parser("serve", help="JSON API plus MCP at /mcp over HTTP")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    a = p.parse_args()
    # stderr is what MCP clients capture into their logs; without a handler tool errors vanish
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")
    if a.cmd == "mcp":
        mcp.run()
    else:
        uvicorn.run(api, host=a.host, port=a.port)


# `python -m context_store.server` is how .mcp.json starts the server: it finds the
# package through the working directory, not through the editable install's .pth file,
# which macOS can hide (UF_HIDDEN) and Python's site machinery then silently skips.
if __name__ == "__main__":
    main()
