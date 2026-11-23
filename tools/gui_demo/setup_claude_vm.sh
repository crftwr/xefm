#!/bin/sh
# One-time, for the AI agent demo: Claude Code's own state in the demo VM.
# - onboarding done, the demo folders trusted, auto-update off, dark theme;
# - the read-only commands and xefmctl allowed, so no permission prompt
#   interrupts a take (XeFM's own deny list still applies on top);
# - hooks that append each PreToolUse / Stop / Notification event to
#   /tmp/agent-events.jsonl, so agent_drive.py knows when the agent is done
#   or about to raise an XeFM dialog. They print nothing.
# Claude Code itself: curl -fsSL https://claude.ai/install.sh | bash (in the VM).
HERE="$(cd "$(dirname "$0")" && pwd)"
"$HERE/vm.sh" 'mkdir -p ~/.claude && cat > ~/.claude.json' <<'EOF'
{
  "hasCompletedOnboarding": true,
  "theme": "dark",
  "autoUpdates": false,
  "projects": {
    "/Users/admin/projects/aurora": {"hasTrustDialogAccepted": true, "hasCompletedProjectOnboarding": true},
    "/Users/admin/projects/aurora/photos": {"hasTrustDialogAccepted": true, "hasCompletedProjectOnboarding": true},
    "/Users/admin/projects": {"hasTrustDialogAccepted": true, "hasCompletedProjectOnboarding": true},
    "/Users/admin": {"hasTrustDialogAccepted": true, "hasCompletedProjectOnboarding": true}
  }
}
EOF
"$HERE/vm.sh" 'cat > ~/.claude/settings.json' <<'EOF'
{
  "permissions": {
    "allow": [
      "Bash(xefmctl:*)", "Bash(mkdir:*)", "Bash(ls:*)", "Bash(grep:*)",
      "Bash(find:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(diff:*)",
      "Read", "Glob", "Grep", "Edit", "Write"
    ]
  },
  "hooks": {
    "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "cat >> /tmp/agent-events.jsonl; echo >> /tmp/agent-events.jsonl"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "cat >> /tmp/agent-events.jsonl; echo >> /tmp/agent-events.jsonl"}]}],
    "Notification": [{"hooks": [{"type": "command", "command": "cat >> /tmp/agent-events.jsonl; echo >> /tmp/agent-events.jsonl"}]}]
  }
}
EOF
