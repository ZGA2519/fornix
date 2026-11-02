---
description: Set how many memories fornix recalls (k, sync_k), saved in .fornix/config.json
argument-hint: "[k] [sync_k]  e.g. 12 10, or sync_k=10"
---

Use the `context-sync` skill and run its **context-set-k** command with these
arguments: `$ARGUMENTS`

Map them to flags, then run from the repo root:
`uv run --quiet --directory .fornix python -m context_store.config <flags>`

- nothing → no flags: it only prints the current values and where each comes from
- `N` → `--k N` · `N M` → `--k N --sync-k M`
- `k=N` / `sync_k=M` → `--k N` / `--sync-k M`, in any order

Both must be whole numbers from 1 to 100. Show the user the command's output and
say that `.fornix/config.json` should be committed so teammates share it.
