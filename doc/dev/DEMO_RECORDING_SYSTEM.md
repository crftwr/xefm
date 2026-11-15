# Recording the README Demos

The README opens with two demos side by side: **GUI (macOS)**, a video of the
desktop app, and **TUI**, a GIF of the terminal app. Both are scripted, so a
change to the UI can be re-recorded rather than re-performed by hand. This
document is how, and what was learned the hard way.

| | TUI | GUI (macOS) |
|---|---|---|
| Where it runs | a pseudo-terminal on this machine | a Tart macOS VM |
| Input | bytes written to the pty | VNC key and pointer events |
| Capture | the pty's output, as an asciicast | the VM's framebuffer, over VNC |
| Output | GIF (agg), in `doc/images/` | MP4 (ffmpeg), uploaded to GitHub |
| Tool | `tools/make_demo_gif.py` | `tools/gui_demo/` (a prototype; steps in its README) |

## TUI: `tools/make_demo_gif.py`

```bash
PYTHONPATH=. python tools/make_demo_gif.py temp/demo     # demo.cast, demo.gif
```

Needs `pip install 'quality-loop[tui]'` and [agg](https://github.com/asciinema/agg).

It is `xefm try`'s machinery ([TRY_IMPLEMENTATION.md](TRY_IMPLEMENTATION.md))
used as a library: `trial.TryHome` makes the throwaway home, the tool writes a
sample project into it (`~/projects/aurora` and an older
`~/projects/aurora-backup`, so a directory compare finds something), and
`trial.run_script` drives the TUI through `SCENES` and records an asciicast.

- **Retiming.** A raw recording is mostly the runner waiting for the screen
  to settle. agg's `--idle-time-limit` would cap that and the reading pauses
  alike, so the tool retimes the cast itself: every gap is squeezed to
  `MAX_GAP` (0.15 s), then each scene's own `hold` is added before the next
  scene's marker. Typing is sent one character at a time (`typed()`).
- **No temporary paths on screen.** The panes already show `~`. Log lines name
  full paths, so a `sitecustomize.py` that only the demo process imports
  patches PuiKit's `LogView.append` to write the home as `~`. The copy
  confirmation names its destination in full, so the demo config turns
  `CONFIRM_COPY` off.
- **The underline cursor.** `PUIKIT_UNDERLINE_COLOR=1` makes PuiKit treat the
  pty as able to draw a coloured underline, so the cursor is the rule under the
  row rather than `[ ]`. pyte cannot parse that SGR, so the per-step text dumps
  show stray escape text on the cursor row; agg renders it correctly.
- **Shape.** agg's `--line-height 1.125` on a 120x40 terminal gives 1028x646,
  about 16:10: the shape of the GUI video, so the two README columns match in
  height. (agg's default 1.4 gives 1028x804.)

## GUI: a Tart VM driven over the hypervisor's VNC server

### Why a VM, and why VNC

Capturing inside PuiKit was rejected: it cannot see the native menu bar, menus
or the window frame. Recording the real screen ties up the developer's Mac and
needs Screen Recording and Accessibility permissions.

`tart run --vnc-experimental` starts the **Virtualization framework's own VNC
server**, which sits below the guest OS. That one connection gives both halves:

- **Input:** VNC key and pointer events arrive in the guest as virtual
  keyboard and mouse hardware. macOS sees a keyboard, not a program sending
  events, so no Accessibility permission is needed.
- **Capture:** the framebuffer is the guest's real display, after Metal
  compositing, with the mouse cursor drawn in. The GPU background animations
  and the CRT/phosphor effects come through, and no Screen Recording
  permission is needed.

Nothing touches the host's screen.

### The VM

```bash
tart clone ghcr.io/cirruslabs/macos-golden-gate-vanilla:27.0 xefm-demo
tart set xefm-demo --cpu 6 --memory 8192
tart run xefm-demo --vnc-experimental --no-graphics
```

- **`--no-graphics` is required.** Without it Tart opens macOS Screen Sharing
  as a second VNC client, and that client connecting or disconnecting crashes
  Tart (`EXC_BREAKPOINT` in `-[_VZVirtualMachineAccessor addAccessorObserver:]`).
- **One VNC connection per boot.** Reconnecting a client crashes Tart the
  same way. So one long-lived daemon holds the connection. Scripts talk to it
  over a Unix socket and send primitives (key, pointer, still, record, stop),
  so the daemon never needs a restart while the scenes are being tuned.
- **SSH.** The vanilla image's user is `admin` / `admin`. Install a key once
  (with `expect`), then provision over `ssh admin@$(tart ip xefm-demo)`.
- **The app.** Copy `/Applications/XeFM.app` in with `tar … | ssh … tar x`,
  and launch it with `open -a XeFM`. Launching the packaged app rather than
  `--backend gui` makes the menu bar say *XeFM*, not *Python*.
- **Display mode.** The guest boots at 1024x768 HiDPI whatever `tart set
  --display` says. The XeFM bundle's own Python has PyObjC, so the mode is set
  with Quartz (`CGDisplayCopyAllDisplayModes` with
  `kCGDisplayShowDuplicateLowResolutionModes` lists the HiDPI modes, then
  `CGConfigureDisplayWithDisplayMode`, `kCGConfigurePermanently`):

  ```bash
  PY=/Applications/XeFM.app/Contents/Frameworks/PythonT.framework/Versions/Current/bin/python3
  ssh … "PYTHONPATH=/Applications/XeFM.app/Contents/Resources/python_packages $PY - 960 600 1920" < modes.py
  ```

  The demo uses **960x600 points at 2x** (1920x1200 pixels). At 1280x800 the
  file list had too much empty space after the names. 800x500 is too short
  for the View menu.
- **Permissions in the guest.** XeFM's first visits to Desktop, Documents and
  Downloads raise macOS permission prompts. Click *Allow* once in this VM, with
  a VNC click; macOS remembers it per app. A prompt left open takes keyboard
  focus and silently swallows the scenes that follow.
- **A fresh home per take.** Before each recording, replace `~/projects` and
  `~/.xefm`, then relaunch XeFM:
  - `~/.xefm` is built on the host with `StateManager`. The keymap preset is
    set (`keymap.preset`), tips are off (`tips.enabled`), the starting theme is
    set (`theme`), and so are the panes' directories (`pane.left` /
    `pane.right`, `{"path": …}`).
  - The window fills the screen through the saved frame:
    `defaults write com.xefm.app "NSWindow Frame XeFMMainWindow" "0 0 960 570 0 0 960 600 "`.
  - The Dock is set to autohide, so it does not take height from the window.

### The VNC client

A minimal RFB 3.8 client in Python, with numpy for the framebuffer and
`cryptography` for the DES in VNC authentication:

- **Auth:** security type 2 (VNC). DES-encrypt the 16-byte challenge with
  the password, each key byte bit-reversed (a VNC quirk). Triple DES with the
  key repeated three times is single DES, which is how `cryptography` still
  provides it. The password is in the `vnc://:PASSWORD@127.0.0.1:PORT` line
  that `tart run` prints.
- **Pixel format:** 32 bpp true colour, shifts r=16 g=8 b=0, which is BGRX in
  memory. That pipes straight into ffmpeg as `-pix_fmt bgr0`.
- **Encodings:** Raw (0), plus DesktopSize (-223) and ExtendedDesktopSize
  (-308). **The Virtualization framework's server asserts (and Tart dies)
  when a client lacks them** ("It is unclear if we can support clients that
  don't support this pseudo encoding").
- **Updates:** request one non-incremental update, then an incremental one
  after each update arrives. A DesktopSize rectangle means a new
  framebuffer; request a full update again. Changing the guest's display mode
  on a live connection works.
- **Throughput:** raw over localhost keeps up with full-screen animation:
  86–90 distinct frames in every 90 recorded at 30 fps.

### Keys

A VNC `KeyEvent` carries an X11 keysym, down or up. The Virtualization
framework maps it to a key on its virtual keyboard:

- **Named keys:** Return `0xff0d`, Escape `0xff1b`, Tab `0xff09`, BackSpace
  `0xff08`, arrows `0xff51`–`0xff54`, PageUp/Down `0xff55`/`0xff56`, Home/End
  `0xff50`/`0xff57`, F1 `0xffbe`, F10 `0xffc7`.
- **Modifiers** are their own key events around the key: Shift_L `0xffe1`,
  Control_L `0xffe3`, Alt_L `0xffe9` (Option), Super_L `0xffeb` (Command).
- **A keysym becomes a physical key, and its shift is dropped.** `*` arrives
  as `8`, `+` as `=`, and `A` as `a`. So the client sends Shift itself for
  every shifted symbol (a US-layout table: `*` → Shift + `8`) and for capitals.
- **Letters in the scenes are key names, as the keymap writes them.** `V` is
  the v key; quick view is `Shift-V`. (An early version sent `V` as Shift+v,
  and every "view" opened quick view instead.)
- Text is typed one key at a time, about 0.09 s apart, so it looks typed.
- **Open question:** Option held during a drag did not make XeFM copy instead
  of move. The demo shows the move and its confirmation dialog instead.
  Whether Alt_L reaches the app as Option during a drag is not settled.

### Pointer

A `PointerEvent` carries x, y (framebuffer pixels: points × 2) and a button
mask:

- **Clicks:** left is 1, right is 4. A double click is two press/release
  pairs about 0.1 s apart.
- **Wheel:** 8 (up) and 16 (down), each a press and release.
- **Motion:** the cursor is in the framebuffer, so every move is
  interpolated, 60 steps a second with ease-in-out. A jump would teleport the
  cursor in the video.
- **Drags:** press, a small first move to start the drag, a slow move to the
  target, a pause, then release.
- **Native menus are driven with the mouse.** Click the menu title, hover the
  item, move horizontally into its submenu first, then down, so the
  submenu's hover path stays inside it. Coordinates come from stills taken at
  the end of each scene.

### Scenes and timing

Scenes are `(intent, actions, hold)`, as in the TUI tool. A GUI screen cannot
be read as text to tell when it has settled, so each scene simply waits its
`hold`. That also makes the recording's timing final: there is nothing to
retime afterwards. Each scene ends with a still (half size), and those
stills are how the scenes were tuned without watching the video.

### Encoding

The daemon pipes frames at a fixed 30 fps into ffmpeg
(`-f rawvideo -pix_fmt bgr0`, `h264_videotoolbox`, 40 Mbit/s) for the raw
take. The README file is a separate pass from that raw take:

```bash
ffmpeg -i raw.mp4 -vf "scale=960:600:flags=lanczos" -c:v libx264 -preset slow \
       -crf 24 -pix_fmt yuv420p -movflags +faststart -an demo-960x600.mp4
```

960x600 is half the framebuffer: the screen's size in points, text still
legible, 3.8 MB for 68 s. Always encode from the raw take, not from another
encode.

## Publishing

- **The TUI GIF** is committed to `doc/images/xefm-tui-demo.gif`.
  `tools/gen_pypi_readme.py` turns its path into a tagged raw URL for PyPI.
- **The GUI MP4 is not in the repository.** GitHub plays video in a README
  only from its own uploads: drag the file into an issue or PR comment, and
  use the `https://github.com/user-attachments/assets/<id>` URL it gives,
  **as a bare URL on its own line**. GitHub renders that as a player, even
  inside a `<td>`. A `<video>` element pointing into the repository, or at
  that URL, is stripped by GitHub's sanitizer.
- **GitHub Pages** builds the same README with Jekyll, which leaves the bare
  URL as text. A script in `_layouts/default.html` replaces a `td` or `p`
  holding nothing but such a URL with a `<video>` (muted, autoplay, loop). The
  URL redirects to a signed S3 URL that anyone may fetch, so the video plays
  off github.com.
- **PyPI** shows the GUI cell as the URL; it cannot play video.
- Browsers cache the README's images (Pages sends `max-age=600`). After
  replacing a GIF, reload with Cmd+Shift+R before judging it.

## The GUI tool

`tools/gui_demo/` holds the scripts that made the video: the RFB client
(`rfb.py`), the daemon (`vncd.py`), the scene driver (`drive.py`) and the
demo's scenes, the home builder, the guest's display-mode script, and shell
scripts to set up, boot, reset and ssh into the VM. Its
[README](../../tools/gui_demo/README.md) gives the steps. It is a prototype,
and every step is run by hand. Making it a real tool would mean:

- one command that boots the VM, starts the daemon, resets the home, runs
  the scenes and encodes the result;
- dismissing a stray notification banner automatically, not by checking the
  first still.
