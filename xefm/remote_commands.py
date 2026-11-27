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
  for ``confirm``, ``choose``, ``input`` and ``pane pick``).
- **Where an action takes its items from the pane, a command is told them**
  (#962): any number of them, anywhere XeFM can go. That is the only way a
  command is freer than the action; what it does with an item is the
  action's. ``--from pane|selection`` takes the items from the pane the same
  way for every command that takes items: ``pane`` is the pane's folder (the
  entries, when it shows a list), ``selection`` the selected items or else
  the one under the cursor. A folder is searched below; a file is itself.

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
# Every other effect needs XeFM's screen: refused (exit status 6) while
# terminal mode has handed the terminal to the shell xefmctl runs in.
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
    #: Given more than once, its values are a list.
    multi: bool = False


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
FROM = Opt("--from", "WHAT", ("pane", "selection"),
           "take the items from the pane instead of the arguments: pane (its "
           "folder, or the entries of the list it shows) or selection (the "
           "selected items, or else the one under the cursor)")
SIMILAR_METHODS = ("identical", "image", "video", "audio")

ENTRY_TEXT = "{path}"

#: What ``read``, ``fetch`` and ``find-in-files`` say of an agent's session.
AGENT_READS = (
    "In an AI agent's session, XeFM asks the user before a file's contents are "
    "read outside the session's folder, once for each folder. Files directly in "
    "a folder the user went to in a pane are not asked about.")

COMMANDS: tuple[Command, ...] = (
    # --- orientation ------------------------------------------------------------
    Command(("state",), "both panes, the screen on now and what is open over it: "
            "start here", text="{text}",
            details="One call for what the user is looking at: each pane's "
                    "directory, cursor, selection and filter; which pane is "
                    "active; the screen shown; a viewer or dialog open over "
                    "the panes. In an AI agent's session also whether its "
                    "sandbox is on, off or not known (`sandbox` in --json)."),

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
    Command(("pane", "pick"), "have the user select items in XeFM and press Enter; "
            "prints them (exit status 1 if cancelled with Esc)", ASK,
            opts=(PANE, Opt("--prompt", "TEXT", help="what to ask for, shown in "
                            "XeFM's log pane")),
            wait="always",
            details="The pane becomes the active one and every key works as "
                    "usual - moving, selecting, changing folders, switching "
                    "panes - until Enter, which answers the active pane's "
                    "selection (or the item under its cursor), or Esc."),

    # --- places and searches: any XeFM path -------------------------------------------
    Command(("entries",), "what a folder holds, anywhere XeFM can go (ssh://, s3://, "
            "archives, virtual folders)",
            args=(Arg("url", "*", path=True, help="the folders (default: the pane's "
                      "folder); a file is listed as itself"),),
            opts=(Opt("--recursive", help="the folders below too"),
                  Opt("--depth", "N", help="with --recursive: how deep"),
                  FROM, LIMIT, SHOW, PANE, TITLE),
            stream=True),
    Command(("find-files",), "files whose names match, below a folder anywhere "
            "XeFM can go (find_files)",
            args=(Arg("pattern", help="a glob (*.psd) or a part of the name"),
                  Arg("url", "*", path=True, help="where to look (default: the pane's folder)")),
            opts=(CASE, NO_RECURSIVE, FROM, LIMIT, SHOW, PANE, TITLE), stream=True),
    Command(("find-in-files",), "lines that match, in the files below a folder "
            "anywhere XeFM can go (find_in_files)",
            args=(Arg("pattern"), Arg("url", "*", path=True,
                                      help="where to look (default: the pane's folder)")),
            details=AGENT_READS,
            opts=(CASE, Opt("--word", help="whole words only"),
                  Opt("--regex", help="PATTERN is a regular expression"),
                  NO_RECURSIVE, FROM, LIMIT, SHOW, PANE, TITLE),
            text="{path}:{line}: {text}", stream=True),
    Command(("index-search",), "the OS index (Spotlight, Windows Search) "
            "(index_search)",
            args=(Arg("query"), Arg("url", "*", path=True,
                                    help="the folders to search in (default: the pane's folder)")),
            opts=(FROM, LIMIT, SHOW, PANE, TITLE), stream=True),
    Command(("find-similar",), "groups of similar files below local folders, "
            "found by the similar-files scan (find_similar)",
            args=(Arg("url", "*", path=True,
                      help="the folders or files to scan (default: the pane's folder)"),),
            opts=(Opt("--method", "METHOD", SIMILAR_METHODS,
                      "what to compare (required): identical (the same content), "
                      "image, video or audio"),
                  Opt("--threshold", "T", help="how alike: loose, standard, strict, "
                      "or a number from 0 to 1 (not for identical)"),
                  FROM, LIMIT, SHOW, PANE, TITLE),
            text="{group}\t{path}", stream=True,
            details="One line per file: the group's number, then the path; the "
                    "first file of a group is the one the others are like. The "
                    "scan runs in a process of its own and shows in XeFM's jobs "
                    "list; nothing is printed until it ends. With --show the "
                    "groups open in the pane as a tree."),
    Command(("path-scheme", "list"), "the kinds of place XeFM can open besides the "
            "local disk (ssh://, s3://, archive://, and the ones PATH_SCHEMES and "
            "extensions add)", text="{name}\t{source}"),
    Command(("read",), "a file's text, anywhere XeFM can go", args=(Arg("url", path=True),),
            opts=(Opt("--max-bytes", "N", help="read at most N bytes (default 1000000)"),),
            details=AGENT_READS, text="{text}"),
    Command(("fetch",), "copy a file from anywhere XeFM can go to a local file, "
            "and print where", args=(Arg("url", path=True),
                                     Arg("local", "?", path=True, help="default: a temporary file")),
            text="{path}",
            details=AGENT_READS + " Writing to LOCAL is asked too; without it the copy goes "
                    "to a new temporary folder."),

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
            opts=(Opt("--to", "DIR", path=True, help="the destination folder"),
                  FROM, PANE, WAIT),
            text="{path}", wait="option"),
    Command(("move",), "move items to a folder, through XeFM's move", WRITE,
            args=(Arg("source", "+", path=True, stdin=True),),
            opts=(Opt("--to", "DIR", path=True, help="the destination folder"),
                  FROM, PANE, WAIT),
            text="{path}", wait="option"),
    Command(("trash",), "move items to the OS trash", WRITE,
            args=(Arg("path", "+", path=True, stdin=True),), opts=(FROM, PANE, WAIT),
            text="{path}", wait="option"),
    Command(("delete",), "delete items for good (refused in an agent's session)", WRITE,
            args=(Arg("path", "+", path=True, stdin=True),), opts=(FROM, PANE, WAIT),
            text="{path}", wait="option"),

    Command(("rename",), "rename items to the names a plan gives, after the user "
            "confirms them in XeFM's rename review", WRITE,
            opts=(Opt("--plan", "FILE", path=True,
                      help='a JSON list of {"path": ..., "name": ...}, or - for '
                           'standard input'), WAIT),
            text="{path}\t{status}", wait="option",
            details="Each name is a new name in the item's own folder: rename "
                    "does not move. The plan is checked as Rename in Editor "
                    "checks an edited list (swaps and chains are fine; two items "
                    "on one name, or a name already taken, refuse the plan) and "
                    "nothing moves until the user says Rename."),

    # --- tags and attributes (ctx.tags / add_tags / remove_tags / attributes) ---------------
    Command(("tag", "list"), "the tags XeFM knows, most recently applied first",
            text="{name}\t{color}"),
    Command(("tag", "add"), "tag items, where the OS keeps tags (Finder, "
            "user.xdg.tags, S3)", WRITE,
            args=(Arg("name", help="the tag"),
                  Arg("path", "+", path=True, stdin=True,
                      help="the items, or - to read them from standard input")),
            opts=(Opt("--tag", "NAME", multi=True, help="another tag (repeat for more)"),
                  Opt("--color", "COLOR", ("gray", "green", "purple", "blue", "yellow",
                                           "red", "orange"),
                      "the color of a tag new to XeFM, where the storage keeps colors"),
                  FROM, PANE, WAIT),
            text="{path}\t{status}", wait="option"),
    Command(("tag", "remove"), "take tags off items", WRITE,
            args=(Arg("name", help="the tag"),
                  Arg("path", "+", path=True, stdin=True,
                      help="the items, or - to read them from standard input")),
            opts=(Opt("--tag", "NAME", multi=True, help="another tag (repeat for more)"),
                  FROM, PANE, WAIT),
            text="{path}\t{status}", wait="option"),
    Command(("attribute", "list"), "every attribute XeFM knows (size, tags, "
            "ATTRIBUTES', a tree's)", text="{name}\t{type}\t{label}"),
    Command(("attribute", "get"), "attribute values of items, computed now "
            "(get_attributes)",
            args=(Arg("path", "+", path=True, stdin=True,
                      help="the items, or - to read them from standard input"),),
            opts=(Opt("--attributes", "A,B", help="the attributes (default: all)"),
                  FROM, PANE, LIMIT),
            text="{text}", stream=True,
            details="One line per item: the path, then name=value for each "
                    "attribute, tab-separated. An on-request attribute is "
                    "computed, and a folder's size is its total, so this can "
                    "take a while. --json gives the values as they are."),

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
            "manager's screen", CHANGE, args=(Arg("name"),), opts=(PANE,), text="",
            details="In an AI agent's session, an action that runs other programs "
                    "(open_with_os, open_items_with_os, sync_python_packages), "
                    "reload_config, and an action of the user's own or an "
                    "extension's are asked in XeFM first."),

    # --- the user's own session skills (~/.xefm/skills/, #1009) ----------------------
    Command(("skill", "list"), "the user's own skills for agent sessions, in "
            "~/.xefm/skills/, and whether sessions get them",
            text="{name}\t{state}",
            details="A skill that fails the check is left out of sessions. One "
                    "written or changed now reaches the next session."),
    Command(("skill", "check"), "check skills in ~/.xefm/skills/ by name (all of "
            "them by default); exit status 1 if one fails", args=(Arg("name", "*"),),
            text="{name}\t{state}",
            details="Run it after writing ~/.xefm/skills/<name>/SKILL.md: it says "
                    "what keeps a skill out of sessions (the frontmatter's name and "
                    "description)."),

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
            text="{id}",
            details="In an AI agent's session, asked in XeFM first; the new "
                    "session is restricted as the agent's is."),
    Command(("terminal-session", "close"), "end a terminal session", WRITE,
            args=(Arg("id"),), text=""),

    Command(("help",), "the commands, or one command in full", args=(Arg("command", "*"),),
            text="", local=True),
)

# What an AI agent's session may do with a command without the user: XeFM runs
# it with the user's own rights, outside any sandbox of the agent's (#995).
ALLOWED = "allowed"    # at once: it reads no file's contents, and changes none
ASKED = "asked"        # the user agrees first, each time
DEPENDS = "depends"    # asked for some of what it can be given
REFUSED = "refused"    # never

#: Every command's class. A command that has none fails the tests.
AGENT_CLASS = {
    "state": ALLOWED, "help": ALLOWED,
    "pane path": ALLOWED, "pane entries": ALLOWED, "pane focused": ALLOWED,
    "pane selected": ALLOWED, "pane cd": ALLOWED, "pane select": ALLOWED,
    "pane unselect": ALLOWED, "pane open-list": ALLOWED, "pane refresh": ALLOWED,
    "pane activate": ALLOWED,
    "pane pick": ALLOWED, "confirm": ALLOWED, "choose": ALLOWED, "input": ALLOWED,  # they ask
    "message": ALLOWED,
    "entries": ALLOWED, "find-files": ALLOWED, "index-search": ALLOWED,
    "find-similar": ALLOWED, "path-scheme list": ALLOWED, "tag list": ALLOWED,
    "attribute list": ALLOWED, "attribute get": ALLOWED,
    "view": ALLOWED, "diff": ALLOWED, "show-markdown": ALLOWED,  # the user sees it, not the agent
    "action list": ALLOWED, "action show": ALLOWED,
    # A name and a description from ~/.xefm/skills/, what the session is handed.
    "skill list": ALLOWED, "skill check": ALLOWED,
    "screen list": ALLOWED, "screen show": ALLOWED, "terminal-session list": ALLOWED,
    "read": DEPENDS, "fetch": DEPENDS, "find-in-files": DEPENDS,  # a folder not its own
    "invoke": DEPENDS,                  # an action that runs programs or code
    "terminal-session close": DEPENDS,  # one not its own
    "copy": ASKED, "move": ASKED, "trash": ASKED, "rename": ASKED,
    "tag add": ASKED, "tag remove": ASKED, "terminal-session start": ASKED,
    "delete": REFUSED,
}

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


def needs_screen(cmd: Command) -> bool:
    """Whether ``cmd`` needs XeFM's screen, and so is refused while terminal
    mode has handed the terminal to the shell (exit status 6)."""
    return cmd.effect != READ


def synopsis(cmd: Command) -> str:
    parts = ["xefmctl", *cmd.words]
    for a in cmd.args:
        name = a.name.upper()
        parts.append({"1": name, "?": f"[{name}]", "*": f"[{name}...]",
                      "+": f"{name}..."}[a.nargs])
    for o in cmd.opts:
        part = f"[{o.name} {o.value}]" if o.value else f"[{o.name}]"
        parts.append(part + "..." if o.multi else part)
    return " ".join(parts)


def usage() -> str:
    """``xefmctl help``: one line per command."""
    width = max(len(c.name) for c in COMMANDS)
    lines = ["usage: xefmctl COMMAND [ARGS] [--json]", ""]
    for cmd in COMMANDS:
        mark = "*" if needs_screen(cmd) and not cmd.local else " "
        lines.append(f" {mark}{cmd.name.ljust(width)}  {cmd.summary}")
    lines += ["",
              "* uses XeFM's screen: refused (exit status 6) while XeFM is "
              "suspended until this shell exits (terminal mode).",
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
    if needs_screen(cmd) and not cmd.local:
        lines += ["", "Uses XeFM's screen: refused (exit status 6) while XeFM is "
                      "suspended until this shell exits."]
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
            "needs_screen": needs_screen(cmd),
            "agent": AGENT_CLASS[cmd.name],
            "streams": cmd.stream,
            "waits": cmd.wait or "no",
            "args": [{"name": a.name, "nargs": a.nargs, "path": a.path,
                      "stdin": a.stdin, "help": a.help} for a in cmd.args],
            "options": [{"name": o.name, "value": o.value, "choices": list(o.choices),
                         "repeat": o.multi, "help": o.help} for o in cmd.opts],
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
        "said no, 2 a usage mistake, 3 XeFM cannot be reached, 4 XeFM is busy "
        "(try again), 5 refused (a dialog is open in XeFM, or this session may "
        "not do that), 6 XeFM is suspended until this shell exits (terminal "
        "mode: only commands that read work, for the rest of the session; do "
        "not retry); the message says what to tell the user.",
        "",
        "Commands marked *Uses XeFM's screen* are the ones refused with 6. "
        "While XeFM is suspended, `--show` is ignored and the results come "
        "back to the terminal only. `xefmctl state` says whether XeFM is "
        "suspended (`suspended` in `--json`).",
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
            if needs_screen(cmd):
                lines.append("- *Uses XeFM's screen.*")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _sections():
    groups = [("Orientation", ("state",)), ("A pane", ("pane",)),
              ("Places and searches", ("entries", "find-files", "find-in-files",
                                       "index-search", "find-similar", "path-scheme",
                                       "read", "fetch")),
              ("Showing", ("view", "diff", "show-markdown")),
              ("Files", ("copy", "move", "trash", "delete", "rename")),
              ("Tags and attributes", ("tag", "attribute")),
              ("Asking the user", ("confirm", "choose", "input", "message")),
              ("Actions", ("action", "invoke")),
              ("Skills", ("skill",)),
              ("Screens and terminal sessions", ("screen", "terminal-session"))]
    for title, heads in groups:
        yield title, [c for c in COMMANDS if c.words[0] in heads and not c.local]
