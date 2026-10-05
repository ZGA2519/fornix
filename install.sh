#!/usr/bin/env sh
# Install fornix into a repo: store, MCP entry, skill, commands, hook.
# Idempotent — re-run to update an install. An existing .fornix/memories/ is never touched.
# Run with no answers on a terminal and it asks for them, vite-style; -y takes the defaults.
set -eu

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET=""
WANT_HOOK=""        # "" until answered, then 1 or 0
CLIENTS=""
GOT_CLIENTS=0       # 1 once a client flag was passed, so the wizard skips that question
ASSUME_YES=0
UPGRADE=0

usage() {
  cat <<'USAGE'
usage: ./install.sh [TARGET_REPO] [-y] [--no-hook] [--claude] [--codex] [--gemini] [--agy] [--vscode]
       ./install.sh [TARGET_REPO] --upgrade [--no-hook] [--claude] [--codex] [--gemini] [--agy] [--vscode]

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

--upgrade   update an install that is already there, without questions. One from
            before the rename (.context/) becomes .fornix/; if a .fornix/ is there
            too (a pull brought the renamed memories/), .context/memories/ is merged
            in by id and .context/ removed. Workspace folders that registered this
            repo are re-pointed at .fornix/. The hook stays as the install had it.
USAGE
}

for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --upgrade) UPGRADE=1; ASSUME_YES=1 ;;
    --no-hook) WANT_HOOK=0 ;;
    --claude|--codex|--gemini|--agy|--vscode) CLIENTS="$CLIENTS $arg"; GOT_CLIENTS=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "install: unknown option $arg" >&2; usage >&2; exit 2 ;;
    *)
      [ -z "$TARGET" ] || { echo "install: more than one target given" >&2; exit 2; }
      TARGET=$arg ;;
  esac
done

[ -d "$SRC/.fornix" ] || { echo "install: run this from a fornix checkout ($SRC has no .fornix/)" >&2; exit 1; }

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$(printf '\033[1m') D=$(printf '\033[2m') R=$(printf '\033[0m')
  C=$(printf '\033[36m') G=$(printf '\033[32m') Y=$(printf '\033[33m') M=$(printf '\033[35m')
else
  B= D= R= C= G= Y= M=
fi

# --- prompts ---------------------------------------------------------------
# A tiny vite-style wizard in POSIX sh: one byte at a time off the tty, arrows to
# move, space to toggle, enter to accept. Only asked for what the flags left open.
TTY=/dev/tty
NL=$(printf '\n') CR=$(printf '\r') TAB=$(printf '\t') XESC=$(printf '\033')
STTY_SAVED=""

raw_on() {
  STTY_SAVED=$(stty -g <$TTY)
  # drop anything typed while the last question was closing, so it cannot echo
  # into the frame we are about to draw and throw the cursor arithmetic off
  stty -icanon -echo min 0 time 0 <$TTY
  _drain=0
  while [ "$_drain" -lt 64 ] && [ -n "$(_byte)" ]; do _drain=$((_drain+1)); done
  stty -icanon -echo min 1 time 0 <$TTY
  printf '\033[?25l'
}
raw_off() {
  [ -n "$STTY_SAVED" ] || return 0
  printf '\033[?25h'
  # shellcheck disable=SC2086  # stty -g is a word list on some platforms
  stty $STTY_SAVED <$TTY
  STTY_SAVED=""
}
bail() { raw_off; printf '\n  %s! cancelled, nothing written%s\n' "$Y" "$R"; exit 130; }

# one raw byte, newline included (the X sentinel survives $() stripping it)
_byte() { _b=$(dd bs=1 count=1 2>/dev/null <$TTY; printf X); printf %s "${_b%X}"; }
# getkey: KEY becomes up/down/enter/space/cancel, or the literal character
getkey() {
  KEY=$(_byte)
  case $KEY in
    "$XESC")
      stty -icanon -echo min 0 time 1 <$TTY     # the rest of the sequence, or nothing
      _a=$(_byte) _c=$(_byte)
      stty -icanon -echo min 1 time 0 <$TTY
      case "$_a$_c" in
        '[A'|OA) KEY=up ;; '[B'|OB) KEY=down ;;
        '[C'|OC) KEY=right ;; '[D'|OD) KEY=left ;;
        '') KEY=cancel ;; *) KEY=other ;;
      esac ;;
    "$NL"|"$CR"|'') KEY=enter ;;
    ' ') KEY=space ;;
    "$TAB") KEY=down ;;
    k) KEY=up ;; j) KEY=down ;; q) KEY=cancel ;;
  esac
}
# nth <i> <item...>: the i-th item
nth() { _i=$1; shift; while [ "$_i" -gt 1 ]; do shift; _i=$((_i-1)); done; printf %s "$1"; }
q_ask()  { printf '%s?%s %s%s%s\n' "$M" "$R" "$B" "$1" "$R"; }
# q_done <lines-to-erase> <title> <answer>: collapse a finished question to one line
q_done() { printf '\033[%dA\033[J%s✔%s %s %s›%s %s%s%s\n' "$1" "$G" "$R" "$2" "$D" "$R" "$C" "$3" "$R"; }
# row <pointer> <box, may be empty> <label|hint> [label colour]
row() {
  _lab=${3%%|*} _hint=${3#*|}; [ "$_hint" != "$3" ] || _hint=""
  printf '  %s%s%s %s%s%-14s%s %s%s%s\033[K\n' \
    "$M" "$1" "$R" "$2" "${4:-}" "$_lab" "$R" "$D" "$_hint" "$R"
}

# ask_select <title> <label|hint>...  -> SELECT is the 1-based choice
ask_select() {
  _t=$1; shift; _n=$#; _sel=1 _drawn=0
  raw_on
  q_ask "$_t"
  while :; do
    [ "$_drawn" = 0 ] || printf '\033[%dA' "$_n"
    _drawn=1 _i=0
    for _o in "$@"; do
      _i=$((_i+1))
      if [ "$_i" = "$_sel" ]; then row '❯' '' "$_o" "$C"; else row ' ' '' "$_o"; fi
    done
    getkey
    case $KEY in
      up)     _sel=$((_sel-1)); [ "$_sel" -ge 1 ] || _sel=$_n ;;
      down)   _sel=$((_sel+1)); [ "$_sel" -le "$_n" ] || _sel=1 ;;
      enter)  break ;;
      cancel) bail ;;
      [1-9])  [ "$KEY" -le "$_n" ] && _sel=$KEY && break ;;
    esac
  done
  raw_off
  _lab=$(nth "$_sel" "$@"); q_done $((_n+1)) "$_t" "${_lab%%|*}"
  SELECT=$_sel
}

# ask_multi <title> <label|hint>...  -> MULTI is the chosen indices, space separated
ask_multi() {
  _t=$1; shift; _n=$#; _cur=1 _picks="" _drawn=0
  raw_on
  q_ask "$_t"
  while :; do
    [ "$_drawn" = 0 ] || printf '\033[%dA' "$((_n+1))"
    _drawn=1 _i=0
    for _o in "$@"; do
      _i=$((_i+1))
      case " $_picks " in
        *" $_i "*) _box="${G}◼ ${R}" ;;
        *)         _box="${D}◻ ${R}" ;;
      esac
      if [ "$_i" = "$_cur" ]; then row '❯' "$_box" "$_o" "$C"; else row ' ' "$_box" "$_o"; fi
    done
    printf '  %sspace toggles · enter accepts%s\033[K\n' "$D" "$R"
    getkey
    case $KEY in
      up)     _cur=$((_cur-1)); [ "$_cur" -ge 1 ] || _cur=$_n ;;
      down)   _cur=$((_cur+1)); [ "$_cur" -le "$_n" ] || _cur=1 ;;
      space)
        case " $_picks " in
          *" $_cur "*) _keep=""; for _p in $_picks; do [ "$_p" = "$_cur" ] || _keep="$_keep $_p"; done; _picks=$_keep ;;
          *) _picks="$_picks $_cur" ;;
        esac ;;
      enter)  break ;;
      cancel) bail ;;
    esac
  done
  raw_off
  _sum=""
  for _p in $_picks; do _lab=$(nth "$_p" "$@"); _sum="$_sum${_sum:+, }${_lab%%|*}"; done
  q_done $((_n+2)) "$_t" "${_sum:-none}"
  MULTI=$_picks
}

# ask_yesno <title> <default 1|0>  -> YESNO is 1 or 0
ask_yesno() {
  _t=$1 _yes=$2 _drawn=0
  raw_on
  q_ask "$_t"
  while :; do
    [ "$_drawn" = 0 ] || printf '\033[1A'
    _drawn=1
    if [ "$_yes" = 1 ]; then printf '  %s◉ yes%s   %s○ no%s\033[K\n' "$C" "$R" "$D" "$R"
    else printf '  %s○ yes%s   %s◉ no%s\033[K\n' "$D" "$R" "$C" "$R"; fi
    getkey
    case $KEY in
      left|right|up|down|space) [ "$_yes" = 1 ] && _yes=0 || _yes=1 ;;
      y|Y) _yes=1; break ;;
      n|N) _yes=0; break ;;
      enter) break ;;
      cancel) bail ;;
    esac
  done
  raw_off
  [ "$_yes" = 1 ] && _a=yes || _a=no
  q_done 2 "$_t" "$_a"
  YESNO=$_yes
}

# ask_path: TARGET, asked until it is a real directory that is not this checkout
ask_path() {
  _def=$PWD; [ "$_def" != "$SRC" ] || _def=""
  while :; do
    printf '%s?%s %s%s%s %s%s%s ' "$M" "$R" "$B" "install into which repo?" "$R" \
      "$D" "${_def:+($_def)}" "$R"
    IFS= read -r _ans <$TTY || bail
    [ -n "$_ans" ] || _ans=$_def
    case $_ans in '~') _ans=$HOME ;; '~/'*) _ans=$HOME/${_ans#'~/'} ;; esac
    _why=""
    if [ -z "$_ans" ]; then _why="a path is needed"
    elif [ ! -d "$_ans" ]; then _why="no such directory"
    else
      _ans=$(CDPATH= cd -- "$_ans" && pwd)
      [ "$_ans" != "$SRC" ] || _why="that is the fornix checkout; pass the repo to install into"
    fi
    if [ -n "$_why" ]; then printf '  %s! %s%s\n' "$Y" "$_why" "$R"; continue; fi
    printf '\033[1A\033[J%s✔%s install into which repo? %s›%s %s%s%s\n' \
      "$G" "$R" "$D" "$R" "$C" "$_ans" "$R"
    TARGET=$_ans
    return 0
  done
}

WIZARD=0
if [ "$ASSUME_YES" = 0 ] && [ -t 1 ] && [ -r $TTY ] &&
   { [ -z "$TARGET" ] || [ -z "$WANT_HOOK" ] || [ "$GOT_CLIENTS" = 0 ]; }; then
  WIZARD=1
fi

if [ "$WIZARD" = 1 ]; then
  trap 'raw_off' EXIT HUP TERM
  trap 'bail' INT
  printf '\n%s▌%s %sfornix%s %sinstaller%s\n\n' "$M" "$R" "$B" "$R" "$D" "$R"

  [ -n "$TARGET" ] || ask_path

  if [ -z "$WANT_HOOK" ]; then
    ask_select "how should the sync loop stay on?" \
      'hook + skill|re-injected every prompt, survives compaction (recommended)' \
      'skill only|no hook installed, the skill alone drives it'
    [ "$SELECT" = 1 ] && WANT_HOOK=1 || WANT_HOOK=0
  fi

  if [ "$GOT_CLIENTS" = 0 ]; then
    ask_multi "register the server with other clients?" \
      'codex|codex mcp add' \
      'gemini|gemini mcp add' \
      'antigravity|agy mcp add' \
      'vs code|code --add-mcp'
    _i=0
    for _f in --codex --gemini --agy --vscode; do
      _i=$((_i+1))
      case " $MULTI " in *" $_i "*) CLIENTS="$CLIENTS $_f" ;; esac
    done
    printf '  %sclaude code is covered by .mcp.json, written either way%s\n' "$D" "$R"
  fi

  printf '\n  %s%s%s %s·%s hook %s %s·%s clients%s\n' \
    "$C" "$TARGET" "$R" "$D" "$R" "$([ "$WANT_HOOK" = 1 ] && echo on || echo off)" \
    "$D" "$R" "${CLIENTS:- none}"
  [ ! -d "$TARGET/.fornix/memories" ] ||
    printf '  %san install is already there; .fornix/memories/ is kept as is%s\n' "$D" "$R"
  echo
  ask_yesno "write it?" 1
  [ "$YESNO" = 1 ] || { printf '  %s! cancelled, nothing written%s\n' "$Y" "$R"; exit 130; }
  echo
fi

[ -n "$TARGET" ] || TARGET=$PWD
[ -d "$TARGET" ] || { echo "install: no such directory: $TARGET" >&2; exit 1; }
TARGET=$(CDPATH= cd -- "$TARGET" && pwd)
if [ "$TARGET" = "$SRC" ]; then
  echo "install: target is the source checkout; pass the repo to install into" >&2
  exit 1
fi
if [ "$UPGRADE" = 1 ]; then
  [ -d "$TARGET/.context/context_store" ] || [ -d "$TARGET/.fornix/context_store" ] ||
    { echo "install: nothing to upgrade in $TARGET; run without --upgrade to install" >&2; exit 1; }
  # keep the choice the old install made
  [ -n "$WANT_HOOK" ] || { [ -f "$TARGET/.claude/hooks/context-sync.sh" ] && WANT_HOOK=1 || WANT_HOOK=0; }
fi
[ -n "$WANT_HOOK" ] || WANT_HOOK=1

HAVE_PY=1; command -v python3 >/dev/null 2>&1 || HAVE_PY=0
HOOK_CMD='"$CLAUDE_PROJECT_DIR"/.claude/hooks/context-sync.sh'

n_new=0 n_same=0 n_skip=0
# sec <title>: section header
sec() { printf '\n%s▌%s %s%s%s\n' "$M" "$R" "$B" "$1" "$R"; }
# say <path> <status>: one row; glyph and color follow the status verb, counted for the summary
say() {
  case $2 in
    *already*|kept*)  g="${D}•" c=$D n_same=$((n_same+1)) ;;
    skipped*)         g="${Y}!" c=$Y n_skip=$((n_skip+1)) ;;
    *added*|*registered|*created*|*replaced*|removed*) g="${G}✔" c=$G n_new=$((n_new+1)) ;;
    *)                g="${G}✔" c=   n_new=$((n_new+1)) ;;
  esac
  printf '  %s%s %s%-28s%s %s%s%s\n' "$g" "$R" "$C" "$1" "$R" "$c" "$2" "$R"
}
printf '%s▌%s %sfornix%s %s→%s %s\n\n' "$M" "$R" "$B" "$R" "$D" "$R" "$TARGET"

# --- .context/ → .fornix/ --------------------------------------------------
# Installs from before the rename keep the store in .context/. Move it whole so
# memories/, .sync-on and the built index come along.
# With --upgrade, a .fornix/ that is already there (a teammate's rename pulled in
# memories/) gets .context/memories/ merged in by id, and .context/ goes.
MOVED=0
if [ -d "$TARGET/.context/context_store" ]; then
  if [ ! -e "$TARGET/.fornix" ]; then
    mv "$TARGET/.context" "$TARGET/.fornix"
    MOVED=1
    say .fornix/ "moved from .context/"
  elif [ "$UPGRADE" = 0 ]; then
    say .context/ "skipped, .fornix/ is there too; re-run with --upgrade to merge it in"
  elif [ "$HAVE_PY" = 0 ]; then
    say .context/ "skipped, no python3 to merge memories/ with; move them over by hand"
  else
    merged=$(python3 - "$SRC" "$TARGET/.context/memories" "$TARGET/.fornix/memories" <<'PY'
import pathlib, sys
sys.path.insert(0, sys.argv[1])
from setup import merge_memories  # the one merge, shared with setup.py
print(*merge_memories(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])))
PY
)
    added=${merged% *} clashes=${merged#* }
    [ ! -f "$TARGET/.context/.sync-on" ] || [ -e "$TARGET/.fornix/.sync-on" ] ||
      cp "$TARGET/.context/.sync-on" "$TARGET/.fornix/.sync-on"
    if [ "$clashes" = 0 ]; then
      rm -rf "$TARGET/.context"
      MOVED=1
      say .fornix/memories/ "merged $added from .context/, .context/ removed"
    else
      say .context/ "skipped removal, $clashes memories differ from .fornix/; compare by hand"
    fi
  fi
fi

# --- .fornix/ -------------------------------------------------------------
# Everything but memories/, which is the user's data and is handled separately below.
(cd "$SRC" && tar cf - \
    --exclude '.fornix/.venv' \
    --exclude '.fornix/index.db*' \
    --exclude '.fornix/.pytest_cache' \
    --exclude '.fornix/.sync-on' \
    --exclude '.fornix/memories' \
    --exclude '*/__pycache__' \
    --exclude '*.DS_Store' \
    .fornix) | (cd "$TARGET" && tar xf -)
say .fornix/ "server, store code, pyproject"

# --- .fornix/memories/ ----------------------------------------------------
# The user's data. If memories/ is already there we do not touch it at all: no
# seeding, no merging, no new files. Only a fresh install gets the seed stores.
if [ -e "$TARGET/.fornix/memories" ]; then
  [ -d "$TARGET/.fornix/memories" ] || {
    echo "install: $TARGET/.fornix/memories exists but is not a directory" >&2
    exit 1
  }
  n=$(find "$TARGET/.fornix/memories" -type f -name '*.jsonl' | wc -l | tr -d ' ')
  say .fornix/memories/ "kept as is, $n store$([ "$n" = 1 ] || echo s) already there"
else
  mkdir -p "$TARGET/.fornix/memories"
  stores=""
  for f in "$SRC"/.fornix/memories/*.jsonl; do
    [ -e "$f" ] || continue
    cp "$f" "$TARGET/.fornix/memories/"
    stores="$stores $(basename -- "$f")"
  done
  say .fornix/memories/ "created, empty:$stores"
fi

# --- .mcp.json -------------------------------------------------------------
if [ "$HAVE_PY" = 1 ]; then
  result=$(python3 - "$TARGET/.mcp.json" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
doc = {}
if p.exists() and p.read_text().strip():
    try:
        doc = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"{p} is not valid JSON ({e}); fix or move it and re-run")
want = {"command": "uv", "args": ["run", "--directory", ".fornix", "python", "-m", "context_store.server", "mcp"]}
servers = doc.setdefault("mcpServers", {})
# the server was called "context", then "context-system", both run from .context/;
# drop those keys so a re-install does not leave two processes on the same store
stale = [k for k in ("context", "context-system") if (v := servers.get(k)) and v.get("command") == "uv"
         and any(".context" in str(a) for a in v.get("args", []))]
for k in stale:
    del servers[k]
if servers.get("fornix") == want and not stale:
    print("already present")
else:
    verb = "replaced" if "fornix" in servers else "added"
    servers["fornix"] = want
    p.write_text(json.dumps(doc, indent=2) + "\n")
    print(verb + "".join(f', legacy "{k}" entry removed' for k in stale))
PY
)
  say .mcp.json "mcpServers.fornix $result"
else
  say .mcp.json "skipped, no python3. add by hand:" >&2
  echo '    {"mcpServers": {"fornix": {"command": "uv", "args": ["run", "--directory", ".fornix", "python", "-m", "context_store.server", "mcp"]}}}' >&2
fi

# --- skill and commands ----------------------------------------------------
mkdir -p "$TARGET/.claude/skills/context-sync" "$TARGET/.claude/commands"
cp "$SRC/skills/context-sync/SKILL.md" "$TARGET/.claude/skills/context-sync/SKILL.md"
say .claude/skills/context-sync/ SKILL.md
# Older hand-installs nested commands/ and hooks/ under the skill, where nothing
# reads them. The real copies go to .claude/commands and .claude/hooks below.
for stale in commands hooks; do
  d="$TARGET/.claude/skills/context-sync/$stale"
  if [ -d "$d" ]; then
    rm -rf "$d"
    say .claude/skills/context-sync/ "removed stale $stale/"
  fi
done
cp "$SRC"/skills/context-sync/commands/*.md "$TARGET/.claude/commands/"
ncmd=$(ls -1 "$SRC"/skills/context-sync/commands/*.md | wc -l | tr -d ' ')
say .claude/commands/ "$ncmd slash commands"

# --- .agent/ ---------------------------------------------------------------
# The same skill and commands under the vendor-neutral tree some agents read.
# Commands are called prompts there, so they land in .agent/prompts/.
mkdir -p "$TARGET/.agent/skills/context-sync" "$TARGET/.agent/prompts"
cp "$SRC/skills/context-sync/SKILL.md" "$TARGET/.agent/skills/context-sync/SKILL.md"
say .agent/skills/context-sync/ SKILL.md
cp "$SRC"/skills/context-sync/commands/*.md "$TARGET/.agent/prompts/"
say .agent/prompts/ "$ncmd prompts"

# --- hook ------------------------------------------------------------------
if [ "$WANT_HOOK" = 0 ]; then
  say .claude/hooks/ "skipped (skill only)"
else
  mkdir -p "$TARGET/.claude/hooks"
  cp "$SRC/skills/context-sync/hooks/context-sync.sh" "$TARGET/.claude/hooks/context-sync.sh"
  chmod +x "$TARGET/.claude/hooks/context-sync.sh"
  say .claude/hooks/ context-sync.sh

  if [ "$HAVE_PY" = 1 ]; then
    result=$(python3 - "$TARGET/.claude/settings.json" "$HOOK_CMD" <<'PY'
import json, pathlib, sys
p, cmd = pathlib.Path(sys.argv[1]), sys.argv[2]
doc = {}
if p.exists() and p.read_text().strip():
    try:
        doc = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"{p} is not valid JSON ({e}); fix or move it and re-run")
groups = doc.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
if any("context-sync.sh" in h.get("command", "")
        for g in groups for h in g.get("hooks", [])):
    print("already registered")
else:
    groups.append({"hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
    p.write_text(json.dumps(doc, indent=2) + "\n")
    print("registered")
PY
)
    say .claude/settings.json "UserPromptSubmit hook $result"
  else
    say .claude/settings.json "skipped, no python3. merge skills/context-sync/hooks/settings-snippet.json by hand" >&2
  fi
fi

# --- workspace folders -----------------------------------------------------
# A folder above this repo that registered it still points at .context/; its own
# set_root re-registers the repo under .fornix/ and drops the stale entry.
lists_target() { while IFS= read -r _l; do [ "${_l#* }" != "$TARGET" ] || return 0; done < "$1"; return 1; }
if [ "$UPGRADE" = 1 ] || [ "$MOVED" = 1 ]; then
  _d=$TARGET
  while [ "$_d" != / ]; do
    _d=${_d%/*}; [ -n "$_d" ] || _d=/
    if [ -f "$_d/.claude/context-sync.repos" ] && lists_target "$_d/.claude/context-sync.repos"; then
      sec "workspace folder $_d"
      sh "$TARGET/.fornix/setup.sh" --set-root "$_d" || true
    fi
  done
fi

# --- summary ---------------------------------------------------------------
printf '\n  %s%s updated%s %s·%s %s%s unchanged%s %s·%s %s%s skipped%s\n' \
  "$G" "$n_new" "$R" "$D" "$R" "$D" "$n_same" "$R" "$D" "$R" "$Y" "$n_skip" "$R"
command -v uv >/dev/null 2>&1 || printf '  %s! uv is not on PATH. The server needs it: https://docs.astral.sh/uv/%s\n' "$Y" "$R"

sec "next, in that repo"
printf '  %s1%s  restart Claude Code and approve the "fornix" server (or /mcp)\n' "$M" "$R"
printf '  %s2%s  %s/context-start-sync%s            recall + capture every prompt\n' "$M" "$R" "$C" "$R"
printf '     %s/context-start-sync-readonly%s   recall only, never writes\n' "$C" "$R"
printf '     %s/context-stop-sync%s             off\n' "$C" "$R"
printf '  %s3%s  commit .fornix/memories/ with your code; the rest of .fornix/ is gitignored\n' "$M" "$R"

# --- other agents ----------------------------------------------------------
# Claude Code reads .mcp.json, written above. Every other client is one command
# away; setup.sh travels with .fornix/ so teammates without this checkout have it too.
if [ -n "$CLIENTS" ]; then
  sec "registering with$CLIENTS"
  # shellcheck disable=SC2086  # CLIENTS is a flag list, splitting is the point
  sh "$TARGET/.fornix/setup.sh" $CLIENTS
else
  sec "other clients"
fi
printf '  .fornix/setup.sh                                   %sasks: clients, workspace folder%s\n' "$D" "$R"
printf '  .fornix/setup.sh --codex --set-root <folder>       %s--print just lists the commands%s\n' "$D" "$R"
