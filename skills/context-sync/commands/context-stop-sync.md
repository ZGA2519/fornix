---
description: Stop syncing this session with the context MCP project memory
---

Use the `context-sync` skill and run its **context-stop-sync** command: flush any
durable facts from this session that aren't stored yet, clear the
`.fornix/.sync-on` flag, then stop calling `fornix` tools until sync is
started again.
