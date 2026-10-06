<p align="center">
  <img src="https://raw.githubusercontent.com/ZGA2519/fornix/main/docs/banner.jpg" alt="fornix — Memory that moves with the code. $ uvx fornix -y" width="100%" />
</p>

<h1 align="center">Fornix</h1>

<p align="center">
  <strong>Project memory for AI coding sessions. Lives in the repo, travels with the code.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#the-operations">Operations</a> ·
  <a href="#how-it-compares">Compare</a> ·
  <a href="https://github.com/ZGA2519/fornix/blob/main/.fornix/README.md">Store &amp; server docs</a> ·
  <a href="https://github.com/ZGA2519/fornix/blob/main/skills/context-sync/SKILL.md">Skill protocol</a> ·
  <a href="https://pypi.org/project/fornix/">PyPI</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/fornix/"><img src="https://img.shields.io/pypi/v/fornix?label=pypi&style=flat-square&color=blue" alt="pypi" /></a>
  <a href="https://github.com/ZGA2519/fornix/actions/workflows/publish.yml"><img src="https://img.shields.io/github/actions/workflow/status/ZGA2519/fornix/publish.yml?style=flat-square&label=tests" alt="tests" /></a>
  <a href="https://github.com/ZGA2519/fornix/blob/main/LICENSE.txt"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="license" /></a>
</p>

<p align="center">
  <strong>Memory that branches, merges and gets reviewed with the code.</strong><br/>
  <strong>Shared by every model that opens the repo, consulted on every prompt. No hub, no account, no API key.</strong><br/>
  <a href="#why-it-is-shaped-like-this">Read why →</a>
</p>

---

<p align="center">
  <a href="https://github.com/ZGA2519/fornix/blob/main/docs/banner.mp4">
    <img src="https://raw.githubusercontent.com/ZGA2519/fornix/main/docs/banner.gif" alt="22-second walkthrough: install with uvx, recall before answering, capture after acting, commit the memory with the code" width="100%" />
  </a>
  <br/>
  <sub>Video made with <a href="https://github.com/latent-spaces/brag">brag</a>.</sub>
</p>

Every AI session starts from zero. Yesterday's decision gets re-argued, last
week's gotcha gets hit again, and the convention nobody wrote down gets broken by
the next model to touch the code. Hosted memory tools fix this with a service
outside the repo, so when the code moves, the memory does not.

fornix puts the memory **in the repo**. A teammate gets it by pulling, a
branch carries its own decisions, a pull request reviews a decision next to the
change that caused it. Any model, any MCP client.

| | |
|---|---|
| 📦 **Store** | `.fornix/memories/*.jsonl`, one fact per line, committed. Git is the history. |
| 🔌 **Server** | An MCP server over that store. Six tools, a sqlite-vec index for semantic recall, no model inside. |
| 🔁 **Discipline** | A skill and a hook that make the session recall *before* it answers and capture *after* it acts, every prompt, until told to stop. |
| 🌿 **Branches with the code** | Check out a branch or an old tag and you get the memory that was true there, not whatever a central store believes today. |
| 🤝 **Any model, any client** | Claude writes a memory, Codex reads it, Gemini corrects it. Same store, same file. |

---

## Use fornix

<table>
<tr>
<td width="50%" valign="top">

<h3>🧑‍💻 I work in one repo</h3>

One command installs the store, the server, the skill and the hook into the repo. Restart Claude Code, turn sync on, done.

**[→ Jump to Quick start](#quick-start)**

</td>
<td width="50%" valign="top">

<h3>🗂️ My editor is open on many repos</h3>

One store per repo, registered into the workspace folder above them. Each repo syncs on its own.

**[→ Jump to Many repos in one window](#many-repos-in-one-window)**

</td>
</tr>
<tr>
<td colspan="2" valign="top">

<h3>🔧 I use Codex, Gemini, Cursor, or want an API</h3>

Any MCP client gets the same six tools. There is also an HTTP service with a JSON API.

```sh
.fornix/setup.sh --codex --gemini
```

**[→ Jump to Other clients](#other-clients)**

</td>
</tr>
</table>

---

## Quick start

### Prerequisites

| tool | why |
| --- | --- |
| [Python](https://www.python.org/downloads/) 3.12+ | runs the installer; the store needs 3.14, which uv fetches for you |
| [uv](https://docs.astral.sh/uv/) | runs the MCP server, and `uvx` runs the installer. No uv yet? `pip install uv` or `pipx install uv` |
| `git` | the installer fetches the release from GitHub |

### Install

```sh
cd your-repo
uvx fornix -y
```

No uv for the installer? Either of these does the same:

```sh
pipx run fornix -y                  # pipx
pip install fornix && fornix -y     # plain pip, ideally in a venv
```

The server still runs through uv, so it has to be on `PATH` either way.

Restart Claude Code, approve the `fornix` server when asked, then:

```
/context-start-sync
```

That is the whole setup.
Drop the `-y` to be asked about the target, the hook and the other clients instead
of taking the defaults.

### What landed in the repo

| path | what |
| --- | --- |
| `.fornix/` | the store and the MCP server, with an empty `memories/main.jsonl` |
| `.mcp.json` | the `fornix` server entry, merged into whatever was there |
| `.claude/skills/context-sync/` | the skill that drives the per-prompt loop |
| `.claude/commands/context-*.md` | `/context-start-sync`, `/context-start-sync-readonly`, `/context-stop-sync` |
| `.claude/hooks/context-sync.sh` + `settings.json` | a `UserPromptSubmit` hook that re-arms the loop every prompt, so it survives compaction |
| `.agent/` | the same skill and commands under the vendor-neutral tree some agents read |

Commit `.fornix/memories/`. Everything else under `.fornix/` is gitignored.
Re-run the command any time to update an install; `memories/` is never touched.

### Upgrading from context-system

```sh
uvx fornix --upgrade
```

Moves `.context/` to `.fornix/` and swaps the `context-system` server entry for
`fornix`, keeping the hook choice the install already had. If a teammate's rename
already came in with a pull, so both folders exist, the memories left in
`.context/memories/` are merged in by id and `.context/` is removed; an id whose text
differs on the two sides stops the removal so you can compare. Workspace folders that
registered the repo with `--set-root` are re-pointed too. Other clients registered by
hand (`codex`, `gemini`, …) still carry the old `context-system` entry: remove it with
their own `mcp remove`.

### How it works

Once sync is on, every prompt runs the same loop:

1. **Recall.** Before answering, the model runs one `select` with a query built from the *intent* of your prompt and treats the hits as ground truth for this repo. If a stored decision contradicts what it was about to do, it says so instead of quietly overwriting it.
2. **Act.** Your prompt gets answered as usual.
3. **Capture.** After acting, it writes the durable facts it learned, one per call, correcting older memories in place rather than appending near-duplicates.

Every prompt ends with one quiet line:

```
context: 6 recalled · 1 written
```

A memory is one JSON line:

```json
{"id": "9f3c1a7be2d4", "ts": "2026-09-09T07:20:05+00:00", "text": "Session tokens are refreshed by the gateway, never by services. Tried per-service refresh first; it raced under load.", "tags": ["auth", "decision"], "source": ""}
```

Durable, so it gets written: a decision and why, the option that lost, a hard
constraint, a gotcha and its workaround, a convention the code does not reveal, a
stated preference. Not durable, so it does not: transient state, file contents,
anything re-derivable by reading the repo, general knowledge. Never: credentials,
tokens, personal data. The store is committed and pushed.

### Three commands

| command | does |
| --- | --- |
| `/context-start-sync` | recall and capture on every prompt |
| `/context-start-sync-readonly` | recall only, writes nothing, ever. For someone else's repo, or a branch whose decisions are not settled |
| `/context-stop-sync` | final flush of anything durable, then off |

---

## The operations

Any MCP client gets the same six tools. Scopes are named JSONL files; `main` is the shared default.

| tool | args | does |
| --- | --- | --- |
| `select` | `query`, `scope=main`, `k=8`, `tags`, `since` | Semantic search, best first, each with a score. Empty query lists the `k` newest. `since="2026-10-01"` keeps what changed from then on. |
| `write` | `text`, `scope=main`, `tags`, `source`, `id` | Save one fact. Pass an existing `id` to replace that memory in place. |
| `compress` | `scope`, `ids`, `summary`, `threshold=0.92` | `ids` + `summary`: fold those memories into one. Neither: merge near-duplicates, newest kept. |
| `isolate` | `scope`, `seed_from`, `query`, `k`, `tags` | Open a private scope, optionally seeded with the top `k` hits from another. |
| `forget` | `ids` | Delete those memories from any scope. git keeps the old lines. |
| `scopes` | | Every scope with its memory count and tag counts: what topics memory holds. |

A sub-task or a sub-agent that will generate a lot of throwaway reasoning gets
`isolate("task-x", seed_from="main", query=...)`, works in that scope, then
`compress("main", ids, summary)` folds the useful residue back.

---

## Many repos in one window

One store per repo, but the editor is usually open on the folder above several.
From that folder:

```sh
uvx fornix --set-root        # finds every repo with a .fornix/ up to 5 levels down, asks which join
```

or inside each repo, `.fornix/setup.sh --set-root ..`. Either way the repo adds
itself to that folder's `.mcp.json` as `fornix-<repo>` with an
absolute path, and copies the skill, commands and hook into the folder's `.claude/`.
Stores stay separate on purpose: one repo's decisions are not another's. Sync is
per repo too, so one repo can be capturing while another is read-only and the rest
are off.

---

## Other clients

**Claude Code** · **Codex** · **Gemini CLI** · **Antigravity** · **VS Code** · **Cursor** · **Windsurf** · **Cline** · **Zed** · **Claude Desktop** · any MCP client

Claude Code reads `.mcp.json` and is done. Everything else is one command away,
and `setup.sh` ships inside `.fornix/` so teammates without this repo have it:

```sh
.fornix/setup.sh                      # asks: which clients, which workspace folder
.fornix/setup.sh --codex --gemini     # also --claude --agy --vscode
.fornix/setup.sh --print              # just list the commands
```

### Manual configuration

Clients configured by file (Cursor, Windsurf, Cline, Zed, Claude Desktop) take
this under `mcpServers`:

```json
"fornix": {"command": "uv", "args": ["run", "--directory", "/abs/path/to/repo/.fornix", "python", "-m", "context_store.server", "mcp"]}
```

### As a service

A JSON API with docs at `/docs` and MCP at `/mcp`:

```sh
uv run --directory .fornix python -m context_store.server serve     # http://127.0.0.1:8765
curl -s localhost:8765/select -d '{"query":"how is auth done"}' -H 'content-type: application/json'
```

### Other ways to install

All of these are the same installer with the same flags. `uvx` fetches the release
tag from GitHub, so it needs `git`; the rest run from a checkout.

```sh
uvx fornix /path/to/repo -y                 # a repo other than the current one
uvx fornix --no-hook                        # skill only, no hook
uvx fornix --codex --vscode                 # register those clients as you go
uvx --from git+https://github.com/ZGA2519/fornix fornix   # track main

git clone https://github.com/ZGA2519/fornix && cd fornix
./install.sh /path/to/repo        # POSIX sh, the original
python3 setup.py /path/to/repo    # the same wizard in Python, runs in cmd.exe too
uv run fornix --help      # everything the installer accepts
```

---

## How it compares

Three other shapes exist. Each is better than this at something; none of them is
memory that moves with the code.

| | `AGENTS.md` / `CLAUDE.md` | hosted memory<br>(Mem0, Zep, Supermemory) | local memory server<br>(MemPalace, Basic Memory, ai-memory) | fornix |
| --- | --- | --- | --- | --- |
| committed in the repo | ✓ | ✗ | ✗ | ✓ |
| branches and merges with the code | ✓ | ✗ | ✗ | ✓ |
| reviewed in a pull request | ✓ | ✗ | ✗ | ✓ |
| a teammate gets it by pulling | ✓ | ✗ account | ✗ hub or sync | ✓ |
| retrieved per prompt, not loaded whole | ✗ | ✓ | ✓ | ✓ |
| recall the model cannot skip | ✓ always in context | ✗ tool call | ~ skill or session hook | ✓ per-prompt hook |
| no API key, no network | ✓ | ✗ | ~ varies | ✓ |
| any model, any client | ~ convention | ~ | ✓ | ✓ |
| nothing to run but the agent | ✓ | ✗ | ✗ server | ✓ |

Two rows are the ones that matter.

**A teammate gets it by pulling.** A hub gives everyone the same memory, but it
gives everyone *the latest* memory. Check out a colleague's branch or a tag from
three months ago and the hub still describes `main`. Here the memory is at the
same commit as the code in front of you.

**Recall the model cannot skip.** Every memory server is a tool the model calls
when it happens to think of it, which on a long session is less and less, right
when memory matters most. `AGENTS.md` solves that by being permanently in
context, and pays for it in tokens on every turn whether or not it is relevant.
The hook here re-arms a fixed recall loop on every prompt and survives
compaction, so recall is per-prompt and scoped to the prompt.

---

## Why it is shaped like this

**Memory is part of the repo.** A branch has its own memory. A pull request
reviews the memory along with the code. `git blame` on a decision works. Merge
conflicts in a JSONL are trivial: keep both sides, ids are unique, run `compress()`.
Checking out an old tag gives you the context that was true then, not whatever a
central store believes today.

**Sharing is `git pull`.** No hub to deploy, no account, no sync daemon, no
access control to maintain: if someone can clone the repo, they have the memory,
offline, in the same commit as the code it describes. Revoking access is
revoking repo access.

**No model inside the server.** Summaries in `compress` come from whichever model
is calling. Claude writes a memory, Codex reads it, Gemini corrects it. Same store,
same file.

**The index is disposable.** `index.db` is a sqlite-vec index rebuilt from the JSONL
whenever they drift. Delete it freely. Embeddings come from
`BAAI/bge-small-en-v1.5` via fastembed, about 30 MB, downloaded on first run;
`CONTEXT_EMBED_MODEL` picks another.

**The skill solves *when*, the hook makes it stick.** A memory server on its own
gets called whenever the model happens to think of it, which on a long session
means less and less. The skill turns it into a fixed per-turn loop. The hook
re-injects that loop on every prompt for as long as `.fornix/.sync-on` exists,
so compaction cannot erode it.

### What it is not

- **Not a token reducer.** It adds a few hundred tokens a turn. It saves work, not
  context window. Pair it with something that curates *which files* the session
  sees if that is the problem you have.
- **No temporal model.** Git gives you history, not queryable validity windows. If
  you need "this fact was true between these dates," Zep's temporal graph is built
  for that and this is not.
- **No cross-repo graph.** One store per repo, deliberately. A graph over
  everything your organisation knows is a different product.
- **Repo scale, not org scale.** JSONL plus a sqlite-vec index is right for
  thousands of memories, not millions.
- **The write gate is still a discipline, not a solver.** The skill defines what
  is durable and the model applies it. A store nobody prunes still decays; that is
  what `compress` is for.

---

## Under the hood

```
your prompt
    │
    ├── hook            re-arms the skill every prompt while .fornix/.sync-on exists
    ├── skill           select() before answering · write() after acting
    │
    └── MCP server      .fornix/context_store/server.py, stdio or HTTP
            │
            ├── store       .fornix/memories/<scope>.jsonl, committed, git is the history
            └── index       .fornix/index.db, sqlite-vec, gitignored, rebuilt when it drifts
```

```
.fornix/
  memories/<scope>.jsonl    the store, committed
  index.db                  sqlite-vec index, gitignored, rebuilt when it drifts
  context_store/store.py    the operations
  context_store/server.py   MCP over stdio, or HTTP with a JSON API
  setup.sh                  client registration and workspace folders
skills/context-sync/        the skill, commands and hook the installer copies
install.sh · setup.py       the installer, twice
```

Tests: `uv run --group dev pytest` inside `.fornix/` for the store,
`python3 test_setup.py` at the root for the installer.

### Releasing

Bump `version` in `pyproject.toml`, push to `main`. The workflow in
`.github/workflows/publish.yml` tags `v<version>`, builds and publishes to PyPI with
trusted publishing. A push that does not change the version does nothing.

---

## Links

- 📖 [Store and server docs](https://github.com/ZGA2519/fornix/blob/main/.fornix/README.md)
- 🔁 [The per-turn protocol, in full](https://github.com/ZGA2519/fornix/blob/main/skills/context-sync/SKILL.md)
- 📦 [PyPI](https://pypi.org/project/fornix/)
- 🐛 [Issues](https://github.com/ZGA2519/fornix/issues)
- 📄 [MIT license](https://github.com/ZGA2519/fornix/blob/main/LICENSE.txt)

---

<p align="center">
  <strong>Memory that moves with the code.</strong>
</p>
