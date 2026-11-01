"""``xefm try`` — XeFM in a throwaway home, by hand or from a script (#682).

A thin layer over :mod:`xefm.trial`: for a person to look around (and an
extension's author to try a package) without touching ``~/.xefm``, and, with
``--keys``, for an automated test or a recorded demo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from xefm import extensions as ext
from xefm import trial


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xefm try",
        description="Run the terminal XeFM in a temporary home: your ~/.xefm is "
        "never read or written, the keymap preset is already chosen and the Tip "
        "of the Day is off, and the home is deleted at exit. Without --keys it "
        "runs in this terminal until you quit it. With --keys it follows a "
        "script in a pseudo-terminal, saves each step's screen as text, "
        "optionally records the session, and exits — for automated tests and "
        "demos.")
    home = parser.add_argument_group("the home")
    home.add_argument("--ext", metavar="SOURCE", action="append", default=[],
                      help="install this extension package in it: a directory, a "
                      ".zip, an https:// zip URL or github:owner/repo[/path][@ref] "
                      "(repeatable)")
    home.add_argument("--config", metavar="FILE",
                      help="use this config.py (default: XeFM's template)")
    home.add_argument("--keymap", default="afx",
                      help="the keymap preset: afx, orthodox, native or vim "
                      "(default: afx)")
    home.add_argument("--left", metavar="DIR", help="the left pane's directory "
                      "(default: a few sample files in the home)")
    home.add_argument("--right", metavar="DIR",
                      help="the right pane's directory (default: the home)")
    home.add_argument("--keep-home", action="store_true",
                      help="leave the home in place and print where it is")
    script = parser.add_argument_group(
        "scripted (needs 'quality-loop[tui]')")
    script.add_argument("--keys", metavar="SCRIPT",
                        help="a JSON list of steps to run instead of handing the "
                        "terminal over")
    script.add_argument("--screens", metavar="DIR", help="where each step's screen "
                        "and steps.jsonl go (default: try-screens)")
    script.add_argument("--record", metavar="FILE",
                        help="also record the session as an asciicast v2 file")
    script.add_argument("--size", default="120x40",
                        help="the terminal's COLSxROWS (default: 120x40)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.keys is None and (args.screens or args.record):
        print("error: --screens and --record go with --keys", file=sys.stderr)
        return 2
    try:
        cols, rows = (int(n) for n in args.size.lower().split("x"))
    except ValueError:
        print(f"error: --size is COLSxROWS, not {args.size!r}", file=sys.stderr)
        return 2
    try:
        # The script is read first, so a typo in it costs no install.
        steps = trial.read_script(Path(args.keys)) if args.keys else None
        home = trial.TryHome(args.ext, keymap=args.keymap,
                             config=Path(args.config).expanduser() if args.config else None)
    except ext.InstallError as exc:
        for problem in exc.problems:
            print(problem)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (ext.ManifestError, trial.TryError) as exc:
        print(f"error: {getattr(exc, 'problem', exc)}", file=sys.stderr)
        return 1
    packages = ", ".join(f"{m.id} {m.version}" for m in home.manifests)
    print(f"XeFM in {home.root}" + (f" with {packages}" if packages else ""))
    left = Path(args.left).expanduser().resolve() if args.left else home.work
    right = Path(args.right).expanduser().resolve() if args.right else home.root
    argv_ = trial.xefm_argv(left, right)
    try:
        if steps is None:
            return trial.run_interactive(home, argv_)
        screens = Path(args.screens or "try-screens")
        record = Path(args.record) if args.record else None
        try:
            result = trial.run_script(home, argv_, steps, screens=screens,
                                      record=record, rows=rows, cols=cols)
        except trial.TryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"ran {result.steps} of {len(steps)} steps; screens and steps.jsonl "
              f"in {screens}" + (f", recording in {record}" if record else ""))
        if result.unsettled:
            print("still drawing when patience ran out at step(s) "
                  + ", ".join(map(str, result.unsettled)))
        if result.exited is not None:
            print(f"XeFM exited during the script (status {result.exited}); "
                  f"see the last screen in {screens}")
            return 1
        return 0
    finally:
        if args.keep_home:
            print(f"kept the home: {home.root}")
        else:
            home.remove()


if __name__ == "__main__":
    sys.exit(main())
