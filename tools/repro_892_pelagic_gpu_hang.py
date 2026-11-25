#!/usr/bin/env python3
"""
Try to reproduce the Pelagic GPU hang of xefm#892 without opening XeFM.

Draws the Pelagic scene offscreen, through the same renderer and passes XeFM uses
on macOS, over the seconds in which the hang was reported (time 751.45 at
693x573), and repeats it with one part of the scene taken out at a time. The
variant that stops hanging names the part.

Each run is a child process of its own, because macOS refuses everything a
process submits after a GPU hang. A run stops at its first failure.

Usage, from the repo root (see doc/dev/PELAGIC_GPU_HANG_INVESTIGATION.md):
    PYTHONPATH=. python3 tools/repro_892_pelagic_gpu_hang.py            # about 4 minutes
    PYTHONPATH=. python3 tools/repro_892_pelagic_gpu_hang.py --soak     # about 14 minutes
    PYTHONPATH=. python3 tools/repro_892_pelagic_gpu_hang.py --variant shipped --rounds 5

A GPU hang can make the whole screen flicker or freeze for a moment: save your
work first. The results are also written to temp/repro_892_<date>.txt.
"""

import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import threading
import time

WIDTH, HEIGHT, SEED = 693, 573, 47694.0   # the reported frame
STEP = 0.05                # seconds between the reported frames
IN_FLIGHT = 3              # drawables of a CAMetalLayer: frames queued at once
PAUSE = 3.0                # between runs, for the GPU to recover
# (start, end) of the scene time drawn at the app's pace, and of the dense sweep.
PACED, DENSE = (745.0, 757.0), (751.30, 751.60)
QUIET_PACED, QUIET_DENSE = (729.0, 741.0), (740.30, 740.60)   # no turtle in the frame
DENSE_FRAMES, DENSE_PASSES = 300, 4
EXIT_FAILED = 3


def child(variant: str, soak: bool) -> int:
    """One run: draw, and report the first failure. Prints one JSON line."""
    os.environ["XEFM_PELAGIC_VARIANT"] = variant
    import Metal
    from puikit.background import Shader
    from puikit.backends import _metal
    from xefm.background_pelagic import pelagic_shader

    known = Shader.__dataclass_fields__
    renderer = _metal.MetalBackground()
    fields = {k: v for k, v in pelagic_shader().items() if k in known}
    if not renderer.set_shader(Shader(**fields)):
        print(json.dumps({"error": f"did not compile: {renderer.error}"}))
        return 1
    texture_desc = (Metal.MTLTextureDescriptor
                    .texture2DDescriptorWithPixelFormat_width_height_mipmapped_(
                        _metal.PIXEL_FORMAT, WIDTH, HEIGHT, False))
    texture_desc.setUsage_(Metal.MTLTextureUsageRenderTarget)
    texture_desc.setStorageMode_(Metal.MTLStorageModePrivate)
    outputs = [renderer.device.newTextureWithDescriptor_(texture_desc)
               for _ in range(IN_FLIGHT)]
    slots = threading.Semaphore(IN_FLIGHT)
    lock = threading.Lock()
    failure: list = []
    gpu_ms: list = []
    count = [0]

    def submit(scene_time: float, phase: str) -> bool:
        if not slots.acquire(timeout=30.0):
            with lock:
                failure.append({"phase": phase, "time": scene_time,
                                "error": "no frame finished for 30 s"})
            return False
        with lock:
            if failure:
                slots.release()
                return False
        command = renderer._encode(outputs[count[0] % IN_FLIGHT], WIDTH, HEIGHT,
                                   scene_time, block=True, seed=SEED)
        count[0] += 1

        def done(cmd):
            seconds = cmd.GPUEndTime() - cmd.GPUStartTime()
            with lock:
                if cmd.status() == Metal.MTLCommandBufferStatusError:
                    failure.append({"phase": phase, "time": scene_time,
                                    "error": (str(cmd.error().localizedDescription())
                                              if cmd.error() is not None else "unknown")})
                elif 0.0 < seconds < 3600.0:
                    gpu_ms.append(seconds * 1000.0)
            slots.release()

        command.addCompletedHandler_(done)
        command.commit()
        return True

    def paced(start: float, end: float, phase: str) -> bool:
        begun = time.monotonic()
        frames = int(round((end - start) / STEP))
        for i in range(frames + 1):
            due = begun + i * STEP
            time.sleep(max(0.0, due - time.monotonic()))
            if not submit(start + i * STEP, phase):
                return False
        return True

    def dense(start: float, end: float, phase: str) -> bool:
        for _ in range(DENSE_PASSES):
            for i in range(DENSE_FRAMES):
                if not submit(start + (end - start) * i / DENSE_FRAMES, phase):
                    return False
        return True

    quiet = variant == "quiet"
    if soak:
        paced(0.0, 800.0, "soak")
    elif paced(*(QUIET_PACED if quiet else PACED), "paced"):
        dense(*(QUIET_DENSE if quiet else DENSE), "dense")
    for _ in range(IN_FLIGHT):              # the frames still on the GPU
        slots.acquire(timeout=30.0)
    with lock:
        ordered = sorted(gpu_ms)
        print(json.dumps({
            "frames": count[0],
            "gpu_ms_median": round(ordered[len(ordered) // 2], 2) if ordered else None,
            "gpu_ms_max": round(ordered[-1], 2) if ordered else None,
            "failures": failure[:3],
        }), flush=True)
        failed = bool(failure)
    sys.stdout.flush()
    sys.stderr.flush()
    # Not a normal exit: after a hang the interpreter can wait on the GPU.
    os._exit(EXIT_FAILED if failed else 0)


def sysctl(name: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "?"


def versions() -> str:
    import puikit
    import xefm
    return (f"chip: {sysctl('machdep.cpu.brand_string')} ({sysctl('hw.model')}), "
            f"macOS {platform.mac_ver()[0]}, Python {platform.python_version()}, "
            f"PuiKit {puikit.__version__}, XeFM {xefm.__version__}")


def run(variant: str, soak: bool, timeout: float) -> "tuple[dict, str]":
    """(result, what the child wrote to stderr) of one run."""
    args = [sys.executable, os.path.abspath(__file__), "--child", variant]
    if soak:
        args.append("--soak")
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"error": f"no answer in {timeout:.0f} s"}, ""
    lines = p.stdout.strip().splitlines()
    try:
        result = json.loads(lines[-1])
    except (IndexError, ValueError):
        result = {"error": f"exit {p.returncode}"}
    return result, p.stderr


def describe(result: dict) -> str:
    if "error" in result:
        return f"COULD NOT RUN: {result['error']}"
    ms = f"{result['frames']} frames, GPU ms median {result['gpu_ms_median']} max {result['gpu_ms_max']}"
    if not result["failures"]:
        return f"ok      {ms}"
    first = result["failures"][0]
    return (f"FAILED  {ms}; {first['phase']} phase, time {first['time']:.3f}: "
            f"{first['error']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproduce the Pelagic GPU hang (xefm#892).")
    parser.add_argument("--variant", action="append", help="only this one (repeatable)")
    parser.add_argument("--rounds", type=int, default=2, help="runs of each variant")
    parser.add_argument("--soak", action="store_true",
                        help="draw time 0 to 800 at the app's pace, as the app does")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != "darwin":
        print("This tool draws with Metal; it runs on macOS only.")
        return 2
    if args.child:
        return child(args.child, args.soak)

    from xefm.background_pelagic import VARIANTS
    names = args.variant or (["shipped"] if args.soak else list(VARIANTS))
    unknown = [n for n in names if n not in VARIANTS]
    if unknown:
        print(f"Unknown variant: {', '.join(unknown)} (known: {', '.join(VARIANTS)})")
        return 2
    rounds = 1 if args.soak else max(1, args.rounds)
    os.makedirs("temp", exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join("temp", f"repro_892_{stamp}.txt")
    with open(path, "w", encoding="utf-8") as log:
        def out(text: str) -> None:
            print(text, flush=True)
            log.write(text + "\n")
            log.flush()

        out(versions())
        out(f"{WIDTH}x{HEIGHT}, {'soak' if args.soak else 'quick'}, {rounds} round(s)")
        failed = {}
        for n in range(rounds):              # a round covers every variant, so that
            for name in names:               # a drift over time hits all of them
                result, stderr = run(name, args.soak, 1200.0 if args.soak else 180.0)
                out(f"[{n + 1}/{rounds}] {name:13s} {describe(result)}")
                if result.get("failures") or "error" in result:
                    failed[name] = failed.get(name, 0) + 1
                    for line in stderr.strip().splitlines():
                        out(f"      {line}")
                time.sleep(PAUSE)
        out("")
        out("summary: " + ", ".join(f"{n} {failed.get(n, 0)}/{rounds} failed" for n in names))
    print(f"Saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
