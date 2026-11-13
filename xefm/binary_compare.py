"""Byte-for-byte comparison of two files, answered in a message box (#631).

The side-by-side diff viewer is a *text* diff: on a binary file both sides show
a placeholder, and the question the user asked — *are these two the same?* — goes
unanswered. :func:`show_byte_comparison` answers it instead: both sizes, then
"Identical", "Different (sizes differ)", or the offset of the first byte that
differs.

:func:`compare_bytes` is the comparison itself (no UI), shared with the
directory diff, which runs it for every two-sided file and keeps the result on
the node so a later Enter can report it without reading the files again.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from puikit.widgets import show_message_box

from xefm import path_schemes
from xefm.log_manager import getLogger
from xefm.progress_manager import OperationType
from xefm.task import Task

logger = getLogger("BinCompare")

#: Read size per side per step: large enough that a local compare is
#: disk-bound, small enough that Cancel lands promptly on a slow remote.
_CHUNK = 64 * 1024

#: Local files no larger than this are compared on the UI thread: it takes a
#: few milliseconds, and a progress dialog would only flash. Anything larger —
#: and anything remote or inside an archive, whatever its size — runs on a task.
_INLINE_MAX = 4 * 1024 * 1024


@dataclass(frozen=True)
class ByteComparison:
    """What :func:`compare_bytes` found. ``offset`` is the 0-based position of
    the first differing byte — None when the files are identical, when their
    sizes already differ (nothing is read then), or when ``error`` is set."""
    left_size: Optional[int]
    right_size: Optional[int]
    offset: Optional[int] = None
    error: Optional[str] = None

    @property
    def identical(self) -> bool:
        return (self.error is None and self.offset is None
                and self.left_size == self.right_size)


def compare_bytes(left, right, *, checkpoint: Optional[Callable[[], None]] = None,
                  on_bytes: Optional[Callable[[int, int], None]] = None
                  ) -> ByteComparison:
    """Compare ``left`` and ``right`` byte for byte: sizes first, then chunked
    reads until the first difference. ``checkpoint`` is called between chunks
    (a task's, which raises to cancel); ``on_bytes(done, total)`` reports how
    far into the files the compare is."""
    try:
        left_size = left.stat().st_size
        right_size = right.stat().st_size
    except OSError as e:
        return ByteComparison(None, None, error=str(e))
    if left_size != right_size:
        return ByteComparison(left_size, right_size)
    done = 0
    try:
        with left.open("rb") as lf, right.open("rb") as rf:
            while True:
                if checkpoint is not None:
                    checkpoint()
                lc, rc = lf.read(_CHUNK), rf.read(_CHUNK)
                if lc != rc:
                    at = next((i for i, (a, b) in enumerate(zip(lc, rc)) if a != b),
                              min(len(lc), len(rc)))
                    return ByteComparison(left_size, right_size, offset=done + at)
                if not lc:
                    return ByteComparison(left_size, right_size)
                done += len(lc)
                if on_bytes is not None:
                    on_bytes(done, left_size)
    except OSError as e:
        return ByteComparison(left_size, right_size, error=str(e))


def describe(left, right, result: ByteComparison) -> str:
    """The message box's text: each file with its size, then the verdict.
    Two files of the same name (the usual case across two panes) are told
    apart by their full paths."""
    if left.name != right.name:
        names = (left.name, right.name)
    else:
        names = (str(left), str(right))

    def size(n: Optional[int]) -> str:
        return "?" if n is None else f"{n:,} bytes"

    lines = [f"{names[0]}  {size(result.left_size)}",
             f"{names[1]}  {size(result.right_size)}", ""]
    if result.error is not None:
        lines.append(f"Could not compare: {result.error}")
    elif result.identical:
        lines.append("Identical")
    elif result.offset is None:
        lines.append("Different (sizes differ)")
    else:
        lines.append(f"Different: first difference at offset "
                     f"{result.offset:,} (0x{result.offset:X})")
    return "\n".join(lines)


def _inline(left, right) -> bool:
    """Whether the compare is quick enough to run on the UI thread."""
    if path_schemes.is_uri(str(left)) or path_schemes.is_uri(str(right)):
        return False
    try:
        return max(left.stat().st_size, right.stat().st_size) <= _INLINE_MAX
    except OSError:
        return True  # compare_bytes reports the error at once


def show_byte_comparison(panel: Any, tasks, left, right, *, config: Any = None,
                         z: int = 80, background: bool = True,
                         known: Optional[ByteComparison] = None) -> None:
    """Compare ``left`` and ``right`` and report the verdict in a message box.

    ``known`` is a result the caller already holds (the directory diff's), shown
    without reading anything. Otherwise a small local pair is compared inline,
    and the rest on a task from ``tasks`` with a cancellable progress dialog."""

    def report(result: ByteComparison) -> None:
        if result.error is not None:
            logger.warning(f"Compare {left} / {right}: {result.error}")
        show_message_box(panel, describe(left, right, result),
                         title="Compare Files", icon="info", z=z)
        panel.render()

    if known is not None:
        report(known)
        return
    if _inline(left, right):
        report(compare_bytes(left, right))
        return

    task = Task(f"Comparing {left.name}", config=config, kind="compare",
                busy_label="Comparing…", exclusive=False)

    def run(t: Task) -> dict:
        prog = t.progress
        prog.start_operation(OperationType.COPY, 1, description="Comparing")
        prog.update_operation_total(1)
        prog.update_progress(left.name, 0)
        result = compare_bytes(left, right, checkpoint=t.checkpoint,
                               on_bytes=prog.update_file_byte_progress)
        return {"comparison": result}

    def on_done(res: dict) -> None:
        result = res.get("comparison")
        if result is None:  # cancelled
            logger.info(f"Compare {left.name} cancelled")
            panel.render()
            return
        report(result)

    tasks.submit(task, panel, run=run, on_done=on_done, z=z, background=background)
