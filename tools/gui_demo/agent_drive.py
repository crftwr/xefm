"""Drive an AI agent take: the scenes wait on the agent itself, not on fixed
holds. Claude Code's hooks in the VM (setup_claude_vm.sh) append each
PreToolUse / Stop / Notification event to /tmp/agent-events.jsonl; one ssh
``tail -F`` streams them here.

    $VENV/bin/python tools/gui_demo/agent_drive.py still|record OUT MODULE

MODULE (in tools/gui_demo) defines SCENES, a list of steps. Besides
drive.py's actions (keys, {"text"}, {"click"}, ...):

    {"submit": "text"}        type the text, press Enter: the agent works
    {"wait_stop": 240}        until the agent's turn ends (Stop hook)
    {"wait_tool": "xefmctl (move|trash)", "timeout": 240}
                              until the agent is about to run a matching
                              Bash command (an XeFM dialog follows)
    {"approve": "Move|Trash", "look": 2.5}
                              until the agent's turn ends, approve (Enter)
                              each XeFM dialog of that name after showing
                              it for `look` s (xefmctl state, via
                              vm_xefm_state.sh)
    {"hold": 2.0}             a pause the edit keeps at normal speed
    {"still": "name"}         a still now

Writes OUT/timeline.json: each step with its start/end on the recording's
clock and its kind ("work" spans are what make_agent_video.py speeds up).
"""
import importlib, json, queue, re, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from drive import Driver  # noqa: E402


class Events:
    def __init__(self):
        self.q = queue.Queue()
        self.p = subprocess.Popen(
            [str(HERE / "vm.sh"), ": > /tmp/agent-events.jsonl; tail -n 0 -F /tmp/agent-events.jsonl"],
            stdout=subprocess.PIPE, text=True)
        threading.Thread(target=self._read, daemon=True).start()
        time.sleep(1.0)

    def _read(self):
        for line in self.p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.q.put(json.loads(line))
            except ValueError:
                pass

    def drain(self):
        while not self.q.empty():
            self.q.get_nowait()

    def wait(self, pred, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                ev = self.q.get(timeout=0.25)
            except queue.Empty:
                continue
            name = ev.get("hook_event_name")
            cmd = (ev.get("tool_input") or {}).get("command", "")
            print("   event", name, ev.get("tool_name", ""), cmd[:100], flush=True)
            if pred(ev):
                return ev
            if name == "Notification":
                print("   ! notification:", ev.get("message"), flush=True)
        raise TimeoutError("agent event not seen")

    def close(self):
        self.p.terminate()


def dialog_over_files():
    """'dialog (Move)' while one is open over the file manager, else ''."""
    r = subprocess.run([str(HERE / "vm_xefm_state.sh")], capture_output=True, text=True)
    try:
        over = json.loads(r.stdout).get("files_screen") or ""
    except ValueError:
        return ""
    return over if over.startswith("dialog") else ""


def run(out: Path, video: bool, module: str):
    scenes = importlib.import_module(module)
    out.mkdir(parents=True, exist_ok=True)
    d, ev = Driver(), Events()
    timeline, n = [], 0
    t0 = time.monotonic()
    if video:
        d(op="record", path=str((out / "raw.mp4").resolve()))
        t0 = time.monotonic()
    now = lambda: round(time.monotonic() - t0, 2)  # noqa: E731
    try:
        for step in scenes.SCENES:
            start, kind = now(), "act"
            if isinstance(step, dict) and "submit" in step:
                ev.drain()
                d.type(step["submit"], delay=step.get("delay", 0.045))
                time.sleep(0.4)
                d.key("Enter")
            elif isinstance(step, dict) and "wait_stop" in step:
                kind = "work"
                ev.wait(lambda e: e.get("hook_event_name") == "Stop", step["wait_stop"])
            elif isinstance(step, dict) and "wait_tool" in step:
                kind = "work"
                pat = re.compile(step["wait_tool"])
                ev.wait(lambda e: e.get("hook_event_name") == "PreToolUse"
                        and pat.search((e.get("tool_input") or {}).get("command", "")),
                        step.get("timeout", 240))
            elif isinstance(step, dict) and "approve" in step:
                # Until the agent's turn ends, approve every XeFM dialog whose
                # name matches, after showing it for `look` seconds.
                pat, look = re.compile(step["approve"]), step.get("look", 2.5)
                end = time.monotonic() + step.get("timeout", 300)
                kind, seen = "work", 0
                while time.monotonic() < end:
                    try:
                        e = ev.q.get(timeout=0.1)
                        print("   event", e.get("hook_event_name"), e.get("tool_name", ""), flush=True)
                        if e.get("hook_event_name") == "Stop":
                            break
                        continue
                    except queue.Empty:
                        pass
                    over = dialog_over_files()
                    if over and pat.search(over):
                        timeline.append({"start": start, "end": now(), "kind": "work", "step": "agent"})
                        seen += 1
                        time.sleep(look)
                        d(op="still", path=str((out / f"dialog-{seen}.png").resolve()))
                        timeline.append({"start": now() - look, "end": now(), "kind": "hold", "step": over})
                        d.key("Enter")
                        # The next dialog may follow at once, under the same
                        # name, so don't wait for "gone": give it a moment.
                        time.sleep(1.2)
                        start = now()
                        print(f"   approved {over}", flush=True)
                    time.sleep(0.5)
                else:
                    raise TimeoutError("agent did not finish")
            elif isinstance(step, dict) and "hold" in step:
                kind = "hold"
                time.sleep(step["hold"])
            elif isinstance(step, dict) and "still" in step:
                n += 1
                d(op="still", path=str((out / f"{n:02d}-{step['still']}.png").resolve()))
            else:
                d.run_action(step)
            timeline.append({"start": start, "end": now(), "kind": kind, "step": step})
            print(f"{start:7.2f} {kind:5s} {json.dumps(step, ensure_ascii=False)[:90]}", flush=True)
    finally:
        if video:
            d(op="stop")
        ev.close()
        (out / "timeline.json").write_text(json.dumps(timeline, indent=1, ensure_ascii=False))
        d(op="still", path=str((out / "zz-end.png").resolve()))


if __name__ == "__main__":
    run(Path(sys.argv[2]), sys.argv[1] == "record", sys.argv[3])
