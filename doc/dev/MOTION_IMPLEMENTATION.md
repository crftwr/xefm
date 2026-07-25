# Motion & Pane Focus Chrome — Implementation

How XeFM's modal entrance, reduced-motion switch, and per-theme pane focus chrome
are put together, and — more usefully — *why* they are split between XeFM and
PuiKit the way they are.

User-facing behavior: `doc/COLOR_SCHEMES_FEATURE.md` (Motion & text effects section).

---

## 1. Where each piece lives

| Piece | Home | Why there |
|---|---|---|
| Easing curves (`ease_out_expo`, …) | `puikit/easing.py` | Pure math; every backend and both playback models consume the same curve |
| Reduced-motion switch | `puikit.Backend` / `Panel` | The backend owns the two self-driven motions (shader clock, post-effect roll); the Panel owns transitions |
| `draw_corner_brackets` | `puikit.DrawContext` | Needs the grid/vector branch, and that branch belongs in the Panel layer, never in an app |
| Text animation | `puikit/textfx.py` (kinds) + `Panel` (timing/trigger) | Applied at the `draw_text` seam, so every text widget takes part at zero cost — see §5 |
| Modal entrance hints | `xefm/dialog_geometry.py` | An app-level *choice* (which curve, how long), not a framework capability |
| Pane frame / dim | `xefm/file_pane.py` + theme data | App-specific chrome, driven entirely by `Theme.extras` |

The dividing line: PuiKit owns *what is possible and how it degrades*; XeFM owns
*which of it to use*. A new curve or a new frame shape is a PuiKit change; a
theme wanting brackets is a data change with no code behind it at all.

---

## 2. Easing

`puikit/easing.py` is a registry of pure `progress → progress` functions plus
`resolve(name_or_callable, default)`. An animation names one through its hints:

```python
panel.animate(dialog, hints={"transition": "scale", "easing": "ease_out_expo"})
```

Two consumers, and they default differently **on purpose**:

- **GUI backends** (`Animation.eased`) default to `ease_out_quad`, which is
  exactly the `1 - (1 - p) ** 2` both backends hardcoded before easing was
  selectable. Existing transitions are unchanged.
- **Panel-driven channels** (`_GeometryAnimation`, `_ColorAnimation`) default to
  **linear**, because that is what they have always been (`CLAUDE.md`: "Geometry
  interpolation is linear"). A drawer slide is unchanged unless it names a curve.

`resolve` never raises on an unknown name — curve names arrive from themes and
user config files, and a typo should cost the intended timing, not the app.

### Easing and the 2-frame policy

`_anim_progress` applies a curve **only** to continuously-interpolated
animations. A stepped (terminal) animation stays linear, and this is load-bearing
rather than an oversight: the 2-frame policy's single intermediate frame exists to
be *visibly* intermediate, and `ease_out_expo(0.5)` is `0.999` — running the
intermediate frame through the curve would place it on top of the target and turn
the beat into one abrupt jump.

---

## 3. Reduced motion

Deliberately **not** a capability. A capability says what a backend *can* do;
this says what the user has asked it *not* to, and it flips at runtime.

- `Backend.set_reduced_motion()` stores it (a class-level default, so no backend
  is forced to call `super().__init__()`), then calls
  `_on_reduced_motion_changed()`.
- `Panel.animate()` returns `False` immediately — the same contract as a still
  backend, so an `on_complete` caller (a drawer popping its layer once closed)
  does its follow-up at once rather than waiting on a tick that never comes.
- Both GUI backends return `0.0` from `_bg_target()`, reusing the existing
  idle-coast ramp so the scene *decelerates* to a stop rather than cutting out.
  An endlessly looping ambient scene has no "final frame", so its rest state is a
  still one.
- `PostEffect.without_motion()` (defined on the descriptor, so macOS and Windows
  cannot disagree about which fields count as motion) drops `flicker` and `roll`
  and keeps everything else — a CRT theme still looks like a CRT.

### The carve-out that matters

`request_animation_ticks` is **not** gated. That tick drives functional work as
well as decoration — draining a worker thread's results into the UI, following a
growing log, the progressive-search dialog's queue. Silencing it would turn a
motion preference into a broken app. A decorative self-driven widget instead
reads `ctx.reduced_motion` and draws its resting frame.

XeFM applies the config value in `XeFMApp.__init__` *before* the first theme is
applied, so a reduced-motion launch never plays the opening beat even once and
the theme's background comes up already stopped.

---

## 4. The modal entrance

`xefm.dialog_geometry.animate_open()` is the single definition, called by all
eleven modals. Previously each call site spelled out its own
`{"transition": "fade", "duration_ms": 150}`, which is exactly the kind of thing
that drifts.

The transition is a `scale` that also fades. That combination did not exist
before this work: `scale` was a pure CTM/Direct2D transform with no alpha, so
switching the dialogs to it would have traded the fade away. Both GUI backends
now honor a `fade: True` hint on a `scale` by opening the *same* offscreen
transparency layer a plain fade uses — compositing the group once at the group
opacity rather than multiplying each primitive's alpha, which double-blends where
a dialog's own fills overlap (see `puikit/docs/animation_compositing.md`).

On Windows this needed a new `"layer+transform"` teardown marker, since the old
one could express a layer or a transform but not both.

---

## 5. Text animation (`puikit.textfx`)

How a string *arrives* on screen. This went through two wrong shapes before the
right one, and the reasons are worth keeping.

**Attempt 1 — a `Typewriter` widget.** Wrong for the same reason the original
design document's "Effect plugin" idea was: it forces an app to *swap widget
types* to get an effect, so it can never animate a `Label`, a `TextBlock`, or a
list row that already exists. It shipped with no call site anywhere.

**Attempt 2 — a per-string `reveal` transition** (`panel.animate(..., key=...)`
paired with `ctx.revealed_text(s, key=...)`). Better, but it did not scale and it
could not be theme-driven:

- the start and the draw had to agree on a key, so every adopting widget needed
  its own bespoke helper — `reveal_message` existed for a widget with *two*
  `draw_text` calls, and FilePane would have needed its own;
- cost was per string. A 50-row FilePane draws ~200 strings, so it meant ~200
  `animate()` calls with 200 coordinated keys per listing;
- nothing connected it to a theme, so XeFM would have written
  `if theme.extras.get(...)` at every call site.

**What it is now.** Three parts, each answering one requirement:

| Requirement | Mechanism |
|---|---|
| Per-theme | `theme.extras['text_effect']`, read by `Panel.text_effect`. No app code decides. |
| Works on any text widget | Applied inside `DrawContext.draw_text` — the one seam every string passes through. |
| Low cost per widget | **Zero.** Widgets are unchanged; opting *out* is one attribute, `animates_text = False`. |
| Low cost per animation | A pure `(text, progress, frame, params) -> str` in `TEXT_EFFECTS`. No dataclass, no Panel branch, no backend change. |

Five kinds ship: `typewriter` (plain left-to-right reveal, the Sci-Fi default),
`scatter` (characters landing in random order), `decode` (tail churning as junk
until the head passes over it), `wipe` (tail held open by a fill glyph),
`flicker` (interference that calms). Adding a sixth is one function and one dict
entry — `test_adding_a_kind_is_one_function` states that as a test.

The three *reveal* kinds (`typewriter`, `scatter`, `decode`) share one renderer,
`_render_reveal`, and differ only in a `threshold(i, n, salt)` function saying
when each character resolves. Two options ride on it:

- **`flash`** — a character shows as a solid block for an instant as it lands.
  This is as close to "flash a rectangle" as a kind can get, and the limit is the
  contract, not the idea: a kind returns a *string*, and `draw_text` applies one
  style per run, so a per-character colored or inverted rectangle would need
  per-character styling the rendering API cannot express. A block glyph fills its
  cell exactly and needs none, so it renders identically on every backend.
  Thresholds are compressed into `[0, 1-flash]` so the last character finishes
  its flash instead of being cut off at progress 1.
- **`hidden`** — the stand-in for an un-revealed character: blanks, or
  `"scramble"` for churning junk (which is all `decode` is).

`scatter`'s order is salted by a **deterministic** hash of the string
(`_text_salt`, not `hash()`, which Python randomizes per process). Content-derived
so two different strings scatter differently — otherwise a pane of equal-length
rows would reveal in identical order and read as a marching pattern.

Trailing blanks are trimmed from a reveal, so a blank-tailed kind returns a bare
prefix and paints nothing over cells it does not own, while *interior* gaps keep
their spacing — which is what holds a scattered reveal's columns still.

### Who chooses what

Authority is split, and the split is what keeps a widget preference from
overriding the user:

| Decision | Owner |
|---|---|
| *Whether* text animates at all | the **theme** — nothing else can turn it on |
| The pacing (`duration_ms`, `stagger_ms`, `max_rows`) | the **theme**, though a widget may override it |
| The *flavor* for one widget's subtree | the **widget**, via a `text_effect` class attribute |
| Opting out entirely | the **widget**, via `animates_text = False` |

`textfx.merge` layers a widget's variant over the theme's effect, so
`{"kind": "scatter"}` changes only the kind and inherits the timing. A widget
preference is inert under a theme that opts out, and reduced motion still wins
over everything.

XeFM's `TextViewer` uses this: `{"kind": "scatter", "flash": 0.10}`. Typing suits
a *line*, where the eye follows one reveal left to right; a full screen has no
single place to follow, so a left-to-right reveal reads as a slow wipe while
landing everywhere at once fills the page in the same time.

The variant is **inherited down the subtree** (`DrawContext._text_variant`,
propagated by `draw_child`), and that was a bug before it was a feature: the
viewer draws its header itself but delegates the body to a `_ScrollBody` child,
so the first version scattered the header while the body kept typing. A child
with its own `text_effect` still wins over an inherited one.

### Grid vs proportional

A placeholder glyph only occupies the same space as the character it replaces
when the run is **column-aligned**. On a proportional face a blank is far
narrower than a `W` and a block has its own advance, so a gap held open with one
displaces every resolved glyph after it — over a base unit of drift on realistic
UI-font advances.

The fix is to stop deriving position from the *drawn string* at all. On a
proportional run a kind emits **one glyph per source character** — the character,
a substitution, or `textfx.HIDDEN` — so the result stays index-aligned, and
`DrawContext._draw_measured` places each visible piece at the x its character
will finally occupy, measured from the real text. Hidden positions are simply not
drawn: a gap needs no placeholder because nothing after it depends on the drawn
string's width. Runs of untouched characters draw together; each substitution
draws alone, since its own advance would otherwise shift the rest of its run.

Prefix widths are memoized in `Panel._prefix_cache` and released when nothing is
animating. Measuring a *growing prefix* is how kerning is honored (see
`puikit.text.elide`), so it costs O(n) backend calls per string — and a reveal
redraws the same string every frame for its whole duration.

**Two earlier attempts failed, and both are worth remembering:**

1. *Width-matched placeholders.* Correct on a grid, wrong on a proportional face
   for the reason above.
2. *Trimming to the contiguous resolved prefix.* Fixed the positions and
   destroyed the animation: a scattered reveal's contiguous prefix stays empty
   until nearly the end, so the text sat invisible behind the flash block and
   then appeared all at once. **Reported as a bug from actually using it** — the
   position tests all passed, because they checked that nothing moved without
   checking that anything was visible. `test_text_keeps_arriving_throughout` is
   the assertion that was missing.

A third option — degrading the *order* to left-to-right — was rejected: it makes
the animation correct at the cost of not being the animation that was asked for.

Grid runs are untouched by all of this: a terminal, a log view, a code viewer's
body and a pane's size/date columns all keep the padded single-draw path.

### Text inputs never animate

A widget with `wants_text_input` is showing *editable* content: a value under a
caret that the user may be mid-way through typing. Scrambling or withholding it
is wrong in a way no theme should be able to ask for, so text input implies
`animates_text = False` — and any future input widget inherits that without
knowing this system exists. An explicit `animates_text = True` still wins.

### Pacing is counted in rows, not strings

`stagger_ms` steps per **row** and `max_rows` caps rows, both keyed on the
`y` a widget draws at. Strings sharing a row are one visual unit: they step
together and cost one row against the cap.

Counting strings instead was wrong twice, in opposite directions, because the
strings-per-row ratio varies by an order of magnitude between widgets — XeFM's
file pane draws about **1.0** strings per row, its syntax-highlighted text viewer
about **8.7**:

- a 40-*string* cap covered only ~5 lines of the viewer, so the rest of the page
  simply appeared;
- the same cap cut a 60-row file pane off at row 39 — the reported "latter half
  doesn't animate".

With rows as the unit the number means what a reader expects ("the first N rows
animate, each one step later") and holds for any widget. XeFM's Sci-Fi theme now
paces at `stagger_ms: 8` with `max_rows: 120` — a backstop for a very tall
window (~1s), not a coverage limit.

A widget may still override the pacing. `TextViewer` sets `stagger_ms: 0` and
`max_rows: 0`: a screenful materializes on one clock rather than cascading down
the page, and with no cascade there is nothing to bound.

### The trigger policy is the load-bearing decision

**On-appear, not on-change.** A widget animates when it was absent from the
previous frame. Text changing *in place* does not retrigger.

That distinction is the whole difference between usable and broken. On-change
would re-decode every row of a file pane on every scroll step, and re-animate a
status counter every frame. The Panel tracks a set of widget ids drawn last
frame — no string diffing at all, which is also why it costs nothing per frame.

A wholesale content swap is the case only the app can recognize, so it says so:
`Panel.animate_text(widget)`, **one call per widget, not per string**. XeFM calls
it from `_process_result_queue`, the single point where a new listing lands for
both the sync and async paths.

### A third trigger, for streams

A log view defeats both of the above: it never leaves the screen (so the appear
trigger cannot fire) and `animate_text` is too coarse (it would re-animate every
line already on screen, not the one that just arrived). So `draw_text` takes an
optional `anim_key` naming the *content's* identity, and the Panel animates
anything above a per-widget high-water mark.

A mark is **one integer**, not the set of every key ever drawn — which is what
keeps a stream running for days bounded. In-flight keys are held separately and
expire individually, so a key mid-animation is not mistaken for already-seen on
the next frame, and a line scrolled back into view is correctly recognized as old.

The key must be stable, which is subtler than it looks in `LogView`: a row index
shifts every time `_trim` drops lines off the front, and `clear()`/`set_lines()`
reset the buffer entirely. `LogView._dropped` counts everything discarded, so
`_dropped + position` only ever increases for the life of the widget. The key is
taken per *logical* line rather than per display row, so a wrapped line's rows
share one key and reveal together, and a re-wrap on resize does not renumber it.

### Details that took a second pass

- **State is per widget, not per string** — `{id(widget): start_time}`. A
  200-string pane is one entry.
- **`stagger_ms` and `max_rows`** live on the effect and are counted in rows —
  see "Pacing is counted in rows, not strings" above. XeFM's Sci-Fi values
  (260 ms, 8 ms stagger, 120 rows) are tuned around this firing on *every
  directory change*.
- **Noise is decorrelated per string.** The junk hash is keyed by character
  index, so equal-length rows scrambled to byte-identical junk and a pane read as
  a repeating pattern rather than as data. The string's position within the
  widget is folded into the churn counter to break that up.
- **Reduced motion** returns `None` from `Panel.text_effect`, so every widget
  honors it with no code of its own.

XeFM's `show_about` is deliberately a *plain* `show_message_box` call: under
Sci-Fi the body decodes because the box appeared, under every other theme it
opens plainly, and no XeFM call site knows the effect exists.

---

## 6. Pane focus chrome

### The frame

`DrawContext.draw_corner_brackets(w, h, style, arm=, thickness=)` marks a
region's four corners and leaves its edges open. Capability-resolved: eight
hairline strokes on `vector_shapes`, four box-drawing glyphs (`┏ ┓ ┗ ┛`, extended
with `━ ┃`) on a grid.

Both paths clamp the arms so at least one base unit of gap always survives
between opposite legs. The grid clamp is `(n - 3) // 2`, not `(n - 2) // 2` —
the latter is off by one at even sizes, where the two arms end up adjacent and
fill the row edge to edge, closing the frame into the solid border it exists to
avoid. A test covers exactly this.

XeFM draws it **only on a vector backend**, and the reason is space rather than
backend: the frame lives in the sub-cell margin a GUI pane already has
(`INNER_MARGIN` / `CONTENT_PAD_CELLS`), which is zero on a grid. Every row of
`FilePane` is a file row, so on a terminal the brackets land *on* the first and
last filenames and eat their leading characters — which is what the first version
of this did, until a render test showed `┏━ile0.txt`. Reserving a frame gutter
instead would spend two columns and two rows decorating a pane whose focus a
terminal already marks through the cursor cue. Same reasoning as the framework's
`divider="subtle"`: spend the sub-unit where it is free, spend nothing where it
is not.

### The dim

Applied at the two points where every row foreground funnels through `ctx.ink`,
and applied to the *source* color — **before** the legibility pass, never after.
`ctx.ink` is floor-only, so it lifts anything the wash pushed under the readable
threshold back over it. That makes the dim self-limiting: a theme cannot
configure its resting pane into illegibility, which matters because the user is
usually comparing the two panes and still has to read the resting one.

`_dim_ink` returns the color unchanged at zero, so the focused pane and every
opted-out theme go through an identical code path.

### Theme wiring

`extras['pane_frame']` and `extras['pane_dim']`, threaded through `_theme()` and
`_THEME_OVERRIDE_MAP` so a user's `config.py` can set them per theme. Sci-Fi is
the only built-in that opts in; a test asserts every other theme carries neither,
which is the property that makes this a safe addition to an existing palette set.

---

## 7. Tests

| File | Covers |
|---|---|
| `puikit/tests/test_easing.py` | Curve contract (endpoints, monotonicity, clamping), resolution fallbacks, and that stepped progress ignores easing |
| `puikit/tests/test_reduced_motion.py` | The switch, transitions declining, the tick carve-out, `without_motion` |
| `puikit/tests/test_textfx.py` | Every kind's contract (lands exact, width-stable, deterministic), effect coercion, theme gating, the on-appear trigger, stagger/cap, many-string widgets, and the stream trigger (appended lines animate, scrolled-back lines do not, identity survives trimming and `clear()`) |
| `puikit/tests/test_corner_brackets.py` | Both render paths, containment, the arms-never-meet clamp |
| `test/test_pane_focus_chrome.py` | Theme opt-in/out, frame on vector only, filenames intact on grid, dim strength and clamping, the shared open transition, Sci-Fi's `text_effect` values |

### A caveat about the app-level tests

`XeFMApp` tests construct a real app, which reads the developer's own
`~/.xefm/config.py` **and** restores the last-used theme from `~/.xefm/state.db`.
So a machine whose saved theme carries a `text_effect` renders a different first
frame than one whose does not, and a test asserting on freshly-drawn text can
pass for one developer and fail for another. This is pre-existing environment
dependence, not new, but the text effect is the first feature to expose it — it
surfaced through a user theme inheriting `base: 'Sci-Fi'`.

Tests that assert on drawn text should call `panel.set_text_effect(False)`, which
force-disables the effect regardless of theme (`test_compare_dialog.py` does).
The real fix is isolating the app tests from the user's config and state.
