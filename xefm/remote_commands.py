"""The ``xefmctl`` command table (discussions #900, #951, #952).

One table describes every command: its words, arguments, options, what it
does, and how its answer reads as text. The client (:mod:`xefm.remote_cli`)
parses with it and prints ``xefmctl help`` / ``help --json`` from it; the
skill's reference page (``references/xefmctl.md``) is generated from it too,
so the three never disagree.

``xefmctl`` is for an AI agent first: an agent in a terminal session XeFM
started, with the ``xefm`` skill, next to a user looking at XeFM. So:

- A command is an ``ActionContext`` call, named the same, with ``-`` for
  ``_``: ``pane cd`` is ``ctx.pane.cd``, ``invoke`` is ``ctx.invoke``, a list
  is ``X list`` for ``ctx.Xs()``.
- ``--json`` on every command prints one JSON object per line.
- A command the user takes part in waits for them with ``--wait`` (always,
  for ``confirm``, ``choose`` and ``input``).

Standard library only, and nothing from ``xefm``: the client loads this file
by path, from XeFM's own interpreter run with ``-I``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PANES = ("active", "other", "left", "right")

#: The longest request XeFM takes, in bytes. A request carries what the
#: command reads from standard input (``show-markdown -``, ``pane open-list
#: -``), so it is sized for a long document or many thousand paths. The
#: client refuses a longer one before sending it, with a message; the
#: listener would drop it with nothing to say back.
MAX_REQUEST = 8 * 1024 * 1024

# What a command does to XeFM, for the gate (what a key could do now) and the
# session policy (what an agent's session may do).
READ = "read"          # answers from the state; never refused for the UI
CHANGE = "change"      # changes the file manager: let in as a key would be
WRITE = "write"        # changes files: confirmed in XeFM for an agent
ASK = "ask"            # asks the user in XeFM and waits for the answer


@dataclass(frozen=True)
class Arg:
    name: str
    #: "1", "?", "*" or "+".
    nargs: str = "1"
    #: A path: relative ones are taken from the shell's directory; a URL
    #: (``ssh://``, ``archive://``...) is passed as written. "-" reads the
    #: items from standard input, one per line.
    path: bool = False
    stdin: bool = False
    help: str = ""


@dataclass(frozen=True)
class Opt:
    name: str                  # "--pane"
    #: The value's name, or "" for a flag.
    value: str = ""
    choices: tuple = ()
    help: str = ""
    #: A path value (taken from the shell's directory).
    path: bool = False
    short: str = ""


@dataclass(frozen=True)
class Command:
    words: tuple
    summary: str
    effect: str = READ
    args: tuple = ()
    opts: tuple = ()
    #: How one answered item reads as text without --json (str.format over
    #: the item's keys). "" prints nothing per item.
    text: str = "{path}"
    #: Items arrive as they are found (a search): printed as they come.
    stream: bool = False
    #: --wait is offered (the user takes part); "always" waits regardless.
    wait: str = ""
    details: str = ""
    #: Answered by the client alone (help).
    local: bool = False

    @property
    def name(self) -> str:
        return " ".join(self.words)

    def opt(self, name: str) -> Opt | None:
        return next((o for o in self.opts if o.name == name or o.short == name), None)


PANE = Opt("--pane", "PANE", PANES, "the pane: active (the default), other, left or right")
SHOW = Opt("--show", help="also show the results in a pane, as a list the user can work with")
TITLE = Opt("--title", "TEXT", help="the title of what is shown")
LIMIT = Opt("--limit", "N", help="stop after N items")
WAIT = Opt("--wait", help="wait until it is done (or the user answered) and say how it went")
CASE = Opt("--case", help="match capitals exactly")
NO_RECURSIVE = Opt("--no-recursive", help="this folder only, not the ones below")
NUL = Opt("-0", help="end each path with NUL instead of a newline")

ENTRY_TEXT = "{path}"

COMMANDS: tuple[Command, ...] = (
    # --- orientation ------------------------------------------------------------
    Command(("state",), "both panes, the screen on now and what is open over it: "
            "start here", text="{text}",
            details="One call for what the user is looking at: each pane's "
                    "directory, cursor, selection and filter; which pane is "
                    "active; the screen shown; a viewer or dialog open over "
                    "the panes."),

    # --- a pane (ctx.pane) ---------------------------------------------------------
    Command(("pane", "path"), "the pane's directory (or the URL it shows)", opts=(PANE,)),
    Command(("pane", "entries"), "every item the pane lists, in its order",
            opts=(PANE, LIMIT)),
    Command(("pane", "focused"), "the item under the cursor", opts=(PANE,)),
    Command(("pane", "selected"), "the selected items", opts=(PANE, NUL)),
    Command(("pane", "cd"), "point the pane at a folder; with --focus, put the "
            "cursor on an item there", CHANGE,
            args=(Arg("path", "?", path=True, help="default: this shell's directory"),),
            opts=(PANE, Opt("--focus", "NAME", help="the item to put the cursor on"))),
    Command(("pane", "select"), "select items in the pane by name or glob", CHANGE,
            args=(Arg("pattern", "*", help="names or globs (*.jpg); none with --all"),),
            opts=(PANE, Opt("--all", help="every item")), text="{text}"),
    Command(("pane", "unselect"), "unselect items in the pane by name or glob", CHANGE,
            args=(Arg("pattern", "*"),), opts=(PANE, Opt("--all", help="every item")),
            text="{text}"),
    Command(("pane", "open-list"), "show paths as a list in the pane, where every "
            "file operation works on them", CHANGE,
            args=(Arg("path", "+", path=True, stdin=True,
                      help="paths or URLs, or - to read them from standard input"),),
            opts=(PANE, TITLE), text=""),
    Command(("pane", "refresh"), "re-read the pane", CHANGE, opts=(PANE,), text=""),
    Command(("pane", "activate"), "make the pane the active one", CHANGE,
            opts=(PANE,), text=""),

    # --- places and searches: any XeFM path -------------------------------------------
    Command(("entries",), "what a folder holds, anywhere XeFM can go (ssh://, s3://, "
            "archives, virtual folders)",
            args=(Arg("url", "+", path=True),),
            opts=(Opt("--recursive", help="the folders below too"),
                  Opt("--depth", "N", help="with --recursive: how deep"),
                  LIMIT, SHOW, PANE, TITLE),
            stream=True),
    Command(("find-files",), "files whose names match, below a folder anywhere "
            "XeFM can go (find_files)",
            args=(Arg("pattern", help="a glob (*.psd) or a part of the name"),
                  Arg("url", "*", path=True, help="where to look (default: the pane's folder)")),
            opts=(CASE, NO_RECURSIVE, LIMIT, SHOW, PANE, TITLE), stream=True),
    Command(("find-in-files",), "lines that match, in the files below a folder "
            "anywhere XeFM can go (find_in_files)",
            args=(Arg("pattern"), Arg("url", "*", path=True,
                                      help="where to look (default: the pane's folder)")),
            opts=(CASE, Opt("--word", help="whole words only"),
                  Opt("--regex", help="PATTERN is a regular expression"),
                  NO_RECURSIVE, LIMIT, SHOW, PANE, TITLE),
            text="{path}:{line}: {text}", stream=True),
    Command(("index-search",), "the OS index (Spotlight, Windows Search) "
            "(index_search)",
            args=(Arg("query"), Arg("url", "?", path=True, help="the folder to search in")),
            opts=(LIMIT, SHOW, PANE, TITLE), stream=True),
    Command(("read",), "a file's text, anywhere XeFM can go", args=(Arg("url", path=True),),
            opts=(Opt("--max-bytes", "N", help="read at most N bytes (default 1000000)"),),
            text="{text}"),
    Command(("fetch",), "copy a file from anywhere XeFM can go to a local file, "
            "and print where", args=(Arg("url", path=True),
                                     Arg("local", "?", path=True, help="default: a temporary file")),
            text="{path}"),

    # --- showing --------------------------------------------------------------------
    Command(("view",), "open a file in XeFM's viewer, on the file manager's screen",
            CHANGE, args=(Arg("path", path=True),),
            opts=(Opt("--line", "N", help="scroll to line N"),), text=""),
    Command(("diff",), "compare two files (or two folders) in XeFM", CHANGE,
            args=(Arg("left", path=True), Arg("right", path=True)), text=""),
    Command(("show-markdown",), "show Markdown in XeFM's viewer", CHANGE,
            args=(Arg("file", path=True, stdin=True,
                      help="a Markdown file, or - for standard input"),),
            opts=(TITLE,), text=""),

    # --- files (ctx.copy / move / trash / delete) ------------------------------------------
    Command(("copy",), "copy items to a folder, through XeFM's copy", WRITE,
            args=(Arg("source", "+", path=True, stdin=True),),
            opts=(Opt("--to", "DIR", path=True, help="the destination folder"), WAIT),
            text="{path}", wait="option"),
    Command(("move",), "move items to a folder, through XeFM's move", WRITE,
            args=(Arg("source", "+", path=True, stdin=True),),
            opts=(Opt("--to", "DIR", path=True, help="the destination folder"), WAIT),
            text="{path}", wait="option"),
    Command(("trash",), "move items to the OS trash", WRITE,
            args=(Arg("path", "+", path=True, stdin=True),), opts=(WAIT,),
            text="{path}", wait="option"),
    Command(("delete",), "delete items for good (refused in an agent's session)", WRITE,
            args=(Arg("path", "+", path=True, stdin=True),), opts=(WAIT,),
            text="{path}", wait="option"),

    # --- asking the user (ctx.confirm / choose / input / message) ---------------------------
    Command(("confirm",), "ask the user yes or no in XeFM; exit status 0 for yes, 1 for no",
            ASK, args=(Arg("prompt"),), opts=(TITLE,), text="{answer}", wait="always"),
    Command(("choose",), "have the user pick one item in XeFM; prints it (exit status "
            "1 if cancelled)", ASK, args=(Arg("title"), Arg("item", "+")),
            text="{answer}", wait="always"),
    Command(("input",), "ask the user for a line of text in XeFM; prints it (exit "
            "status 1 if cancelled)", ASK, args=(Arg("prompt"),),
            opts=(Opt("--default", "TEXT", help="the text to start with"), TITLE),
            text="{answer}", wait="always"),
    Command(("message",), "write a line to XeFM's log pane", CHANGE,
            args=(Arg("text"),), text=""),

    # --- actions (ctx.actions / invoke) ------------------------------------------------
    Command(("action", "list"), "every action invoke takes, with what it does and "
            "its keys", text="{name}\t{description}"),
    Command(("action", "show"), "what one action does, in full", args=(Arg("name"),),
            text="{text}"),
    Command(("invoke",), "run an action by name, as its key would on the file "
            "manager's screen", CHANGE, args=(Arg("name"),), opts=(PANE,), text=""),

    # --- screens and terminal sessions ---------------------------------------------
    Command(("screen", "list"), "the screens, the one shown first",
            text="{marker} {id}\t{label}"),
    Command(("screen", "show"), "show a screen (files, or a terminal session's id)",
            CHANGE, args=(Arg("id"),), text=""),
    Command(("terminal-session", "list"), "XeFM's terminal sessions",
            text="{marker} {id}\t{name}\t{state}\t{directory}"),
    Command(("terminal-session", "start"), "start a terminal session (a shell by "
            "default)", CHANGE,
            args=(Arg("command", "*", help="the program and its arguments"),),
            opts=(Opt("--cwd", "DIR", path=True), Opt("--name", "NAME"),
                  Opt("--hidden", help="start it without showing it")),
            text="{id}"),
    Command(("terminal-session", "close"), "end a terminal session", WRITE,
            args=(Arg("id"),), text=""),

    Command(("help",), "the commands, or one command in full", args=(Arg("command", "*"),),
            text="", local=True),
)

COMMON_OPTS = (Opt("--json", help="one JSON object per line"),
               Opt("--help", short="-h", help="this command's help"))


def find(words: list[str]) -> tuple[Command | None, int]:
    """The command named by the leading ``words`` and how many it took."""
    best: tuple[Command | None, int] = (None, 0)
    for cmd in COMMANDS:
        n = len(cmd.words)
        if tuple(words[:n]) == cmd.words and n > best[1]:
            best = (cmd, n)
    return best


def nouns() -> dict[str, list[str]]:
    """The verbs of each noun that has some (``pane``: path, entries, ...)."""
    out: dict[str, list[str]] = {}
    for cmd in COMMANDS:
        if len(cmd.words) == 2:
            out.setdefault(cmd.words[0], []).append(cmd.words[1])
    return out


def synopsis(cmd: Command) -> str:
    parts = ["xefmctl", *cmd.words]
    for a in cmd.args:
        name = a.name.upper()
        parts.append({"1": name, "?": f"[{name}]", "*": f"[{name}...]",
                      "+": f"{name}..."}[a.nargs])
    for o in cmd.opts:
        parts.append(f"[{o.name} {o.value}]" if o.value else f"[{o.name}]")
    return " ".join(parts)


def usage() -> str:
    """``xefmctl help``: one line per command."""
    width = max(len(c.name) for c in COMMANDS)
    lines = ["usage: xefmctl COMMAND [ARGS] [--json]", ""]
    for cmd in COMMANDS:
        lines.append(f"  {cmd.name.ljust(width)}  {cmd.summary}")
    lines += ["",
              "Start with `xefmctl state`. `xefmctl help COMMAND` tells one command "
              "in full; `xefmctl help --json` describes them all.",
              "These work in a shell XeFM started and act on that XeFM's file "
              "manager, as of now."]
    return "\n".join(lines)


def command_help(cmd: Command) -> str:
    lines = [synopsis(cmd), "", cmd.summary + "."]
    if cmd.details:
        lines += ["", cmd.details]
    if cmd.args:
        lines.append("")
        for a in cmd.args:
            lines.append(f"  {a.name.upper():<14}{a.help}")
    opts = [*cmd.opts, *COMMON_OPTS]
    lines.append("")
    for o in opts:
        flag = f"{o.name} {o.value}".strip()
        lines.append(f"  {flag:<14}{o.help}")
    if cmd.wait == "always":
        lines += ["", "Waits for the user's answer."]
    return "\n".join(lines)


def describe() -> list[dict]:
    """``xefmctl help --json``: every command, for an agent to read."""
    out = []
    for cmd in COMMANDS:
        if cmd.local:
            continue
        out.append({
            "command": cmd.name,
            "synopsis": synopsis(cmd),
            "summary": cmd.summary,
            "details": cmd.details,
            "effect": cmd.effect,
            "streams": cmd.stream,
            "waits": cmd.wait or "no",
            "args": [{"name": a.name, "nargs": a.nargs, "path": a.path,
                      "stdin": a.stdin, "help": a.help} for a in cmd.args],
            "options": [{"name": o.name, "value": o.value, "choices": list(o.choices),
                         "help": o.help} for o in cmd.opts],
        })
    return out


def reference_markdown() -> str:
    """The skill's ``references/xefmctl.md``, generated by ``make
    skill-references``."""
    lines = [
        "# xefmctl: commands",
        "",
        "Generated from `xefm/remote_commands.py`; do not edit by hand.",
        "",
        "`xefmctl` works in a terminal session XeFM started (`XEFM_SESSION` is "
        "set) and acts on that XeFM's file manager. Add `--json` to any command "
        "for one JSON object per line. Exit status: 0 done, 1 failed or the user "
        "said no, 2 a usage mistake, 3 XeFM cannot be reached, 4 XeFM is busy, "
        "5 refused (a dialog is open in XeFM, or this session may not do that); "
        "the message says what to tell the user.",
        "",
    ]
    for noun in _sections():
        title, cmds = noun
        lines += [f"## {title}", ""]
        for cmd in cmds:
            lines += [f"### `{cmd.name}`", "", f"`{synopsis(cmd)}`", "", cmd.summary + "."]
            if cmd.details:
                lines += ["", cmd.details]
            for a in cmd.args:
                if a.help:
                    lines.append(f"- `{a.name.upper()}`: {a.help}")
            for o in cmd.opts:
                lines.append(f"- `{(o.name + ' ' + o.value).strip()}`: {o.help}")
            if cmd.wait == "always":
                lines.append("- Waits for the user's answer.")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _sections():
    groups = [("Orientation", ("state",)), ("A pane", ("pane",)),
              ("Places and searches", ("entries", "find-files", "find-in-files",
                                       "index-search", "read", "fetch")),
              ("Showing", ("view", "diff", "show-markdown")),
              ("Files", ("copy", "move", "trash", "delete")),
              ("Asking the user", ("confirm", "choose", "input", "message")),
              ("Actions", ("action", "invoke")),
              ("Screens and terminal sessions", ("screen", "terminal-session"))]
    for title, heads in groups:
        yield title, [c for c in COMMANDS if c.words[0] in heads and not c.local]
