#!/bin/sh
# Ask the demo VM's XeFM what is on screen (xefmctl state --json), borrowing
# the socket and token from the running agent's environment. Prints nothing
# when no agent runs.
exec "$(dirname "$0")/vm.sh" '
pid=$(pgrep -f "/.local/bin/claude" | head -1); [ -n "$pid" ] || exit 0
eval "$(ps eww -p $pid | tr " " "\n" | grep -E "^(XEFM_SOCKET|XEFM_TOKEN|XEFM_SESSION|XEFM_SESSION_KEY|PATH)=" | sed "s/^/export /")"
xefmctl state --json 2>&1'
