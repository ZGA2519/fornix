---
name: context-sync
description: Drives the `fornix` MCP server (project memory - write/select/compress/isolate over a .fornix/ folder) on a fixed per-turn loop so recall and capture happen every prompt instead of whenever the model happens to think of it. Provides three commands, context-start-sync, context-start-sync-readonly and context-stop-sync. Use this skill whenever the user types any of those names, with or without a leading slash, and also whenever they ask to start or stop syncing context, turn project memory on or off, sync context without writing to it, recall only, read-only context, "keep context in sync", "remember this for the project", "check the context store first", or when a repo contains a .fornix/ folder and the user wants past decisions honored. Also use it when a session has clearly stopped consulting project memory and needs to be put back on the loop.
---

# context-sync

The `fornix` MCP server is a shared project memory: `memories/<scope>.jsonl` committed to git, a sqlite-vec index rebuilt from it, six tools. It works fine on its own — the problem it does not solve is *when* to call it. This skill supplies the when: two commands that flip a per-turn discipline on and off.

## The server

Launched by `.mcp.json` at the repo root as `uv run --directory .fornix python -m context_store.server mcp`. Six tools:

| tool | args | use |
| --- | --- | --- |
| `select` | `query=""`, `scope="main"`, `k=8`, `tags=[]` | Semantic recall, best first, each with a `score`. Empty query returns the `k` newest. |
| `write` | `text`, `scope="main"`, `tags=[]`, `source=""`, `id=""` | Save one fact. Returns the memory with its `id`. Pass an existing `id` to replace that memory in place. |
| `compress` | `scope="main"`, `ids=[]`, `summary=""`, `threshold=0.92` | `ids` + `summary`: replace those with one summary. Neither: merge near-duplicates, newest kept. |
| `isolate` | `scope`, `seed_from=""`, `query=""`, `k=8`, `tags=[]` | Open a private scope, optionally seeded with the top `k` of another. |
| `forget` | `ids` | Delete those memories, from any scope. For a wrong or obsolete fact; to fix one, `write(id=...)`. |
| `scopes` | | Every scope with its memory count and tag counts. Tags are the topics. |

Scope names are `[a-z0-9._-]`, 64 chars max, one JSONL file each. `main` is the shared default.

## Command: context-start-sync

1. Check the server answers: `select(query="", k=3)`. If the call errors, report that and **do not** turn sync on — say what failed and suggest `/mcp` to reconnect.
2. Prime the session: `select(query=<what this session is about>, k=8)`. If the user gave no topic yet, the empty query from step 1 is enough.
3. If a `.fornix/` directory exists, `echo full > .fornix/.sync-on`. This is the flag the hook reads, and its contents are the mode; harmless without the hook. It's gitignored by the install. In a window opened over several repos, the flag belongs to the repo being synced — `<repo>/.fornix/.sync-on` — never the folder above them.
4. Report in one line what came back, then run the loop below on **every** following prompt until `context-stop-sync`.

## Command: context-start-sync-readonly

Same as `context-start-sync` with capture switched off: recall on every prompt, write nothing, ever. For working in someone else's repo, on a branch whose decisions aren't settled, or any session whose reasoning shouldn't end up in a committed store.

1. Steps 1 and 2 above, unchanged.
2. `echo readonly > .fornix/.sync-on` instead of `full`.
3. Report that sync is on in read-only mode, then run the loop with the **Capture** half skipped.

While read-only:
- `select` and `isolate(seed_from=...)` are fine — the first is a pure read, the second only ever copies into a private throwaway scope.
- `write` and `compress` are off limits. `compress` deletes lines from the JSONL, so it counts as a write no matter how it's framed.
- Something durable turns up and there's nowhere to put it: mention it in one line at the end of the turn and move on. Don't stockpile a list to flush later, and don't ask every turn for permission to write.
- Switching to full capture takes an explicit `context-start-sync` from the user. Nothing said mid-session — "yeah that's worth remembering", "go ahead" — promotes read-only to writable on its own.
- Footer marks the mode: `context: 6 recalled · read-only`.

## The per-turn loop (while sync is on)

Recall runs in both modes. Capture runs only in full mode.

**Recall, before answering.** One `select` per prompt, `k=6`. Build the query from the *intent* of the prompt in your own words, not the prompt verbatim — it's semantic search, so "how do we handle auth token refresh" beats "fix the thing you broke". Then:

- Treat what comes back as project ground truth. It outranks your assumptions about this repo.
- If a memory contradicts what you were about to say or do, say so out loud before proceeding. Never quietly overwrite a recorded decision.
- Low scores across the board means nothing relevant is stored — say nothing and move on. Don't pad the answer with weak hits.
- The one skip: a bare acknowledgement ("yes", "go on", "ok do it") gets no fresh select — reuse the previous turn's recall.

**Capture, after acting.** One fact per `write`, a sentence or two, with tags.

Durable — write these:
- a decision and *why*, including the option that lost
- a constraint that can't be negotiated away (version pin, quota, compliance rule)
- a gotcha and its workaround, especially one that cost real time
- a convention this repo follows that the code alone doesn't reveal
- a stated preference about how work should be done here
- an environment fact that bit you and will bite again

Not durable — don't write these:
- transient state ("the branch is currently rebasing")
- file contents, diffs, or anything re-derivable by reading the repo in seconds
- general knowledge that isn't specific to this project
- a restatement of what the code plainly says

**Correct, don't duplicate.** If `select` surfaced an older version of the fact you're about to record, call `write(id=<that id>, text=<new text>)` to replace it in place. Tags and source carry over unless you pass new ones. Appending a near-duplicate instead is the main way this store rots.

**Never write:** credentials, tokens, API keys, connection strings, passwords, personal data, or raw production config. `memories/` is committed and pushed. If a fact needs one of those to make sense, write the shape without the value — "auth uses a service token from Vault at <path>", not the token.

**Volume.** Zero to three writes a turn is normal. A turn with nothing durable in it gets zero writes, and that is a correct turn, not a missed one.

**Report.** End the turn with one quiet line, nothing more:

```
context: 6 recalled · 1 written
```

## Scopes

Default everything to `main`. For a sub-task or a subagent that will generate a lot of throwaway reasoning, `isolate("task-name", seed_from="main", query=<the sub-task>)`, work with `scope="task-name"`, then fold the useful residue back with `compress("main", ids=[...], summary=<one or two sentences>)`. Occasionally, when a scope feels repetitive, a bare `compress()` merges near-duplicates on its own. In read-only mode the fold-back and the tidy-up are both off — an isolated scope stays a scratchpad and is simply abandoned.

## Command: context-stop-sync

Stops either mode.

1. In full mode, final flush: write anything durable from this session that isn't stored yet. This is the last chance. In read-only mode, skip this — read-only means read-only right through the exit.
2. `rm -f .fornix/.sync-on`, in each repo it was set for.
3. Stop calling `fornix` tools. Don't recall, don't write, don't offer to — until a start command comes again.
4. Report: `context: sync off · N written this session`, or `context: sync off · read-only, nothing written`.

## When it breaks

A tool error or an unreachable server: say it once, treat sync as off, carry on with the actual work. Don't retry the call every turn — a broken memory store shouldn't turn into a per-prompt tax.

## Making it survive a long session

These instructions live in context, so on a long or heavily compacted session the loop can quietly fade. The hard guarantee is the `UserPromptSubmit` hook at `.claude/hooks/context-sync.sh`, which re-injects the loop on every prompt as long as `.fornix/.sync-on` exists. `install.sh` puts it there and registers it in `.claude/settings.json`; if this repo was set up by hand or with `--no-hook`, re-run `./install.sh <this repo>` from the fornix checkout to add it. Claude Code CLI only — Cowork does not fire hooks, so there the skill-only path is all there is.

The three command names are real slash commands when `install.sh` has run (they live in `.claude/commands/`, which is the only place Claude Code looks — command files sitting inside a skill folder are never registered). Without them, typing the command name as plain text works just as well.

## Many repos in one window

One store per repo, but the editor is often open on the folder above several of them. Running `.fornix/setup.sh --set-root <that folder>` inside each repo puts a `fornix-<repo>` server in the folder's `.mcp.json` — absolute path, so it starts from anywhere — copies the skill, the commands and the hook into its `.claude/`, and lists the repo in `.claude/context-sync.repos`, which is how the hook finds the members.

The stores stay separate on purpose: one repo's decisions are not another's. Recall from the server that owns the files a prompt is about and write back to that same one — `fornix-api` for `api/`, `fornix-web` for `web/`. Sync is per repo too. The hook arms exactly the servers whose repo has a `.sync-on` flag, so a session can have one repo capturing, another read-only, and the rest off.

## Tuning

`k=6` on recall and one select per prompt is the default because recall cost is paid on every turn. Raise `k` for a research-heavy session, drop to select-only-on-topic-change if the store is small and the session is long. If the user asks for cheaper syncing, cut recall frequency first, never capture.
