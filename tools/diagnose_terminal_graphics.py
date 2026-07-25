#!/usr/bin/env python3
"""Diagnose why inline terminal images may not appear (especially in iTerm2).

Run this INSIDE the terminal you are testing (iTerm2, kitty, WezTerm, ...):

    PYTHONPATH=. python tools/diagnose_terminal_graphics.py

It is NOT a TUI — it just prints environment/detection info, then emits one test
image several different ways, each under a numbered "TEST N" banner. After it
exits, tell me **which TEST numbers showed a 4-colour image and which showed
nothing** (a blank gap, or raw escape gibberish). That single fact pins down the
break:

* No TEST shows an image  -> iTerm2 is not rendering our sequences at all
                             (wrong terminal detected, tmux in the way, or the
                             emulator setting is off).
* TEST 1-3 show but 5 does not -> the cursor save/restore or positioning the
                             real backend adds is the culprit.
* Everything shows here but XeFM still doesn't -> the protocol is fine; the break
                             is in the curses integration (run with the debug
                             env var below and send the log).

Runtime trace for the *real* app (complements this script):

    PUIKIT_TERM_GRAPHICS_DEBUG=/tmp/tg.log PYTHONPATH=. python -m xefm

open an image, quit, and send /tmp/tg.log.
"""

import base64
import io
import os
import sys

# Make puikit + PIL importable whether run from the repo root or elsewhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def line(text=""):
    sys.stdout.write(text + "\n")


def banner(title):
    line()
    line("=" * 64)
    line(title)
    line("=" * 64)


banner("1. Environment")
for key in ("TERM_PROGRAM", "TERM_PROGRAM_VERSION", "LC_TERMINAL", "TERM",
            "TMUX", "STY", "KITTY_WINDOW_ID", "KONSOLE_VERSION",
            "PUIKIT_TERM_GRAPHICS"):
    line(f"  {key:24} = {os.environ.get(key, '(unset)')}")

try:
    import PIL
    from PIL import Image
    line(f"  {'Pillow':24} = {PIL.__version__}")
    have_pil = True
except ImportError:
    line(f"  {'Pillow':24} = NOT INSTALLED")
    have_pil = False

tg = None
try:
    from puikit.backends import _terminal_graphics as tg
    line(f"  {'detect_protocol()':24} = {tg.detect_protocol()}")
    line(f"  {'have_pillow()':24} = {tg.have_pillow()}")
    px = tg.cell_pixels()
    line(f"  {'cell_pixels()':24} = {px}")
except Exception as exc:  # noqa: BLE001 - diagnostic, report anything
    line(f"  puikit import/detect FAILED: {exc!r}")

if os.environ.get("TMUX") or os.environ.get("STY"):
    banner("!! You are inside tmux/screen")
    line("tmux and screen intercept image escape sequences, so they never reach")
    line("iTerm2 unless passthrough is configured. Test OUTSIDE tmux first:")
    line("    tmux detach   (or open a fresh iTerm2 tab), then re-run this.")

if not have_pil:
    banner("Stop: Pillow is required to build a test image (pip install pillow).")
    sys.exit(1)

# A small, unmistakable test image: four solid colour quadrants.
image = Image.new("RGB", (240, 120))
for x in range(240):
    for y in range(120):
        image.putpixel((x, y), (
            (235, 70, 70) if (x < 120 and y < 60) else
            (70, 205, 90) if (x >= 120 and y < 60) else
            (80, 120, 245) if (x < 120) else (240, 205, 70)
        ))
buffer = io.BytesIO()
image.save(buffer, format="PNG")
png = buffer.getvalue()
b64 = base64.b64encode(png).decode("ascii")
line()
line(f"Test image: 240x120 PNG, {len(png)} bytes — red/green/blue/yellow quadrants.")


def emit(title, sequence):
    banner(title)
    sys.stdout.write(sequence)
    sys.stdout.flush()
    line()
    line("^^^ image above this line?  (blank = not rendered)")


# Progressively richer iTerm2 sequences, so the first one that fails is the
# feature that breaks it.
emit("TEST 1  iTerm2, absolute minimum (inline=1 only, BEL terminator)",
     f"\x1b]1337;File=inline=1:{b64}\a")

emit("TEST 2  iTerm2 + size",
     f"\x1b]1337;File=inline=1;size={len(png)}:{b64}\a")

emit("TEST 3  iTerm2 + width/height in cells + preserveAspectRatio",
     f"\x1b]1337;File=inline=1;size={len(png)};width=20;height=10;"
     f"preserveAspectRatio=1:{b64}\a")

emit("TEST 4  iTerm2 with ESC-backslash (ST) terminator instead of BEL",
     f"\x1b]1337;File=inline=1;width=20;height=10:{b64}\x1b\\")

if tg is not None:
    emit("TEST 5  exactly what PuiKit's encoder produces (no positioning)",
         tg.encode(tg.ITERM2, image, png, cols=20, rows=10))
    emit("TEST 6  encoder + cursor-move + DECSC/DECRC (as present() writes it)",
         "\x1b7" + "\x1b[12;3H" + tg.encode(tg.ITERM2, image, png, 20, 10) + "\x1b8")

# TEST 7 is the important one: XeFM runs in the ALTERNATE screen buffer (curses
# initscr enables it). Some terminals render inline images differently there —
# this is the single most likely reason images work in a plain shell but not in
# the TUI. It is interactive (enters the alt screen and waits) so it only runs on
# a real terminal.
if tg is not None and sys.stdin.isatty():
    banner("TEST 7  ALTERNATE screen buffer — the closest match to how XeFM runs")
    line("About to enter the alternate screen (like a full-screen TUI) and draw")
    line("an image there. Watch whether it appears. Press Enter to start.")
    try:
        input("  press Enter... ")
    except (EOFError, KeyboardInterrupt):
        input_ok = False
    else:
        input_ok = True
    if input_ok:
        sys.stdout.write("\x1b[?1049h")          # enter alternate screen
        sys.stdout.write("\x1b[2J\x1b[H")         # clear + cursor home
        sys.stdout.write("ALT SCREEN — a 4-colour image should appear below:\r\n\r\n")
        sys.stdout.write("\x1b7\x1b[5;3H"
                         + tg.encode(tg.ITERM2, image, png, 20, 10) + "\x1b8")
        sys.stdout.write("\x1b[20;1H"
                         "Did the image appear in the ALT screen? Press Enter to leave.")
        sys.stdout.flush()
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        sys.stdout.write("\x1b[?1049l")           # leave alternate screen
        line()
        line("Back to the normal screen. If TESTs 1-6 showed an image but TEST 7")
        line("(alt screen) did NOT, that is the bug: iTerm2 is not rendering our")
        line("inline images in the alternate screen buffer XeFM uses.")

banner("Done")
line("Report which TEST numbers rendered an image — especially TEST 7 (alt")
line("screen) vs the earlier ones. For the real app, run it with")
line("PUIKIT_TERM_GRAPHICS_DEBUG=/tmp/tg.log python -m xefm and send that file.")
