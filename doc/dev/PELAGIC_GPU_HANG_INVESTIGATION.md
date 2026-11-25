# Pelagic GPU hang (#892) — how to reproduce and narrow it down

This page and the code beside it live on the `investigate-892` branch only, and
are not meant to be merged. They are for whoever has a Mac that shows the
problem. The development Mac (M5) does not.

## What is known

The first report with details came from XeFM 1.17.1 on macOS 26 with the
Pelagic theme, on the M3 Pro that showed the problem before:

- **The GPU hung in the Pelagic scene shader itself** (`puikit_bg_fragment ->
  scene: FAULTED`), in the frame at scene time 751.45, 693x573. The frames just
  before and after it were only caught up in it. The lens passes are not the
  cause.
- **It is not the load.** The 30 frames before took 5 to 14 ms of GPU time.
  `GPU ms of this buffer: 6147620589388.7` is not a time but a placeholder that
  macOS leaves for a buffer it aborted. The report was misleading there.
- **The same frames are clean on an M5**: no GPU error, no NaN or Inf in the scene
  target, nothing from Metal's API and shader validation.
- **The frame that hung is about where the turtle enters.** Drawn on the M5 at the
  same size, the turtle has no pixel at 751.40, one at 751.45 and six at 751.50.
  A jellyfish with long tentacles is close to the camera at the same moment.

The last point is a coincidence worth testing, not a cause. The first pixel is a
grazing hit that moves by a frame with the compiler, and the turtle also crosses
the frame around 92, 312 and 526 seconds in, for close to a minute each time,
without a hang as far as we know (assuming the window had that size all along).

## Before you start

- **Save your work.** A GPU hang can make the whole screen flicker or freeze for
  a moment, and can disturb other apps that draw on the GPU.
- macOS refuses everything a process submits after a hang. A run that hung is
  over: start a new one (the script does this by itself).

## Set up

Needs Python 3.11 or newer.

```bash
git clone -b investigate-892 https://github.com/crftwr/xefm.git xefm-892
cd xefm-892
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Test 1: the script (about 4 minutes)

It draws the scene offscreen through the renderer XeFM uses, without opening a
window, at the reported size.

```bash
PYTHONPATH=. python tools/repro_892_pelagic_gpu_hang.py
```

Each run draws the twelve seconds around the reported moment at the app's pace
(20 frames a second), then goes over 751.3 to 751.6 in small steps. Every variant
of the scene runs twice:

| Variant | What is different | If it stops hanging while `shipped` hangs |
|---|---|---|
| `shipped` | Nothing | |
| `quiet` | The shipped scene, a few seconds earlier, before the turtle | The moment matters |
| `no-turtle` | No turtle at all | The turtle is involved |
| `turtle-flat` | The turtle is found but drawn in a flat colour | Its shading (`turtleShade`) is involved |
| `no-jellyfish` | No jellyfish | The jellyfish are involved |
| `no-tentacles` | Jellyfish without tentacles and arms | The tentacles and arms are involved |
| `no-arrays` | The same picture, with no local arrays in the tentacles | The arrays are involved, and this could be the fix |

**Nothing failed?** Draw the 800 seconds leading up to it at the app's pace (about
14 minutes):

```bash
PYTHONPATH=. python tools/repro_892_pelagic_gpu_hang.py --soak
```

If only some runs of a variant fail, repeat with more rounds, for example
`--rounds 6`, or limit it with `--variant shipped --variant no-arrays`.

## Test 2: XeFM itself

Only if Test 1 does not hang. The scene's clock can start just before the
reported moment, so there is no need to wait 12 minutes:

```bash
XEFM_PELAGIC_OFFSET=745 python -m xefm --backend gui
```

1. Make the window about 770 x 637 points. That is the size of the report; at
   another size the turtle enters at another moment.
2. Switch to another theme and back to Pelagic. That restarts the clock, so the
   turtle enters about six seconds later.
3. Keep the window in front and press a cursor key now and then. The scene
   stops after 15 seconds without input.
4. Repeat steps 2 and 3 ten times or so.

If it hangs, quit XeFM and try the variants of Test 1 in the same way:

```bash
XEFM_PELAGIC_OFFSET=745 XEFM_PELAGIC_VARIANT=no-arrays python -m xefm --backend gui
```

`XEFM_PELAGIC_OFFSET=0` is XeFM as usual.

## What to send

- The file Test 1 saved, `temp/repro_892_<date>.txt`, even when nothing failed.
  It has the chip, the macOS version and the versions of the packages.
- For Test 2: the `[puikit]` lines from the terminal, which variants hung, and
  after how many tries. The unified log keeps the lines too:

  ```bash
  log show --last 30m --predicate 'eventMessage CONTAINS "[puikit]"'
  ```
- Whether Low Power Mode was on, and which displays were connected.

## Code on this branch

| Where | What |
|---|---|
| `tools/repro_892_pelagic_gpu_hang.py` | The script. Each run is a process of its own and stops at the first failure. |
| `xefm/background_pelagic.py` | `VARIANTS`, `XEFM_PELAGIC_VARIANT` and `XEFM_PELAGIC_OFFSET`, all read when XeFM starts |
