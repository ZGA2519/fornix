#!/usr/bin/env sh
# Re-inject the context-sync loop on every prompt while a flag file exists.
# Registered as a UserPromptSubmit hook; stdout is added to the model's context.
# The flag file's contents are the mode: "readonly" for recall-only, anything
# else (including empty) for full recall + capture. "detail" is full plus a log:
# every prompt, and every tool call (registered again as PostToolUse with "post"),
# is appended verbatim to .fornix/memories/detail.jsonl.
#
# Two layouts, both driven by <repo>/.fornix/.sync-on:
#   a repo opened on its own   the flag beside this project, server "fornix"
#   a workspace folder over    .claude/context-sync.repos lists "<server> <repo path>"
#   several repos              for every repo added with .fornix/setup.sh --set-root;
#                              each repo's own flag arms its own server
PD="${CLAUDE_PROJECT_DIR:-.}"
# ponytail: detail logs a repo opened on its own; a workspace folder over several repos is not logged
[ "$(tr -d '[:space:]' 2>/dev/null < "$PD/.fornix/.sync-on")" != "detail" ] ||
  uv run --quiet --directory "$PD/.fornix" python -m context_store.store > /dev/null
cat > /dev/null  # drain the stdin JSON; leaving it unread can trip the hook handler
[ "$1" != "post" ] || exit 0  # PostToolUse: the log above was the whole job

FULL="" RO="" KS=""

# valid_k <value>: print it when it is a whole number in 1..100, nothing otherwise
valid_k() {
  case "$1" in ''|*[!0-9]*) return ;; esac
  [ "${#1}" -le 3 ] && [ "$1" -ge 1 ] && [ "$1" -le 100 ] && printf %s "$1"
}
# sync_k <store dir>: how many memories a recall from that store asks for, per prompt.
# CONTEXT_SYNC_K, else "sync_k" in <store dir>/config.json (see context_store/config.py), else 6.
sync_k() {
  _k=$(valid_k "${CONTEXT_SYNC_K:-}")
  [ -n "$_k" ] || [ ! -f "$1/config.json" ] ||
    _k=$(valid_k "$(tr -d '\n\r' < "$1/config.json" | sed -n 's/.*"sync_k"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')")
  printf %s "${_k:-6}"
}

# arm <server> <flag file>: sort that server into the capture or the read-only list,
# and note the k its recall asks for, read from the config.json beside the flag
arm() {
  KS="$KS $1=$(sync_k "${2%/*}")"
  if [ "$(tr -d '[:space:]' < "$2")" = "readonly" ]; then RO="$RO $1"; else FULL="$FULL $1"; fi
}
join()  { _j=""; for _w in $1; do _j="$_j${_j:+, }$_w"; done; printf %s "$_j"; }
count() { set -- $1; echo $#; }

[ ! -f "$PD/.fornix/.sync-on" ] || arm fornix "$PD/.fornix/.sync-on"
if [ -f "$PD/.claude/context-sync.repos" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    server=${line%% *} dir=${line#* }
    # .context/ is where a member installed before the rename keeps its flag
    for f in "$dir/.fornix/.sync-on" "$dir/.context/.sync-on"; do
      [ ! -f "$f" ] || { arm "$server" "$f"; break; }
    done
  done < "$PD/.claude/context-sync.repos"
fi
[ -n "$FULL$RO" ] || exit 0

ALL=$(join "$FULL $RO")
# one k when every armed store agrees, otherwise each server's own
K="" EACH=""
for _p in $KS; do
  EACH="$EACH${EACH:+, }${_p%%=*} k=${_p#*=}"
  [ -z "$K" ] || [ "$K" = "k=${_p#*=}" ] || K=mixed
  [ "$K" = mixed ] || K="k=${_p#*=}"
done
[ "$K" != mixed ] || K="the k set for that server ($EACH)"
WHERE=""
if [ "$(count "$FULL $RO")" = 1 ]; then
  RECALL="Before answering this prompt: call the $ALL MCP select() with a query built from the intent of the prompt, $K, and treat the results as project ground truth."
else
  RECALL="Before answering this prompt: call select() on the MCP server for the repo this prompt is about, with a query built from the intent of the prompt, $K, and treat the results as project ground truth. One server per repo, all syncing right now: $ALL. Each holds only that repo's memory, so recall from the one that owns the files in play."
  WHERE=" on the server for the repo it belongs to,"
fi

if [ -z "$FULL" ]; then
  echo "context-sync is ON in READ-ONLY mode. $RECALL Do not call write() or compress() for any reason this turn, and do not ask for permission to; only an explicit context-start-sync from the user re-enables capture. If something durable comes up, note it in one line instead of storing it. Close the turn with: context: N recalled, read-only. Full protocol is in the context-sync skill."
else
  READONLY_NOTE=""
  [ -z "$RO" ] || READONLY_NOTE=" $(join "$RO") is read-only this session: recall from it, never write to it."
  echo "context-sync is ON. $RECALL After acting: write() each durable fact learned, one per call,$WHERE correcting in place with write(id=...) rather than appending duplicates. No credentials or personal data.$READONLY_NOTE Close the turn with one line: context: N recalled, M written. Full protocol is in the context-sync skill."
fi
