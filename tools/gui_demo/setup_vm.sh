#!/bin/sh
# One-time: make the demo VM. Run steps by hand the first time; see README.md.
#   1. tools/gui_demo/setup_vm.sh create      clone and size the VM
#   2. tools/gui_demo/run_vm.sh &             boot it (wait ~30 s)
#   3. tools/gui_demo/setup_vm.sh provision   ssh key, XeFM.app, Dock, display
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$HERE/../../temp/gui-demo"
VM="${XEFM_DEMO_VM:-xefm-demo}"
mkdir -p "$WORK"
case "$1" in
create)
    tart clone ghcr.io/cirruslabs/macos-golden-gate-vanilla:27.0 "$VM"
    tart set "$VM" --cpu 6 --memory 8192
    ;;
provision)
    IP=$(tart ip "$VM")
    [ -f "$WORK/id_demo" ] || ssh-keygen -q -t ed25519 -N "" -f "$WORK/id_demo"
    # The vanilla image's admin/admin, once, to install the key.
    expect <<EXP
set timeout 30
spawn sh -c "ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null admin@$IP 'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys' < $WORK/id_demo.pub"
expect "assword:" { send "admin\r" }
expect eof
EXP
    (cd /Applications && tar cf - XeFM.app) | "$HERE/vm.sh" 'rm -rf /Applications/XeFM.app; tar xf - -C /Applications'
    "$HERE/vm.sh" 'defaults write com.apple.dock autohide -bool true; killall Dock'
    # Tips posts "See what's new in macOS" as a banner that stays on screen,
    # in the corner of every take. Off from the next login on.
    "$HERE/vm.sh" 'launchctl disable gui/$(id -u)/com.apple.tipsd'
    PY=/Applications/XeFM.app/Contents/Frameworks/PythonT.framework/Versions/Current/bin/python3
    "$HERE/vm.sh" "PYTHONPATH=/Applications/XeFM.app/Contents/Resources/python_packages $PY - 960 600 1920" < "$HERE/modes.py"
    echo "Now grant XeFM's folder permissions once: see README.md."
    ;;
*)
    echo "usage: $0 create|provision" >&2; exit 2 ;;
esac
