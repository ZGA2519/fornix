---
description: Sync this session with the context MCP project memory, recall only, never writing
---

Use the `context-sync` skill and run its **context-start-sync-readonly** command:
verify the `fornix` MCP server answers, prime the session with a `select`, set the
`.fornix/.sync-on` flag to `readonly`, then run the per-turn loop with the capture
half skipped — recall on every prompt, no `write` and no `compress` until the user
explicitly runs `context-start-sync`.
