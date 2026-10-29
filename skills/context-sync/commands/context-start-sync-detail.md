---
description: Sync this session with the context MCP project memory and log every prompt and tool call in detail
---

Use the `context-sync` skill and run its **context-start-sync-detail** command:
verify the `fornix` MCP server answers, prime the session with a `select`, set the
`.fornix/.sync-on` flag to `detail`, then run the full per-turn recall/capture loop.
The hook logs every prompt and every tool call on its own to the `detail` scope;
nothing extra to write by hand.
