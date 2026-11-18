"""Shell integration for XeFM's own terminal (discussion #900).

A shell running in XeFM's terminal marks its prompts with OSC 133 (prompt
start, input start, output start, command end with its exit code) and its
working directory with OSC 7, so XeFM knows when the shell is idle at its
prompt - the only time typing into it is safe (inserting the selection) - and
when a command finished.

Shells do not do that on their own, so XeFM injects a few lines, the way
terminals with shell integration do, without touching the user's dotfiles:

- **zsh**: ``ZDOTDIR`` points at a directory of XeFM's whose ``.zshenv``,
  ``.zprofile``, ``.zshrc`` and ``.zlogin`` each source the user's own file of
  that name (from the ``ZDOTDIR`` the user had, else ``$HOME``), then put
  ``ZDOTDIR`` back once startup is over. The hooks go in after the user's
  ``.zshrc``, so a prompt theme set up there is already in place.
- **bash 4.4 or later**: ``--rcfile`` names XeFM's rc file, which sources the
  user's (``~/.bashrc``, or the profile files when a login shell was asked
  for: bash ignores ``--rcfile`` for a login shell, so ``-l`` is turned into
  the same reading order). An older bash - macOS's 3.2 - has no ``PS0``, so
  the end of a command cannot be marked and the shell is left alone: an
  "at the prompt" reading that stays true while a command runs would be
  worse than none.

Any other shell runs as it is. fish 4 emits OSC 133 by itself.

The scripts are written once per process into a private temp directory.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import weakref

from xefm.log_manager import getLogger

logger = getLogger("ShellInteg")

# The marks every shell's hooks print. In zsh's prompt they sit inside
# %{...%}, in bash's inside \[...\], so the line editor counts no width.
_ZSH_HOOKS = r'''
# XeFM shell integration (#900): OSC 133 prompt marks, OSC 7 directory.
if [[ -o interactive && -z ${_xefm_hooked-} ]]; then
  _xefm_hooked=1
  _xefm_precmd() {
    local ret=$?
    if [[ -n ${_xefm_ran-} ]]; then
      printf '\e]133;D;%s\a' "$ret"
      _xefm_ran=
    fi
    printf '\e]7;file://%s%s\a' "${HOST}" "${${PWD//\%/%25}// /%20}"
    printf '\e]133;A\a'
    # A theme may rebuild PS1 before every prompt: mark its end each time.
    [[ $PS1 == *$'\e]133;B'* ]] || PS1="${PS1}%{"$'\e]133;B\a'"%}"
  }
  _xefm_preexec() {
    printf '\e]133;C\a'
    _xefm_ran=1
  }
  typeset -ga precmd_functions preexec_functions
  precmd_functions+=(_xefm_precmd)
  preexec_functions+=(_xefm_preexec)
fi
'''

#: zsh startup file -> what it does besides sourcing the user's file of the
#: same name. ``.zshrc`` adds the hooks; the last file read in each kind of
#: shell (``.zshrc`` for a non-login one, ``.zlogin`` for a login one) gives
#: ``ZDOTDIR`` back, so a shell started from this one is the user's own.
_ZSH_FILES = (".zshenv", ".zprofile", ".zshrc", ".zlogin")


def _zsh_file(name: str) -> str:
    lines = [
        "# Written by XeFM (#900): source the user's own file, then go on.",
        '_xefm_zd=$ZDOTDIR',
        'ZDOTDIR=${XEFM_USER_ZDOTDIR:-$HOME}',
        f'[[ -r "$ZDOTDIR/{name}" ]] && source "$ZDOTDIR/{name}"',
        # The user's .zshenv may move ZDOTDIR itself: follow it.
        'XEFM_USER_ZDOTDIR=$ZDOTDIR',
        'ZDOTDIR=$_xefm_zd',
    ]
    if name == ".zshrc":
        lines.append(_ZSH_HOOKS)
        lines.append('[[ -o login ]] || { ZDOTDIR=$XEFM_USER_ZDOTDIR; '
                     'unset XEFM_USER_ZDOTDIR _xefm_zd; }')
    if name == ".zlogin":
        lines.append('ZDOTDIR=$XEFM_USER_ZDOTDIR; unset XEFM_USER_ZDOTDIR _xefm_zd')
    return "\n".join(lines) + "\n"


_BASH_RC = r'''# Written by XeFM (#900): read what bash would have, then add the marks.
if [[ -n ${XEFM_BASH_LOGIN-} ]]; then
  unset XEFM_BASH_LOGIN
  [[ -r /etc/profile ]] && . /etc/profile
  for _xefm_f in ~/.bash_profile ~/.bash_login ~/.profile; do
    if [[ -r $_xefm_f ]]; then . "$_xefm_f"; break; fi
  done
  unset _xefm_f
else
  [[ -r ~/.bashrc ]] && . ~/.bashrc
fi
if (( BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 4) )); then
  _xefm_prompt() {
    local ret=$?
    if [[ -n ${_xefm_started-} ]]; then printf '\e]133;D;%s\a' "$ret"; fi
    _xefm_started=1
    local pwd=${PWD//%/%25}
    printf '\e]7;file://%s%s\a\e]133;A\a' "$HOSTNAME" "${pwd// /%20}"
    [[ $PS1 == *$'\e]133;B'* ]] || PS1="${PS1}\[\e]133;B\a\]"
    return $ret
  }
  PROMPT_COMMAND="_xefm_prompt${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
  PS0="${PS0-}"$'\e]133;C\a'
fi
'''


class _Scripts:
    """The integration files, written on first use."""

    def __init__(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="xefm-shell-")
        weakref.finalize(self, shutil.rmtree, self.dir, True)
        self.zdotdir = os.path.join(self.dir, "zsh")
        os.mkdir(self.zdotdir)
        for name in _ZSH_FILES:
            with open(os.path.join(self.zdotdir, name), "w", encoding="utf-8") as f:
                f.write(_zsh_file(name))
        self.bashrc = os.path.join(self.dir, "bashrc")
        with open(self.bashrc, "w", encoding="utf-8") as f:
            f.write(_BASH_RC)


_scripts: _Scripts | None = None


def _get_scripts() -> _Scripts:
    global _scripts
    if _scripts is None:
        _scripts = _Scripts()
    return _scripts


def _shell_name(argv0: str) -> str:
    name = os.path.basename(argv0).lower()
    return name[:-4] if name.endswith(".exe") else name


def apply(argv: list[str], env: dict) -> list[str]:
    """``argv`` and ``env`` for running the shell ``argv`` with integration:
    ``env`` is changed in place, and the argv to run is returned (the same
    one when the shell is not one XeFM integrates, or when the command runs
    something rather than an interactive shell)."""
    if not argv:
        return argv
    name = _shell_name(argv[0])
    args = argv[1:]
    if "-c" in args or any(a.startswith("-") and "c" in a[1:] and not a.startswith("--")
                           for a in args):
        return argv  # runs a command, not an interactive shell
    try:
        if name == "zsh":
            scripts = _get_scripts()
            if "ZDOTDIR" in env:
                env["XEFM_USER_ZDOTDIR"] = env["ZDOTDIR"]
            else:
                env.pop("XEFM_USER_ZDOTDIR", None)
            env["ZDOTDIR"] = scripts.zdotdir
            return argv
        if name == "bash":
            if any(a in ("--rcfile", "--init-file", "--norc", "--posix") for a in args):
                return argv  # the user chose how it starts
            scripts = _get_scripts()
            login = [a for a in args if a in ("-l", "--login")]
            rest = [a for a in args if a not in ("-l", "--login")]
            if login:
                env["XEFM_BASH_LOGIN"] = "1"
            else:
                env.pop("XEFM_BASH_LOGIN", None)
            return [argv[0], "--rcfile", scripts.bashrc, *rest]
    except OSError as exc:
        logger.warning(f"Shell integration unavailable: {exc}")
    return argv
