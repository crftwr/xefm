#!/bin/sh
# Before each AI agent take: a fresh home (prep_home_agent.py, THEME baked
# in), no earlier Claude sessions, the Claude Code token handed to the GUI
# session through open --env (read from stdin over ssh, so it is never in a
# local command line or in ~/.xefm/config.py, which the agent may read), XeFM started.
#   tools/gui_demo/reset_agent.sh THEME TOKEN_FILE
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../.."
WORK="$ROOT/temp/gui-demo"
THEME="${1:-Earth}"
(cd "$ROOT" && PYTHONPATH=. python tools/gui_demo/prep_home_agent.py "$WORK/home-agent" "$THEME" >/dev/null)
"$HERE/vm.sh" 'pkill -x XeFM; pkill -f "/.local/bin/claude"; sleep 1; rm -rf ~/projects ~/.xefm ~/.claude/projects; find ~/.Trash -mindepth 1 -delete 2>/dev/null; true'
(cd "$WORK/home-agent" && tar cf - projects .xefm) | "$HERE/vm.sh" 'tar xf - -C ~'
"$HERE/vm.sh" 'defaults write com.xefm.app "NSWindow Frame XeFMMainWindow" "0 0 960 570 0 0 960 600 "'
# launchctl setenv over ssh does not reach the GUI session; open --env does.
"$HERE/vm.sh" 'read -r t; if [ -n "$t" ]; then open --env "CLAUDE_CODE_OAUTH_TOKEN=$t" -a XeFM; else open -a XeFM; fi' < "${2:-/dev/null}"
sleep 7
