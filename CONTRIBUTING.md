# Contributing to XeFM

Thanks for helping. English or Japanese are both fine in issues, discussions
and pull requests (日本語でも大丈夫です).

## Where things go

| You have… | Go to |
|---|---|
| a bug | [Issues → Bug report](https://github.com/crftwr/xefm/issues/new/choose) |
| a small, clear feature request | [Issues → Feature request](https://github.com/crftwr/xefm/issues/new/choose) |
| an idea that needs design discussion | [Discussions → Ideas](https://github.com/crftwr/xefm/discussions/categories/ideas) |
| a question | [Discussions → Q&A](https://github.com/crftwr/xefm/discussions/categories/q-a) |
| an extension or a config recipe to share | [Discussions → Show and tell](https://github.com/crftwr/xefm/discussions/categories/show-and-tell) — it can then be listed on the [wiki](https://github.com/crftwr/xefm/wiki/Extensions) |
| a security problem | [SECURITY.md](SECURITY.md), not a public issue |

## Before writing code: could it be an extension?

Many features do not need to be in XeFM itself. An
[extension package](doc/EXTENSIONS_FEATURE.md) can add actions, menu items,
event hooks, themes, sort orders, filters, picture formats, path schemes and
syntax highlighting, and you can publish it on your own schedule. An AI coding
agent can write one for you with [the XeFM skill](doc/AGENT_SKILL_FEATURE.md).

When an extension cannot do what you need because the public API is missing
something, that gap is a good issue to file.

## Working on XeFM itself

XeFM is a Python package (`xefm/`) on top of
[PuiKit](https://github.com/crftwr/puikit), its UI framework, which is a
separate repository. Python 3.11 or later.

```bash
git clone https://github.com/crftwr/xefm.git
cd xefm
make venv          # creates .venv with every dependency
make run           # the terminal app
make run-gui       # the desktop window, for development
python -m pytest test/test_<area>.py   # run tests from the repo root
make help          # everything else, including PuiKit co-development
```

Changes to rendering, widgets or a backend belong in PuiKit, not here.

### Pull requests

- Keep a pull request to one change, with a title and description that say
  what changes for a user.
- Add or update tests in `test/` for behavior you change.
- Use the unified logger (`xefm.log_manager.getLogger`), never `print()`, in
  `xefm/`. [CLAUDE.md](CLAUDE.md) lists the coding conventions; it is written
  for AI agents but applies to everyone.
- A user-facing feature gets a page in `doc/` (`*_FEATURE.md`) and an
  implementation note in `doc/dev/` (`*_IMPLEMENTATION.md`).
- Pull requests written with an AI assistant are welcome. Please read and run
  what it produced before submitting, and say in the description what you
  checked.

XeFM is MIT licensed. By contributing you agree that your contribution is
released under the same license.
