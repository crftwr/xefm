"""Edit the AI agent takes into one video: the agent's working spans sped
up (with a "6x" badge), a caption at the start of each take, title and
closing cards, fades between takes.

    $VENV/bin/python tools/gui_demo/make_agent_video.py OUT_DIR TAKE_DIR...

Each TAKE_DIR holds raw.mp4 + timeline.json (agent_drive.py record) and a
caption.json: {"title": "...", "theme": "Earth"}.
"""
import json, subprocess, sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1200, 30
FONT = "/System/Library/Fonts/SFNS.ttf"
FADE = 0.4


def font(size, bold=False):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_name("Bold" if bold else "Regular")
    except (OSError, ValueError):
        pass
    return f


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return float(out)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *map(str, args)], check=True)


# --- overlays -------------------------------------------------------------------

def caption_png(path, step, total, title, theme):
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    f1, f2 = font(50, True), font(28)
    sub = f"{step} / {total}  ·  Theme: {theme}"
    tw = max(d.textlength(title, font=f1), d.textlength(sub, font=f2))
    x0, y1 = 70, H - 150
    box = (x0, y1 - 168, x0 + tw + 80, y1)
    d.rounded_rectangle(box, 22, fill=(8, 12, 20, 215), outline=(255, 255, 255, 60), width=2)
    d.text((x0 + 40, y1 - 146), sub, font=f2, fill=(170, 200, 230, 255))
    d.text((x0 + 40, y1 - 96), title, font=f1, fill=(255, 255, 255, 255))
    img.save(path)


def badge_png(path, speed):
    img = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(img)
    f = font(34, True)
    label = f"{speed}x"
    tw = d.textlength(label, font=f)
    x1, y0 = W - 30, 64
    x0 = x1 - (tw + 120)
    d.rounded_rectangle((x0, y0, x1, y0 + 58), 29, fill=(8, 12, 20, 200),
                        outline=(255, 255, 255, 70), width=2)
    tx, cy = x0 + 28, y0 + 29
    for k in range(2):
        ox = tx + k * 22
        d.polygon([(ox, cy - 14), (ox + 22, cy), (ox, cy + 14)], fill=(255, 200, 90, 255))
    d.text((tx + 60, y0 + 9), label, font=f, fill=(255, 255, 255, 255))
    img.save(path)


def card(path, png, seconds):
    ffmpeg("-loop", 1, "-t", seconds, "-i", png, "-vf",
           f"fps={FPS},format=yuv420p,fade=in:st=0:d={FADE},fade=out:st={seconds - FADE}:d={FADE}",
           "-c:v", "libx264", "-preset", "medium", "-crf", 16, path)


def card_png(path, background, lines):
    bg = Image.open(background).convert("RGB").resize((W, H)).filter(ImageFilter.GaussianBlur(18))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (4, 8, 14)), 0.55)
    d = ImageDraw.Draw(bg)
    y = H // 2 - sum(s for _, s, _ in lines) // 2 - 20
    for text, size, colour in lines:
        f = font(size, size >= 60)
        d.text(((W - d.textlength(text, font=f)) / 2, y), text, font=f, fill=colour)
        y += int(size * 1.5)
    bg.save(path)


# --- one take ---------------------------------------------------------------------

def segments(timeline, total):
    """[(start, end, speed)] covering the take; work spans sped up."""
    segs, t = [], 0.0
    for e in sorted(timeline, key=lambda e: e["start"]):
        a, b = max(e["start"], t), e["end"]
        if b <= a:
            continue
        if a > t:
            segs.append([t, a, 1])
        speed = 1
        if e["kind"] == "work" and b - a > 3.0:
            d = b - a
            target = min(5.0, max(2.5, d / 6))
            speed = max(2, round(d / target))
        segs.append([a, b, speed])
        t = b
    if total > t:
        segs.append([t, total, 1])
    merged = []
    for s in segs:
        if merged and merged[-1][2] == s[2] == 1:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [s for s in merged if s[1] - s[0] > 0.05]


def edit_take(take: Path, out: Path, step, total):
    cap = json.loads((take / "caption.json").read_text())
    tl = json.loads((take / "timeline.json").read_text())
    raw = take / "raw.mp4"
    segs = segments(tl, duration(raw))
    caption_png(out / f"cap{step}.png", step, total, cap["title"], cap["theme"])
    inputs = ["-i", raw, "-loop", 1, "-i", out / f"cap{step}.png"]
    speeds = sorted({s for _, _, s in segs if s > 1})
    for s in speeds:
        badge_png(out / f"badge{s}.png", s)
        inputs += ["-loop", 1, "-i", out / f"badge{s}.png"]
    f, names = [], []
    for i, (a, b, s) in enumerate(segs):
        chain = f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{s},fps={FPS}"
        if s > 1:
            f.append(chain + f"[r{i}]")
            f.append(f"[{2 + speeds.index(s)}:v]trim=duration={(b - a) / s:.3f}[b{i}]")
            f.append(f"[r{i}][b{i}]overlay=0:0:shortest=1[s{i}]")
        else:
            f.append(chain + f"[s{i}]")
        names.append(f"[s{i}]")
    f.append("".join(names) + f"concat=n={len(names)}:v=1:a=0[cat]")
    f.append("[1:v]format=rgba,trim=duration=5.2,fade=in:st=0.3:d=0.4:alpha=1,"
             "fade=out:st=4.6:d=0.5:alpha=1[cap]")
    length = sum((b - a) / s for a, b, s in segs)
    f.append(f"[cat][cap]overlay=0:0:eof_action=pass,format=yuv420p,"
             f"fade=in:st=0:d={FADE},fade=out:st={length - FADE:.3f}:d={FADE}[v]")
    dest = out / f"take{step}.mp4"
    ffmpeg(*inputs, "-filter_complex", ";".join(f), "-map", "[v]", "-r", FPS,
           "-c:v", "libx264", "-preset", "medium", "-crf", 16, dest)
    print(f"take {step}: {duration(raw):.1f}s raw -> {length:.1f}s",
          [(round(a, 1), round(b, 1), s) for a, b, s in segs if s > 1], flush=True)
    return dest


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    takes = [Path(p) for p in sys.argv[2:]]
    first = out / "first.png"
    ffmpeg("-ss", 1.0, "-i", takes[0] / "raw.mp4", "-frames:v", 1, first)
    card_png(out / "intro.png", first, [
        ("XeFM  +  Claude Code", 88, (255, 255, 255)),
        ("AI agent sessions in the desktop app", 44, (190, 214, 236)),
        ("The agent sees what you see, shows you what it finds,", 32, (150, 176, 200)),
        ("and asks you before it changes a file.", 32, (150, 176, 200)),
    ])
    card(out / "intro.mp4", out / "intro.png", 5.0)
    parts = [out / "intro.mp4"]
    for i, t in enumerate(takes, 1):
        parts.append(edit_take(t, out, i, len(takes)))
    last = out / "last.png"
    ffmpeg("-sseof", -1.0, "-i", takes[-1] / "raw.mp4", "-frames:v", 1, last)
    card_png(out / "outro.png", last, [
        ("XeFM", 88, (255, 255, 255)),
        ("Tools > AI Agent Here   ·   Tools > Ask AI Agent...", 40, (190, 214, 236)),
        ("github.com/crftwr/xefm", 36, (150, 176, 200)),
    ])
    card(out / "outro.mp4", out / "outro.png", 5.0)
    parts.append(out / "outro.mp4")
    (out / "list.txt").write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    ffmpeg("-f", "concat", "-safe", 0, "-i", out / "list.txt", "-c", "copy",
           "-movflags", "+faststart", out / "xefm-ai-agent-demo-1920.mp4")
    ffmpeg("-i", out / "xefm-ai-agent-demo-1920.mp4", "-vf", "scale=1280:800:flags=lanczos",
           "-c:v", "libx264", "-preset", "slow", "-crf", 22, "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", out / "xefm-ai-agent-demo-1280.mp4")
    print("total", round(duration(out / "xefm-ai-agent-demo-1920.mp4"), 1), "s")


if __name__ == "__main__":
    main()
