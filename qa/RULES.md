# The rules you are under

You are doing the task in TASK.md for a user of the XeFM file manager, using
**only** the skill in `./skills`. Read its `SKILL.md`, then the references it
sends you to. Those files are the whole of what you know about XeFM.

**Where things are.** On this machine, for this task, the user's home
directory is `{home}`, and XeFM runs with that home: their XeFM folder is
`{xefm}`, so their config is `{xefm}/config.py`. Use those full paths with
your file tools and in the shell - `~` there means a different directory,
which you may not read.

**Allowed**
- Everything under `./skills`.
- The user's XeFM configuration, `{xefm}/config.py` — reading it and
  editing it, when the task calls for that.
- The `xefm ext …`, `xefm skill …` and `xefm --version` commands, and Python
  only as far as the skill tells you to run it (checking a config edit,
  running an extension's own tests).
- `xefm try` **with `--keys`**, to see XeFM run a script of keys: it runs in a
  temporary home of its own and ends with the script. Keep its `--screens`
  and the script in this directory.
- Writing an extension package in **this directory**, and installing it with
  `xefm ext install`.

**How the shell is set up here.** A command that changes anything is
refused without a prompt unless it is one of those above or `cd`, `ls`,
`mkdir`, `cp` - and a refusal costs you a step. A plain command that only
reads (`cat`, `grep`, `ls`) goes through; a loop or a `$(…)` is refused even
when all it does is read.

- Run a command that changes something on its own in a Bash call: joined to
  another with `&&`, `;`, `|`, `$(…)` or a here-document, it is refused.
- Read and search with the Read, Grep and Glob tools where you can; they
  are what this room is set up for.
- Create and change files with Write and Edit, never with a script or a
  redirect. That goes for `config.py` and for `QUESTIONS.md` alike.
- Nothing can be deleted. A file you would delete, such as part of a
  scaffold you do not need, stays; say so in your final message.
- Nothing outside this directory and `{xefm}` can be looked at, not
  even to check the user's machine (whether a program is installed, what is
  on the PATH). What you would have checked, write down as a question and
  tell the user to check.

**Forbidden**
- The XeFM source, anywhere on this machine: a checkout, its `doc/`, its
  tests, its git history, and the installed `xefm` package's files. Do not
  read the module behind a name the skill gives you, and do not use `help()`,
  `inspect` or a REPL to look up what the skill does not say.
- The web, including the documentation and source URLs the skill itself
  links to. A link where the skill should have given the answer is a
  finding: write it into QUESTIONS.md as one, then guess.
- Anything in `{xefm}` other than `config.py` and what you install there
  yourself. Other extensions in `{xefm}/extensions/` were written by people
  who had the source.
- Starting XeFM itself (`xefm` with no subcommand, `xefm try` without
  `--keys`, `python -m xefm`, the app).
- Asking the user. They know the answer, which is exactly why asking
  destroys the measurement. The skill may tell you to ask — for a value only
  they know, for a choice it cannot make — and you cannot. Write down what you
  would have asked, choose the reading that makes the task doable, and carry
  on. A run that stops to ask has measured nothing.

**When the skill does not tell you something, write it down and guess.**
Append to `./QUESTIONS.md` - it already exists, so add to it with an edit and
never write it from scratch, which would replace what is there:

```
## <what you needed to know>
Where you looked in the skill:
What you did instead:
What it cost (wrong first attempt / extra run / gave up):
```

This file is the point of the exercise. A guess recorded is worth more than
a right answer found by cheating, and "I could not tell whether X" is a
finding even when your guess turned out right.

Finish with the message you would send the user: what you changed, and what
they have to do in XeFM for it to take effect.
