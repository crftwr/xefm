# The XeFM Skill for AI Agents

English \| [日本語](AGENT_SKILL_FEATURE.ja.md)

XeFM provides an [Agent Skills](https://agentskills.io) skill, **`xefm`**, that
teaches an AI agent to work with XeFM for you. It covers two things:

- **Editing your configuration**, `~/.xefm/config.py`: key bindings and the
  keymap preset, your editor and diff tool, favorites, file associations,
  external programs, themes, and your own small actions. The agent changes
  only what you asked for and keeps the rest of your file as it is.
- **Writing [extension packages](EXTENSIONS_FEATURE.md)**: the manifest, the
  API an extension may use, settings, dependencies and testing. Its last step
  is `xefm ext check`, which confirms the package meets every extension
  requirement.

The skill is a folder with a `SKILL.md` file and two reference files, so any
agent that reads Agent Skills can use it.

## The quickest way: let your agent install it

Give your agent this page and ask it to install the skill, for example:

> Install the XeFM skill by following
> https://crftwr.github.io/xefm/doc/AGENT_SKILL_FEATURE.html

The agent follows the steps in [Instructions for AI agents](#instructions-for-ai-agents)
below. Once it reports where it put the skill, start a new session with that
agent (most load their skills when a session starts). Then ask for what you
want, for example "bind F12 to reload the configuration in XeFM", or "make an
XeFM extension that …".

The agent never starts XeFM itself. When it has changed your configuration,
it tells you to run **Tools ▸ Reload Configuration** (or to restart XeFM, for
the few settings that need it).

## Installing it yourself

1. Download **`xefm-X.Y.Z-skill.zip`** from the
   [XeFM releases page](https://github.com/crftwr/xefm/releases), from the
   release that matches your XeFM (`xefm --version`, or **Help ▸ About**).
2. Unzip it into your agent's skills folder. The zip holds one folder,
   `xefm/`, which should end up directly inside the skills folder:

   ```
   <skills folder>/xefm/SKILL.md
   ```

   Which skills folder to use:

   | Agent | Skills folder for all your projects |
   |---|---|
   | Most agents that read Agent Skills | `~/.agents/skills/` |
   | Claude Code | `~/.claude/skills/` |
   | Others | the agent's own skills folder — see its documentation |

   To use the skill in one project only, use the same folder name inside that
   project, for example `<project>/.agents/skills/`.
3. If that folder also holds **`xefm-extension-authoring/`**, delete it. It is
   the older, extensions-only version of this skill (XeFM 1.8.0 and earlier),
   and two skills for the same job confuse an agent.
4. Start a new session with the agent.

If `xefm` is on your PATH (a pip, pipx, uv or Homebrew install), the skill is
already on your machine. `xefm skill` prints where it is, and this command copies it into a
skills folder — and removes the old `xefm-extension-authoring/` if it is there:

```bash
xefm skill --install ~/.agents/skills
```

## Updating

The skill describes the configuration and the extension API of one XeFM
version. When you upgrade XeFM, install the skill again from the matching
release. Replace the old `xefm/` folder rather than unzipping on top of it.

To see which XeFM an installed skill describes, look at the
`xefm-version` line near the top of its `SKILL.md`. A version with a
`+dev` part (for example `1.9.0+dev.g1a2b3c4d5`) was made from unreleased
source, newer than that release; the part after `g` names the commit, and a
trailing `.dirty` means the source had uncommitted changes. An agent using the skill checks this against
`xefm --version` itself and tells you once if they differ.

---

## Instructions for AI agents

You were asked to install the `xefm` skill. Follow these steps exactly. The
zip contains only Markdown, so nothing in it needs to be run.

1. **Pick the version.**
   - If `xefm` is on PATH, run `xefm --version`. It prints `XeFM X.Y.Z`; use
     `X.Y.Z`.
   - Otherwise, find the latest release's tag: read `tag_name` from
     `https://api.github.com/repos/crftwr/xefm/releases/latest` (or run
     `gh release view --repo crftwr/xefm --json tagName`). It is `vX.Y.Z`; use
     `X.Y.Z`.
2. **Get the zip** into a new, empty temporary directory:
   - If `xefm` is on PATH, prefer `xefm skill --zip <temp>/xefm-X.Y.Z-skill.zip`.
     It writes the copy that matches the installed XeFM, with no download.
   - Otherwise download
     `https://github.com/crftwr/xefm/releases/download/vX.Y.Z/xefm-X.Y.Z-skill.zip`.
     If that returns 404 (the XeFM is older than this skill), use the latest
     release's version from step 1 instead.
3. **Check** the zip before using it:
   - It contains a single top-level folder, `xefm/`.
   - It contains `xefm/SKILL.md`.
   - That file's frontmatter has `name: xefm`.

   If any of these fail, stop and tell the user.
4. **Choose the skills directory.** Use the user-level skills directory that
   you yourself load skills from. If you load from more than one, prefer
   `~/.agents/skills/`. Install at project level only when the user asked for
   that. If you can't tell where you load skills from, ask the user rather than
   guessing.

   If `<skills dir>/xefm/SKILL.md` already exists and its frontmatter has
   `xefm-version: "X.Y.Z"` for the version from step 1, the skill is already
   current. Remove the temporary directory, tell the user so and stop.
5. **Install:**
   - If `<skills dir>/xefm/` already exists, remove it.
   - Extract the zip so that the result is `<skills dir>/xefm/SKILL.md`. Make
     sure it is not nested one level deeper.
   - If `<skills dir>/xefm-extension-authoring/` exists and its `SKILL.md`
     has `name: xefm-extension-authoring`, remove that folder: it is the older
     skill this one replaces.
   - Remove the temporary directory.
6. **Report** to the user:
   - the path you installed to;
   - the version you installed;
   - whether you removed the old `xefm-extension-authoring` skill;
   - that they should start a new session for the skill to load.

   Do not start editing the configuration or writing an extension in the same
   step unless the user asked for that.

## See also

- [Configuration](CONFIGURATION_FEATURE.md) — every setting in `config.py`
- [Extension Packages](EXTENSIONS_FEATURE.md) — what an extension is, and how
  to install, check and manage one
- [Customization](CUSTOMIZATION_FEATURE.md) — what each kind of contribution
  does
