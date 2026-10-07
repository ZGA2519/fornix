#!/usr/bin/env node
// npx fornix-cli: runs the PyPI installer of the same version through uvx. uv is required
// anyway, the MCP server runs on it, so there is no pipx fallback.
const { spawnSync } = require("node:child_process");
const { version } = require("./package.json");

const r = spawnSync("uvx", [`fornix@${version}`, ...process.argv.slice(2)], { stdio: "inherit" });
if (r.error) {
  console.error(r.error.code === "ENOENT" ? "fornix needs uv on PATH: https://docs.astral.sh/uv/getting-started/installation/" : r.error.message);
  process.exit(1);
}
process.exit(r.status ?? 1);
