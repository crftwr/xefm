# Progress Animation System

Module: `xefm/progress_animator.py`

A small, generalized engine for animated progress indicators (spinners and
progress-bar-style effects) used wherever XeFM needs "something is happening"
feedback — search, and, through `ProgressManager`, file operations. It is a pure
frame generator: it computes which glyph to show based on elapsed time. Rendering
and threading live in the callers.

## Architecture

- **`ProgressAnimator`** — the engine. Holds the pattern table, the configured
  pattern/speed, and the current frame index; advances the frame when enough time
  has passed and formats status strings.
- **`ProgressAnimatorFactory`** — static factory methods that build animators
  preconfigured for common use cases, so callers don't repeat pattern/speed
  choices.

## ProgressAnimator

```python
ProgressAnimator(config, pattern_override=None, speed_override=None)
```

`config` supplies defaults `PROGRESS_ANIMATION_PATTERN` and
`PROGRESS_ANIMATION_SPEED`; the two overrides let a single instance pick a
different pattern or speed without touching config. Key methods:

- `get_current_frame() -> str` — the glyph to show now; advances the frame when
  `animation_speed` seconds have elapsed since the last advance.
- `reset()` — back to frame 0 (call on operation start/finish).
- `set_pattern(pattern)` / `set_speed(speed)` — change either at runtime.
- `get_available_patterns()` / `get_pattern_preview(pattern=None)` — introspection.
- `get_progress_indicator(context_info=None, is_active=True, style='default')` —
  the bare indicator; for the `'progress'` pattern this renders a filling bar
  effect. Styles: `'default'`, `'brackets'`, `'minimal'`.
- `get_status_text(operation_name, context_info=None, is_active=True)` — a full
  line, e.g. `"Searching ⠋ (42 found)"`; when inactive returns a "complete"
  message.

Timing is purely elapsed-time based, so the animation is independent of how often
the caller redraws — a caller can force smoothness by redrawing on a timer even
without new progress data.

### Patterns

The `patterns` table maps a name to a frame list. Available names: `spinner`
(default, Braille), `dots`, `progress` (bar fill), `bounce`, `pulse`, `wave`,
`clock`, `arrow`. An unknown name falls back to `spinner`. The exact frame lists
are defined in the source; treat that as authoritative rather than duplicating
them here.

## ProgressAnimatorFactory

Static builders:

- `create_search_animator(config)` — defaults, tuned for search.
- `create_loading_animator(config)` — `spinner` at speed `0.15`.
- `create_processing_animator(config)` — `progress` at speed `0.25`.
- `create_custom_animator(config, pattern='spinner', speed=0.2)` — arbitrary
  pattern/speed.

## Usage

```python
from xefm.progress_animator import ProgressAnimator, ProgressAnimatorFactory

search_animator = ProgressAnimatorFactory.create_search_animator(config)
status = search_animator.get_status_text("Searching", "42 found", is_active=True)

animator = ProgressAnimatorFactory.create_custom_animator(config, 'progress', 0.3)
animator.set_pattern('wave')   # change at runtime
animator.set_speed(0.1)
```

`ProgressManager` (`xefm/progress_manager.py`) constructs its own
`ProgressAnimator` with `pattern_override='spinner'`, `speed_override=0.08` and
calls `get_current_frame()` while formatting operation status — see
[Progress Manager System](PROGRESS_MANAGER_SYSTEM.md).

## Configuration

```python
# Defaults consumed from config
PROGRESS_ANIMATION_PATTERN = 'spinner'
PROGRESS_ANIMATION_SPEED   = 0.2   # seconds per frame; ~0.1–0.5 is reasonable
```

## Notes

- Thread-safe in practice: animation state is independent of the work being
  tracked; frame updates don't touch the operation's data.
- Minimal cost — a small frame list and a time comparison per call.
- Unicode terminal recommended; `spinner` has the widest glyph compatibility.

## Tests

- `test/test_search_animation.py` — pattern behavior, frame cycling, timing,
  config integration.
- `test/test_search_animation_integration.py` — integration and thread-safety.

## Related

- [Progress Manager System](PROGRESS_MANAGER_SYSTEM.md)
</content>
