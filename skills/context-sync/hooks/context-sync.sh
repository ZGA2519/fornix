#!/usr/bin/env sh
# Re-inject the context-sync loop on every prompt while a flag file exists.
# Registered as a UserPromptSubmit hook; stdout is added to the model's context.
# The flag file's contents are the mode: "readonly" for recall-only, anything
# else (including empty) for full recall + capture.
#
# Two layouts, both driven by <repo>/.fornix/.sync-on:
#   a repo opened on its own   the flag beside this project, server "fornix"
#   a workspace folder over    .claude/context-sync.repos lists "<server> <repo path>"
#   several repos              for every repo added with .fornix/setup.sh --set-root;
#                              each repo's own flag arms its own server
cat > /dev/null  # drain the stdin JSON; leaving it unread can trip the hook handler

PD="${CLAUDE_PROJECT_DIR:-.}"
FULL="" RO=""

# arm <server> <flag file>: sort that server into the capture or the read-only list
arm() {
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
WHERE=""
if [ "$(count "$FULL $RO")" = 1 ]; then
  RECALL="Before answering this prompt: call the $ALL MCP select() with a query built from the intent of the prompt, k=6, and treat the results as project ground truth."
else
  RECALL="Before answering this prompt: call select() on the MCP server for the repo this prompt is about, with a query built from the intent of the prompt, k=6, and treat the results as project ground truth. One server per repo, all syncing right now: $ALL. Each holds only that repo's memory, so recall from the one that owns the files in play."
  WHERE=" on the server for the repo it belongs to,"
fi

if [ -z "$FULL" ]; then
  echo "context-sync is ON in READ-ONLY mode. $RECALL Do not call write() or compress() for any reason this turn, and do not ask for permission to; only an explicit context-start-sync from the user re-enables capture. If something durable comes up, note it in one line instead of storing it. Close the turn with: context: N recalled, read-only. Full protocol is in the context-sync skill."
else
  READONLY_NOTE=""
  [ -z "$RO" ] || READONLY_NOTE=" $(join "$RO") is read-only this session: recall from it, never write to it."
  echo "context-sync is ON. $RECALL After acting: write() each durable fact learned, one per call,$WHERE correcting in place with write(id=...) rather than appending duplicates. No credentials or personal data.$READONLY_NOTE Close the turn with one line: context: N recalled, M written. Full protocol is in the context-sync skill."
fi
