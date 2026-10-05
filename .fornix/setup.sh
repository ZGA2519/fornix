#!/usr/bin/env sh
# Register this folder's MCP server with a client, or add the repo to a workspace folder.
#   .fornix/setup.sh                    ask what to do; --print only lists the commands
#   .fornix/setup.sh --codex --gemini   run those; flags: --claude --codex --gemini --agy --vscode
#   .fornix/setup.sh --set-root ..      add this repo to the workspace folder above it
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)   # /abs/path/to/repo/.fornix
REPO=${HERE%/*}
NAME=fornix
UV=$(command -v uv || echo uv)
HAVE_PY=1; command -v python3 >/dev/null 2>&1 || HAVE_PY=0

usage() { sed -n '2,5p' "$0"; }

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$(printf '\033[1m') D=$(printf '\033[2m') R=$(printf '\033[0m')
  C=$(printf '\033[36m') G=$(printf '\033[32m') Y=$(printf '\033[33m') M=$(printf '\033[35m')
else
  B= D= R= C= G= Y= M=
fi

# --- prompts ---------------------------------------------------------------
# The same vite-style wizard install.sh uses, carried here rather than shared:
# this script ships inside .fornix/ to people who have no fornix
# checkout, so it has to stand on its own. One byte at a time off the tty,
# arrows to move, space to toggle, enter to accept.
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
bail() { raw_off; printf '\n  %s! cancelled, nothing registered%s\n' "$Y" "$R"; exit 130; }

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

# ask_dir <title> <default> -> ANSWER, asked until it is a folder that is not this repo
ask_dir() {
  _t=$1 _def=$2
  while :; do
    printf '%s?%s %s%s%s %s(%s)%s ' "$M" "$R" "$B" "$_t" "$R" "$D" "$_def" "$R"
    IFS= read -r _ans <$TTY || bail
    [ -n "$_ans" ] || _ans=$_def
    case $_ans in '~') _ans=$HOME ;; '~/'*) _ans=$HOME/${_ans#'~/'} ;; esac
    _why=""
    if [ ! -d "$_ans" ]; then _why="no such folder"
    else
      _ans=$(CDPATH= cd -- "$_ans" && pwd)
      [ "$_ans" != "$REPO" ] && [ "$_ans" != "$HERE" ] ||
        _why="that is this repo; the workspace folder is the one you open in the editor"
    fi
    if [ -n "$_why" ]; then printf '  %s! %s%s\n' "$Y" "$_why" "$R"; continue; fi
    printf '\033[1A\033[J%s✔%s %s %s›%s %s%s%s\n' "$G" "$R" "$_t" "$D" "$R" "$C" "$_ans" "$R"
    ANSWER=$_ans
    return 0
  done
}

# --- workspace root --------------------------------------------------------
# One store per repo, but one editor window over many repos: each repo registers
# itself into the folder above as fornix-<repo>, absolute paths so the
# server starts from anywhere, and the root gets the skill, the commands and the
# hook. .claude/context-sync.repos is how the hook finds the member repos.
set_root() {
  root=$1
  case $root in '~') root=$HOME ;; '~/'*) root=$HOME/${root#'~/'} ;; esac
  [ -d "$root" ] || { echo "setup: no such folder: $root" >&2; exit 1; }
  root=$(CDPATH= cd -- "$root" && pwd)
  [ "$root" != "$REPO" ] && [ "$root" != "$HERE" ] || {
    echo "setup: --set-root wants the folder you open in the editor, not the repo itself" >&2
    exit 1
  }
  printf '\n%s▌%s %s%s%s %s→%s %s\n' "$M" "$R" "$B" "$REPO" "$R" "$D" "$R" "$root"
  case $REPO in
    "$root"/*) ;;
    *) printf '  %s! this repo is not inside that folder; registering it anyway%s\n' "$Y" "$R" ;;
  esac

  base=$(basename -- "$REPO")
  slug=$(printf %s "$base" | tr -cs 'A-Za-z0-9_-' '-')
  alt=$(printf %s "$(basename -- "$(dirname -- "$REPO")")-$base" | tr -cs 'A-Za-z0-9_-' '-')
  [ -n "$slug" ] || slug=repo

  if [ "$HAVE_PY" = 0 ]; then
    echo "  no python3, so add this to $root/.mcp.json under mcpServers by hand:"
    echo "  \"$NAME-$slug\": {\"command\": \"uv\", \"args\": [\"run\", \"--directory\", \"$HERE\", \"python\", \"-m\", \"context_store.server\", \"mcp\"]}"
    return 0
  fi

  # picks the server name too: <repo> normally, <parent>-<repo> if another folder
  # already took that name in this root
  out=$(python3 - "$root/.mcp.json" "$HERE" "$NAME-$slug" "$NAME-$alt" <<'PY'
import json, pathlib, sys
p, here, pref, alt = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
doc = {}
if p.exists() and p.read_text().strip():
    try:
        doc = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"{p} is not valid JSON ({e}); fix or move it and re-run")
want = {"command": "uv", "args": ["run", "--directory", here, "python", "-m", "context_store.server", "mcp"]}
servers = doc.setdefault("mcpServers", {})

def directory(entry):
    args = entry.get("args", []) if isinstance(entry, dict) else []
    return args[args.index("--directory") + 1] if "--directory" in args[:-1] else None

def free(cand):
    if cand not in servers:
        return True
    d = directory(servers[cand])
    # ours, or a leftover pointing at a folder that is not there any more
    return d == here or (d is not None and not pathlib.Path(d).is_dir())

# this repo's entry from before .context/ became .fornix/, under its old name
moved = [k for k, v in servers.items() if directory(v) == here[:-len(".fornix")] + ".context"]
for k in moved:
    del servers[k]
name = next((c for c in (pref, alt) if free(c)), None)
if name is None:
    sys.exit(f"{pref} and {alt} are both taken in {p} by other folders; edit it by hand")
dead = [k for k, v in servers.items()
        if k.startswith(("fornix", "context-system")) and (d := directory(v)) and not pathlib.Path(d).is_dir()]
if dead:
    print("  note: these servers point at folders that are gone, drop them from",
          p, "when you get a chance:", ", ".join(dead), file=sys.stderr)
if servers.get(name) == want and not moved:
    print(name, "already present")
else:
    verb = "updated" if name in servers else "added"
    servers[name] = want
    p.write_text(json.dumps(doc, indent=2) + "\n")
    print(name, verb)
PY
)
  server=${out%% *}
  printf '  %s.mcp.json%s                   %s\n' "$C" "$R" "$out"

  # the skill and the commands, straight from this repo's copies
  if [ -f "$REPO/.claude/skills/context-sync/SKILL.md" ]; then
    mkdir -p "$root/.claude/skills/context-sync" "$root/.claude/commands"
    cp "$REPO/.claude/skills/context-sync/SKILL.md" "$root/.claude/skills/context-sync/SKILL.md"
    cp "$REPO"/.claude/commands/context-*.md "$root/.claude/commands/" 2>/dev/null || true
    printf '  %s.claude/%s                    skill + commands copied\n' "$C" "$R"
  else
    printf '  %s.claude/%s                    %sskipped, no .claude/skills/context-sync in this repo (run install.sh there first)%s\n' "$C" "$R" "$Y" "$R"
  fi

  # the hook, only if this repo runs one
  if [ -f "$REPO/.claude/hooks/context-sync.sh" ]; then
    mkdir -p "$root/.claude/hooks"
    cp "$REPO/.claude/hooks/context-sync.sh" "$root/.claude/hooks/context-sync.sh"
    chmod +x "$root/.claude/hooks/context-sync.sh"
    if [ "$HAVE_PY" = 1 ]; then
      hook=$(python3 - "$root/.claude/settings.json" '"$CLAUDE_PROJECT_DIR"/.claude/hooks/context-sync.sh' <<'PY'
import json, pathlib, sys
p, cmd = pathlib.Path(sys.argv[1]), sys.argv[2]
doc = {}
if p.exists() and p.read_text().strip():
    try:
        doc = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"{p} is not valid JSON ({e}); fix or move it and re-run")
groups = doc.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
if any("context-sync.sh" in h.get("command", "") for g in groups for h in g.get("hooks", [])):
    print("already registered")
else:
    groups.append({"hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
    p.write_text(json.dumps(doc, indent=2) + "\n")
    print("registered")
PY
)
      printf '  %s.claude/settings.json%s       UserPromptSubmit hook %s\n' "$C" "$R" "$hook"
    fi
  fi

  # the member list the hook reads: "<server> <repo path>", one line per repo,
  # rewritten so a re-run cannot leave this repo in twice under two names
  reg=$root/.claude/context-sync.repos
  mkdir -p "$root/.claude"
  tmp=$reg.$$
  : > "$tmp"
  if [ -f "$reg" ]; then
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      if [ "${line%% *}" != "$server" ] && [ "${line#* }" != "$REPO" ]; then
        printf '%s\n' "$line" >> "$tmp"
      fi
    done < "$reg"
  fi
  printf '%s %s\n' "$server" "$REPO" >> "$tmp"
  mv "$tmp" "$reg"
  n=$(wc -l < "$reg" | tr -d ' ')
  printf '  %s.claude/context-sync.repos%s  %s repo%s registered here\n' "$C" "$R" "$n" "$([ "$n" = 1 ] || echo s)"
  printf '\n  open %s%s%s, approve %s"%s"%s, then %s/context-start-sync%s\n' \
    "$C" "$root" "$R" "$B" "$server" "$R" "$C" "$R"
}

# run <label> <cmd...>: execute, or print when in print mode or the client is not installed
run() {
  label=$1; shift
  if [ "$DO" = 1 ] && command -v "$1" >/dev/null 2>&1; then
    printf '+ %s\n' "$*"; "$@" || printf '  %s: exited %s (already registered?)\n' "$label" "$?"; return
  fi
  [ "$DO" = 1 ] && printf '  %-12s not on PATH, run later:\n   ' "$label" || printf '  %-12s' "$label"
  for x; do case $x in *' '*|*'"'*) printf " '%s'" "$x" ;; *) printf ' %s' "$x" ;; esac; done
  echo
}

# --- the wizard ------------------------------------------------------------
# Bare on a terminal: ask. Bare in a pipe or with --print: the old listing.
have() { command -v "$1" >/dev/null 2>&1 && printf '%s' "$2" || printf 'not on PATH'; }
wizard() {
  trap 'raw_off' EXIT HUP TERM
  trap 'bail' INT
  printf '\n%s▌%s %sfornix%s %s%s%s\n\n' "$M" "$R" "$B" "$R" "$D" "$REPO" "$R"

  claude_hint="project scoped, into .mcp.json"
  ! grep -qs "\"$NAME\"" "$REPO/.mcp.json" || claude_hint="already in .mcp.json"
  ask_multi "which clients should launch this repo's server?" \
    "claude code|$claude_hint" \
    "codex|$(have codex 'codex mcp add')" \
    "gemini|$(have gemini 'gemini mcp add')" \
    "antigravity|$(have agy 'agy mcp add')" \
    "vs code|$(have code 'code --add-mcp')"
  _i=0
  for _f in --claude --codex --gemini --agy --vscode; do
    _i=$((_i+1))
    case " $MULTI " in *" $_i "*) WANT="$WANT $_f" ;; esac
  done

  parent=$(dirname -- "$REPO")
  _def=0
  [ ! -f "$parent/.claude/context-sync.repos" ] || _def=1   # already a workspace folder
  ask_yesno "also add this repo to a workspace folder you open in the editor?" "$_def"
  if [ "$YESNO" = 1 ]; then
    ask_dir "which folder?" "$parent"
    ROOT=$ANSWER
  fi

  WANT=${WANT# }
  if [ -z "$WANT" ] && [ -z "$ROOT" ]; then
    printf '\n  %snothing picked, nothing done%s\n' "$D" "$R"
    exit 0
  fi
  printf '\n  %-8s%s%s%s\n' clients "$C" "${WANT:-none}" "$R"
  [ -z "$ROOT" ] || printf '  %-8s%s%s%s %s(as %s-%s)%s\n' folder "$C" "$ROOT" "$R" \
    "$D" "$NAME" "$(printf %s "$(basename -- "$REPO")" | tr -cs 'A-Za-z0-9_-' '-')" "$R"
  echo
  ask_yesno "go?" 1
  [ "$YESNO" = 1 ] || { printf '  %s! cancelled, nothing registered%s\n' "$Y" "$R"; exit 130; }
}

DO=1
WANT="" ROOT=""
if [ $# -eq 0 ]; then
  if [ -t 1 ] && [ -r $TTY ]; then
    wizard
    # shellcheck disable=SC2086  # WANT is a flag list, splitting is the point
    set -- $WANT
  else
    DO=0; set -- --claude --codex --gemini --agy --vscode
  fi
fi

cd "$REPO"   # project-scoped clients write their config in the cwd
while [ $# -gt 0 ]; do
  case $1 in
    # .mcp.json is committed, so paths stay relative and uv unresolved; the rest are user-wide configs, so absolute
    --claude) if [ "$DO" = 1 ] && grep -qs "\"$NAME\"" .mcp.json; then echo "  claude       already in .mcp.json"
              else run claude claude mcp add -s project "$NAME" -- uv run --directory .fornix python -m context_store.server mcp; fi ;;
    --codex)  run codex       codex mcp add "$NAME" -- "$UV" run --directory "$HERE" python -m context_store.server mcp ;;
    --gemini) run gemini      gemini mcp add "$NAME" -- "$UV" run --directory "$HERE" python -m context_store.server mcp ;;
    --agy)    run antigravity agy mcp add "$NAME" -- "$UV" run --directory "$HERE" python -m context_store.server mcp ;;
    --vscode) run "vs code"   code --add-mcp "{\"name\":\"$NAME\",\"command\":\"$UV\",\"args\":[\"run\",\"--directory\",\"$HERE\",\"python\",\"-m\",\"context_store.server\",\"mcp\"]}" ;;
    --set-root)   [ $# -ge 2 ] || { echo "setup: --set-root needs a folder" >&2; exit 2; }; set_root "$2"; shift ;;
    --set-root=*) set_root "${1#*=}" ;;
    # the leading --print is eaten by the shift at the bottom of the loop
    --print)  DO=0; set -- --print --claude --codex --gemini --agy --vscode ;;
    -h|--help) usage; exit 0 ;;
    *) echo "setup: unknown option $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[ -z "$ROOT" ] || set_root "$ROOT"   # only the wizard sets it; --set-root ran in the loop

[ "$DO" = 1 ] && exit 0
cat <<EOF

  pass a flag to run one, e.g. .fornix/setup.sh --codex

  clients configured by file (Cursor, Windsurf, Cline, Zed, Claude Desktop) take this in mcpServers:
  "$NAME": {"command": "$UV", "args": ["run", "--directory", "$HERE", "python", "-m", "context_store.server", "mcp"]}

  many repos in one editor window: run .fornix/setup.sh --set-root <folder> in each,
  and that folder gets a "$NAME-<repo>" server for every one of them
EOF
