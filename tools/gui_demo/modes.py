"""List the guest's display modes, or set one (points w, h, pixel width).
Runs inside the VM on XeFM.app's bundled Python, which has PyObjC:

    PY=/Applications/XeFM.app/Contents/Frameworks/PythonT.framework/Versions/Current/bin/python3
    tools/gui_demo/vm.sh "PYTHONPATH=/Applications/XeFM.app/Contents/Resources/python_packages $PY - 960 600 1920" < tools/gui_demo/modes.py
"""
import sys
from Quartz import (CGMainDisplayID, CGDisplayCopyAllDisplayModes, CGDisplayModeGetWidth,
                    CGDisplayModeGetHeight, CGDisplayModeGetPixelWidth, CGDisplayModeGetPixelHeight,
                    CGDisplayCopyDisplayMode, CGBeginDisplayConfiguration, CGConfigureDisplayWithDisplayMode,
                    CGCompleteDisplayConfiguration, kCGConfigurePermanently)
d = CGMainDisplayID()
from Quartz import kCGDisplayShowDuplicateLowResolutionModes
opts = {kCGDisplayShowDuplicateLowResolutionModes: True}
modes = CGDisplayCopyAllDisplayModes(d, opts)
cur = CGDisplayCopyDisplayMode(d)
print("current", CGDisplayModeGetWidth(cur), CGDisplayModeGetHeight(cur), CGDisplayModeGetPixelWidth(cur), CGDisplayModeGetPixelHeight(cur))
for m in modes:
    print(CGDisplayModeGetWidth(m), CGDisplayModeGetHeight(m), CGDisplayModeGetPixelWidth(m), CGDisplayModeGetPixelHeight(m))
if len(sys.argv) > 1:
    w, h, pw = map(int, sys.argv[1:4])
    for m in modes:
        if (CGDisplayModeGetWidth(m), CGDisplayModeGetHeight(m), CGDisplayModeGetPixelWidth(m)) == (w, h, pw):
            err, cfg = CGBeginDisplayConfiguration(None)
            CGConfigureDisplayWithDisplayMode(cfg, d, m, None)
            print("set", CGCompleteDisplayConfiguration(cfg, kCGConfigurePermanently))
            break
