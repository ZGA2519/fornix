#!/usr/bin/env python3
"""Install fornix into a repo: store, MCP entry, skill, commands, hook.

The Python twin of install.sh, for machines without a POSIX sh and for running as a
tool: `uv run fornix` in a checkout, or without one
`uvx --from git+https://github.com/ZGA2519/fornix fornix`.
Idempotent, re-run to update an install. An existing .fornix/memories/ is never touched.
Run with no answers on a terminal and it asks for them; -y takes the defaults.
"""
import argparse
import atexit
import contextlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO_URL = "https://github.com/ZGA2519/fornix.git"
CLIENT_FLAGS = ["--claude", "--codex", "--gemini", "--agy", "--vscode"]
MCP_ENTRY = {"command": "uv", "args": ["run", "--directory", ".fornix", "python", "-m", "context_store.server", "mcp"]}
HOOK_CMD = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/context-sync.sh'

USAGE = """\
%(prog)s [TARGET_REPO] [-y] [--no-hook] [--claude] [--codex] [--gemini] [--agy] [--vscode]
       %(prog)s [FOLDER] --set-root [-y]"""
DESCRIPTION = """\
Installs into TARGET_REPO (default: the current directory):

  .fornix/                             the store and MCP server
  .mcp.json                             mcpServers.fornix, merged in
  .claude/skills/context-sync/          the skill
  .claude/commands/context-*.md         /context-start-sync, -readonly, /context-stop-sync
  .claude/hooks/context-sync.sh         per-prompt loop re-injection
  .claude/settings.json                 the UserPromptSubmit hook, merged in
  .agent/skills/context-sync/           the same skill, vendor-neutral tree
  .agent/prompts/context-*.md           the same commands, called prompts there

  --no-hook   skip the last two; the skill alone drives the loop
  --claude --codex --gemini --agy --vscode
              also register the server with those clients, via .fornix/setup.sh

Anything not given is asked for interactively when there is a terminal. -y (--yes)
answers every question with its default instead: the current directory, the hook on,
no extra clients.

--set-root      the other job: FOLDER (default: the current directory) is a workspace
                folder opened over several repos. Finds every repo with a .fornix/
                install up to 5 levels below it, asks which should join, and runs each
                one's .fornix/setup.sh --set-root FOLDER. -y takes them all."""

if os.name == "nt":
    os.system("")  # ponytail: the documented hack that turns on ANSI escapes in conhost
sys.stdout.reconfigure(errors="replace")  # glyphs below must not crash a cp1252 pipe
if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
    B, D, R, C, G, Y, M = "\033[1m", "\033[2m", "\033[0m", "\033[36m", "\033[32m", "\033[33m", "\033[35m"
else:
    B = D = R = C = G = Y = M = ""

count = Counter()


def sec(title):
    print(f"\n{M}▌{R} {B}{title}{R}")


def say(path, status):
    """One row; glyph and colour follow the status verb, counted for the summary."""
    if "already" in status or status.startswith("kept"):
        glyph, colour, kind = f"{D}•", D, "same"
    elif status.startswith("skipped"):
        glyph, colour, kind = f"{Y}!", Y, "skip"
    else:
        verbs = ("added", "registered", "created", "replaced", "removed")
        glyph, colour, kind = f"{G}✔", G if any(v in status for v in verbs) else "", "new"
    count[kind] += 1
    print(f"  {glyph}{R} {C}{path:<28}{R} {colour}{status}{R}")


def load_json(p):
    if p.exists() and p.read_text().strip():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f"{p} is not valid JSON ({e}); fix or move it and re-run")
    return {}


def save_json(p, doc):
    p.write_text(json.dumps(doc, indent=2) + "\n")


# --- prompts ---------------------------------------------------------------
# The same vite-style wizard install.sh has: arrows move, space toggles, enter
# accepts, digits jump, q or Esc cancels with nothing written. Raw keys come from
# termios on POSIX and msvcrt on Windows. Only asked for what the flags left open,
# and only on a tty: without one the defaults apply.
try:
    import select
    import termios
    import tty
except ImportError:  # Windows
    import msvcrt
    termios = None

HIDE, SHOW = "\033[?25l", "\033[?25h"
KEYS = {"\x1b[A": "up", "\x1b[B": "down", "\x1b[C": "right", "\x1b[D": "left",
        "\x1bOA": "up", "\x1bOB": "down", "\x1bOC": "right", "\x1bOD": "left",
        "\r": "enter", "\n": "enter", " ": "space", "\t": "down", "k": "up", "j": "down",
        "q": "cancel", "\x1b": "cancel", "\x03": "cancel", "": "cancel"}


@contextlib.contextmanager
def raw():
    """Keys unechoed and the cursor hidden for one question; both put back whatever happens.
    Entering flushes what was typed while the last question was closing, as install.sh does."""
    if termios:
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        tty.setcbreak(fd, termios.TCSAFLUSH)
    print(HIDE, end="", flush=True)
    try:
        yield
    finally:
        print(SHOW, end="", flush=True)
        if termios:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def _key():
    """One keypress as the raw string it sent, escape sequence included."""
    if termios is None:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # arrow prefix, the letter after it says which
            return {"H": "\x1b[A", "P": "\x1b[B", "M": "\x1b[C", "K": "\x1b[D"}.get(msvcrt.getwch(), "\x1b[?")
        return ch
    fd = sys.stdin.fileno()
    s = os.read(fd, 1)
    if s == b"\x1b" and select.select([fd], [], [], 0.05)[0]:  # the rest of the sequence, or a bare Esc
        s += os.read(fd, 2)  # an arrow is ESC [ X; anything typed behind it stays for the next key
    return s.decode(errors="replace")


def getkey():
    """up/down/left/right/space/enter/cancel, or the literal character."""
    try:
        k = _key()
    except (KeyboardInterrupt, EOFError):
        bail()
    return KEYS.get(k, k)


def bail():
    print(f"{SHOW}\n  {Y}! cancelled, nothing written{R}")
    sys.exit(130)


def q_ask(title):
    print(f"{M}?{R} {B}{title}{R}")


def q_done(lines, title, answer):
    """Collapse a finished question, `lines` tall, to one line."""
    print(f"\033[{lines}A\033[J{G}✔{R} {title} {D}›{R} {C}{answer}{R}")


def row(pointer, box, label, hint, hot):
    print(f"  {M}{pointer}{R} {box}{C if hot else ''}{label:<14}{R} {D}{hint}{R}\033[K")


def ask_select(title, items, default=1):
    """items are (label, hint); returns the 1-based choice."""
    sel, n, drawn = default, len(items), False
    with raw():
        q_ask(title)
        while True:
            if drawn:
                print(f"\033[{n}A", end="")
            drawn = True
            for i, (label, hint) in enumerate(items, 1):
                row("❯" if i == sel else " ", "", label, hint, i == sel)
            k = getkey()
            if k == "up":
                sel = sel - 1 or n
            elif k == "down":
                sel = sel % n + 1
            elif k == "enter":
                break
            elif k == "cancel":
                bail()
            elif k.isdigit() and 1 <= int(k) <= n:
                sel = int(k)
                break
    q_done(n + 1, title, items[sel - 1][0])
    return sel


def ask_multi(title, items, default=()):
    """items are (label, hint); returns the sorted 1-based picks, space toggled."""
    cur, n, picks, drawn = 1, len(items), set(default), False
    with raw():
        q_ask(title)
        while True:
            if drawn:
                print(f"\033[{n + 1}A", end="")
            drawn = True
            for i, (label, hint) in enumerate(items, 1):
                row("❯" if i == cur else " ", f"{G}◼ {R}" if i in picks else f"{D}◻ {R}", label, hint, i == cur)
            print(f"  {D}space toggles · enter accepts{R}\033[K")
            k = getkey()
            if k == "up":
                cur = cur - 1 or n
            elif k == "down":
                cur = cur % n + 1
            elif k == "space":
                picks ^= {cur}
            elif k == "enter":
                break
            elif k == "cancel":
                bail()
    picks = sorted(picks)
    q_done(n + 2, title, ", ".join(items[p - 1][0] for p in picks) or "none")
    return picks


def ask_yesno(title, default=True):
    yes, drawn = default, False
    with raw():
        q_ask(title)
        while True:
            if drawn:
                print("\033[1A", end="")
            drawn = True
            a, b = (C, D) if yes else (D, C)
            print(f"  {a}{'◉' if yes else '○'} yes{R}   {b}{'○' if yes else '◉'} no{R}\033[K")
            k = getkey()
            if k in ("left", "right", "up", "down", "space"):
                yes = not yes
            elif k in ("y", "Y", "n", "N"):
                yes = k in ("y", "Y")
                break
            elif k == "enter":
                break
            elif k == "cancel":
                bail()
    q_done(2, title, "yes" if yes else "no")
    return yes


def ask_path(src):
    """The target, typed, asked until it is a real directory that is not the checkout."""
    default = "" if Path.cwd() == src else str(Path.cwd())
    title = "install into which repo?"
    while True:
        try:
            a = input(f"{M}?{R} {B}{title}{R} {D}{f'({default})' if default else ''}{R} ").strip() or default
        except (EOFError, KeyboardInterrupt):
            bail()
        p = Path(a).expanduser()
        if not a:
            why = "a path is needed"
        elif not p.is_dir():
            why = "no such directory"
        elif p.resolve() == src:
            why = "that is the fornix checkout; pass the repo to install into"
        else:
            q_done(1, title, p.resolve())
            return p.resolve()
        print(f"  {Y}! {why}{R}")


def find_repos(root, depth=5):
    """Repos with an install (.fornix/setup.sh) up to `depth` directories below root."""
    found = []
    for d, dirs, _ in os.walk(root):
        d = Path(d)
        if d != root and ".fornix" in dirs and (d / ".fornix/setup.sh").is_file():
            found.append(d)
        deep = len(d.relative_to(root).parts) >= depth
        dirs[:] = [] if deep else sorted(n for n in dirs if not n.startswith(".") and n != "node_modules")
    return found


def set_root(root, yes):
    """Add every chosen repo below root to root's .mcp.json, via each repo's own setup.sh."""
    root = root.resolve()
    if not root.is_dir():
        sys.exit(f"install: no such directory: {root}")
    repos = find_repos(root)
    if not repos:
        sys.exit(f"install: no repo with a .fornix/ install within 5 levels below {root}")
    reg = root / ".claude/context-sync.repos"
    known = {line.split(" ", 1)[1] for line in reg.read_text().splitlines() if " " in line} if reg.is_file() else set()
    items = [(str(r.relative_to(root)), "already registered here" if str(r) in known else "") for r in repos]
    picks = list(range(1, len(items) + 1))
    if not yes and sys.stdin.isatty() and sys.stdout.isatty():
        print(f"\n{M}▌{R} {B}fornix{R} {D}workspace folder{R} {C}{root}{R}\n")
        picks = ask_multi("which repos should join this folder?", items, default=picks)
        if not picks:
            print(f"  {D}nothing picked, nothing done{R}")
            return
    for i in picks:  # ponytail: shells out to setup.sh; port its set_root here if Windows needs this
        try:
            subprocess.run(["sh", str(repos[i - 1] / ".fornix/setup.sh"), "--set-root", str(root)])
        except OSError:
            sys.exit(f"install: no sh on PATH; run {repos[i - 1]}/.fornix/setup.sh --set-root {root} from a shell that has one")


def release_ref():
    """--branch v<version> when installed from PyPI, so 0.1.1 installs the 0.1.1 tree.
    Nothing (main) when installed from a git URL or path: direct_url.json marks those."""
    try:
        dist = importlib.metadata.distribution("fornix")
    except importlib.metadata.PackageNotFoundError:
        return []
    return [] if dist.read_text("direct_url.json") else ["--branch", "v" + dist.version]


def source():
    """The checkout this file sits in, or a fresh shallow clone when installed as a tool."""
    src = Path(__file__).resolve().parent
    if (src / ".fornix").is_dir():
        return src
    tmp = tempfile.TemporaryDirectory(prefix="fornix-")
    atexit.register(tmp.cleanup)
    cmd = ["git", "clone", "--quiet", "--depth", "1", *release_ref(), REPO_URL, tmp.name]
    try:  # git still chatters on stderr for a shallow tag clone, so keep it unless it failed
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as e:
        why = (getattr(e, "stderr", None) or str(e)).strip()
        sys.exit(f"install: {src} is not a fornix checkout and cloning {REPO_URL} failed:\n{why}")
    return Path(tmp.name)


def main(argv=None):
    ap = argparse.ArgumentParser(usage=USAGE, description=DESCRIPTION,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", default="", metavar="TARGET_REPO")
    ap.add_argument("-y", "--yes", action="store_true")
    ap.add_argument("--no-hook", dest="hook", action="store_false", default=None)
    ap.add_argument("--set-root", action="store_true")
    for f in CLIENT_FLAGS:
        ap.add_argument(f, dest="clients", action="append_const", const=f, default=None)
    a = ap.parse_args(argv)
    got_clients = a.clients is not None
    clients = a.clients or []
    target = Path(a.target).expanduser() if a.target else None

    if a.set_root:
        return set_root(target or Path.cwd(), a.yes)

    src = source()

    if not a.yes and sys.stdin.isatty() and sys.stdout.isatty() and (
            target is None or a.hook is None or not got_clients):
        print(f"\n{M}▌{R} {B}fornix{R} {D}installer{R}\n")
        if target is None:
            target = ask_path(src)
        if a.hook is None:
            a.hook = ask_select("how should the sync loop stay on?", [
                ("hook + skill", "re-injected every prompt, survives compaction (recommended)"),
                ("skill only", "no hook installed, the skill alone drives it")]) == 1
        if not got_clients:
            picks = ask_multi("register the server with other clients?", [
                ("codex", "codex mcp add"), ("gemini", "gemini mcp add"),
                ("antigravity", "agy mcp add"), ("vs code", "code --add-mcp")])
            clients = [CLIENT_FLAGS[p] for p in picks]  # 1-based picks skip --claude at index 0
            print(f"  {D}claude code is covered by .mcp.json, written either way{R}")
        print(f"\n  {C}{target}{R} {D}·{R} hook {'on' if a.hook else 'off'} {D}·{R} clients {' '.join(clients) or 'none'}")
        if (target / ".fornix/memories").is_dir():
            print(f"  {D}an install is already there; .fornix/memories/ is kept as is{R}")
        print()
        if not ask_yesno("write it?"):
            print(f"  {Y}! cancelled, nothing written{R}")
            sys.exit(130)
        print()

    hook = True if a.hook is None else a.hook
    target = target or Path.cwd()
    if not target.is_dir():
        sys.exit(f"install: no such directory: {target}")
    target = target.resolve()
    if target == src:
        sys.exit("install: target is the source checkout; pass the repo to install into")

    print(f"{M}▌{R} {B}fornix{R} {D}→{R} {target}\n")

    # --- .context/ → .fornix/ ----------------------------------------------
    # Installs from before the rename keep the store in .context/. Move it whole so
    # memories/, .sync-on and the built index come along.
    old = target / ".context"
    if (old / "context_store").is_dir():
        if (target / ".fornix").exists():
            say(".context/", "skipped, .fornix/ is there too; move memories/ over by hand")
        else:
            old.rename(target / ".fornix")
            say(".fornix/", "moved from .context/")

    # --- .fornix/ ---------------------------------------------------------
    # Everything but memories/, which is the user's data and is handled separately below.
    def skip(d, names):
        top = Path(d) == src / ".fornix"
        return {n for n in names if n in ("__pycache__", ".DS_Store") or top and (
            n in (".venv", ".pytest_cache", ".sync-on", "memories") or n.startswith("index.db"))}
    shutil.copytree(src / ".fornix", target / ".fornix", ignore=skip, dirs_exist_ok=True)
    say(".fornix/", "server, store code, pyproject")

    # --- .fornix/memories/ ------------------------------------------------
    # If memories/ is already there we do not touch it at all. Only a fresh install gets the seeds.
    mem = target / ".fornix/memories"
    if mem.exists():
        if not mem.is_dir():
            sys.exit(f"install: {mem} exists but is not a directory")
        n = sum(1 for f in mem.rglob("*.jsonl") if f.is_file())
        say(".fornix/memories/", f"kept as is, {n} store{'' if n == 1 else 's'} already there")
    else:
        mem.mkdir(parents=True)
        seeds = sorted((src / ".fornix/memories").glob("*.jsonl"))
        for f in seeds:
            shutil.copy(f, mem)
        say(".fornix/memories/", "created, empty: " + " ".join(f.name for f in seeds))

    # --- .mcp.json ---------------------------------------------------------
    p = target / ".mcp.json"
    doc = load_json(p)
    servers = doc.setdefault("mcpServers", {})
    # the server was called "context", then "context-system", both run from .context/;
    # drop those keys so a re-install does not leave two processes on the same store
    stale = [k for k in ("context", "context-system") if (v := servers.get(k)) and v.get("command") == "uv"
             and any(".context" in str(x) for x in v.get("args", []))]
    for k in stale:
        del servers[k]
    if servers.get("fornix") == MCP_ENTRY and not stale:
        result = "already present"
    else:
        result = "replaced" if "fornix" in servers else "added"
        servers["fornix"] = MCP_ENTRY
        save_json(p, doc)
        result += "".join(f', legacy "{k}" entry removed' for k in stale)
    say(".mcp.json", f"mcpServers.fornix {result}")

    # --- skill and commands ------------------------------------------------
    skill = src / "skills/context-sync"
    cmds = sorted(skill.glob("commands/*.md"))
    (target / ".claude/skills/context-sync").mkdir(parents=True, exist_ok=True)
    (target / ".claude/commands").mkdir(parents=True, exist_ok=True)
    shutil.copy(skill / "SKILL.md", target / ".claude/skills/context-sync/SKILL.md")
    say(".claude/skills/context-sync/", "SKILL.md")
    # Older hand-installs nested commands/ and hooks/ under the skill, where nothing reads them.
    for old in ("commands", "hooks"):
        d = target / ".claude/skills/context-sync" / old
        if d.is_dir():
            shutil.rmtree(d)
            say(".claude/skills/context-sync/", f"removed stale {old}/")
    for f in cmds:
        shutil.copy(f, target / ".claude/commands")
    say(".claude/commands/", f"{len(cmds)} slash commands")

    # --- .agent/ -----------------------------------------------------------
    # The same skill and commands under the vendor-neutral tree some agents read.
    (target / ".agent/skills/context-sync").mkdir(parents=True, exist_ok=True)
    (target / ".agent/prompts").mkdir(parents=True, exist_ok=True)
    shutil.copy(skill / "SKILL.md", target / ".agent/skills/context-sync/SKILL.md")
    say(".agent/skills/context-sync/", "SKILL.md")
    for f in cmds:
        shutil.copy(f, target / ".agent/prompts")
    say(".agent/prompts/", f"{len(cmds)} prompts")

    # --- hook --------------------------------------------------------------
    if not hook:
        say(".claude/hooks/", "skipped (skill only)")
    else:
        (target / ".claude/hooks").mkdir(parents=True, exist_ok=True)
        h = target / ".claude/hooks/context-sync.sh"
        shutil.copy(skill / "hooks/context-sync.sh", h)
        h.chmod(h.stat().st_mode | 0o111)
        say(".claude/hooks/", "context-sync.sh")

        p = target / ".claude/settings.json"
        doc = load_json(p)
        groups = doc.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
        if any("context-sync.sh" in x.get("command", "") for g in groups for x in g.get("hooks", [])):
            result = "already registered"
        else:
            groups.append({"hooks": [{"type": "command", "command": HOOK_CMD, "timeout": 5}]})
            save_json(p, doc)
            result = "registered"
        say(".claude/settings.json", f"UserPromptSubmit hook {result}")

    # --- summary -----------------------------------------------------------
    print(f"\n  {G}{count['new']} updated{R} {D}·{R} {D}{count['same']} unchanged{R} {D}·{R} {Y}{count['skip']} skipped{R}")
    if not shutil.which("uv"):
        print(f"  {Y}! uv is not on PATH. The server needs it: https://docs.astral.sh/uv/{R}")

    sec("next, in that repo")
    print(f'  {M}1{R}  restart Claude Code and approve the "fornix" server (or /mcp)')
    print(f"  {M}2{R}  {C}/context-start-sync{R}            recall + capture every prompt")
    print(f"     {C}/context-start-sync-readonly{R}   recall only, never writes")
    print(f"     {C}/context-stop-sync{R}             off")
    print(f"  {M}3{R}  commit .fornix/memories/ with your code; the rest of .fornix/ is gitignored")

    # --- other agents ------------------------------------------------------
    # Claude Code reads .mcp.json, written above. Every other client is one command
    # away; setup.sh travels with .fornix/ so teammates without this checkout have it too.
    if clients:
        sec("registering with " + " ".join(clients))
        try:
            subprocess.run(["sh", str(target / ".fornix/setup.sh"), *clients])
        except OSError:
            print(f"  {Y}! no sh on PATH; run .fornix/setup.sh {' '.join(clients)} from a shell that has one{R}")
    else:
        sec("other clients")
    print(f"  .fornix/setup.sh                                   {D}asks: clients, workspace folder{R}")
    print(f"  .fornix/setup.sh --codex --set-root <folder>       {D}--print just lists the commands{R}")
    print(f"  {ap.prog} <folder> --set-root {' ' * max(0, 30 - len(ap.prog))}{D}finds the repos below a folder, asks which join{R}")


if __name__ == "__main__":
    main()
