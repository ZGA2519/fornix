# .fornix

Project memory that every AI session and every model shares, versioned with the code it describes.

```
memories/<scope>.jsonl   the store: one memory per line, committed, git is the history
index.db                 sqlite-vec vector index, gitignored, rebuilt from the JSONL when they drift
context_store/store.py   the operations
context_store/server.py  MCP server (stdio or HTTP) and a JSON API over the same store
```

## Install in a project

From the fornix checkout, `./install.sh /path/to/your-repo` does this and
the `context-sync` skill in one step; add `--codex`, `--gemini`, `--agy` or `--vscode`
to register those clients as well (see `setup.sh` below). By hand: copy this folder to the repo root as
`.fornix/` and put `.mcp.json` next to it:

```json
{"mcpServers": {"fornix": {"command": "uv", "args": ["run", "--directory", ".fornix", "python", "-m", "context_store.server", "mcp"]}}}
```

Needs [uv](https://docs.astral.sh/uv/). The first `uv run` builds `.venv/` and downloads the embedding model (about 30 MB) into `$FASTEMBED_CACHE_PATH`, or the temp dir if unset. Commit `memories/`; the `.gitignore` in this folder drops everything else.

## Connect

Claude Code reads `.mcp.json` and starts the server itself. Any other MCP client over stdio:

```sh
uv run --directory .fornix python -m context_store.server mcp
```

`setup.sh` registers that command with a client through the client's own `mcp add`, or prints every command when given no flag:

```sh
.fornix/setup.sh                    # print, run nothing
.fornix/setup.sh --codex --gemini   # run those; also --claude --agy --vscode
```

As a service, JSON API with docs at `/docs` and MCP at `/mcp`:

```sh
uv run --directory .fornix python -m context_store.server serve            # http://127.0.0.1:8765
curl -s localhost:8765/select -d '{"query":"how is auth done"}' -H 'content-type: application/json'
```

## Operations

| op | args | does |
| --- | --- | --- |
| `write` | text, scope=main, tags, id | Save one fact. Returns the memory with its id. Pass an existing `id` to correct that memory in place. |
| `select` | query, scope=main, k=8, tags, since | Semantic search, best first with a score. Empty query lists the k newest. `since` (ISO date or datetime) keeps what changed from then on. |
| `compress` | scope, ids, summary, threshold=0.92 | ids + summary: replace them with one summary in scope. Nothing: merge near-duplicates, newest kept. |
| `isolate` | scope, seed_from, query, k, tags | Open a private scope, optionally seeded with the top k memories of another. |
| `forget` | ids | Delete those memories from any scope. git keeps the old lines. |
| `scopes` | | Every scope with its memory count and tag counts. Over HTTP: `GET /health`. |

Scope names are `[a-z0-9._-]`, one JSONL file each. `main` is the shared default.

## Workflow

1. Session start: `select(query="what I am about to do")`.
2. While working: `write` each decision, gotcha or preference as you learn it.
3. Sub-task or sub-agent: `isolate("task-x", seed_from="main", query=...)`, work inside that scope, then `compress("main", ids, summary)` to fold it back.
4. Now and then: `compress()` to merge duplicates.

## Notes

- Test the install on a new machine: `uv run --group dev pytest`.
- Delete a memory with `forget(ids)`, or by removing its line from the JSONL. The index resyncs on the next call.
- `write` refuses text shaped like a credential (cloud and API keys, tokens, private keys, `user:pass@` URLs, `password = ...`). Store where a secret lives, never the value.
- Deleting `index.db` or `.venv/` under a running server strands its open handles. Restart it (Claude Code: `/mcp`, reconnect). Tool errors land in the client's MCP log via stderr.
- Merge conflicts in a JSONL: keep both sides, ids are unique, then run `compress()`.
- `CONTEXT_EMBED_MODEL` picks any fastembed model. Changing it rebuilds the index.
- The server holds no LLM. Summaries come from the model calling `compress`, so any model can be the summariser.
