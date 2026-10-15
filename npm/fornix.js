#!/usr/bin/env node
// npx fornix-cli setup|upgrade|set-root: the PyPI installer of the same version, through
// uvx. uv is required anyway, the MCP server runs on it, so there is no pipx fallback.
const { spawnSync } = require("node:child_process");
const { version } = require("./package.json");

// FORNIX_PROG makes usage lines and deprecation warnings name this front, not `fornix`.
const r = spawnSync("uvx", [`fornix@${version}`, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: { ...process.env, FORNIX_PROG: "npx fornix-cli" },
});
if (r.error) {
  console.error(r.error.code === "ENOENT" ? "fornix needs uv on PATH: https://docs.astral.sh/uv/getting-started/installation/" : r.error.message);
  process.exit(1);
}
process.exit(r.status ?? 1);
