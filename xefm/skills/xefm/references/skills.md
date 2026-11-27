# XeFM skills: skills only XeFM's agent sessions get

A skill in `~/.xefm/skills/<name>/` is handed to every AI agent session XeFM
starts (**Tools > AI Agent Here**, `ask_agent`) and to no agent run anywhere
else. Use it for what only makes sense beside the file manager: workflows on
`xefmctl`, the user's own conventions for sorting, renaming and unpacking
files, anything that assumes XeFM's panes, selection, archives or remote
places.

When the user asks for "an XeFM skill", a skill "for XeFM", or to "install it
in XeFM", it goes here - **not** in your own skills folder
(`~/.claude/skills`, `~/.agents/skills`, ...), where every session of yours
would load it.

## Write one

1. Pick the name: lowercase letters, digits and single hyphens, at most 64
   characters (`sort-photos`, `unpack-downloads`). `xefm` is taken by XeFM's
   own skill. If `~/.xefm/skills/<name>/` already exists, it is the user's:
   ask before changing it.
2. Write `~/.xefm/skills/<name>/SKILL.md` (on Windows `~` is the user's
   profile folder). It is a plain Agent Skills file: YAML frontmatter, then
   the instructions.

   ```markdown
   ---
   name: sort-photos
   description: Sort photos into year/month folders by their date taken and rename them YYYY-MM-DD_HHMMSS. Use when the user asks to sort, file or tidy photos.
   ---

   # Sorting photos

   1. `xefmctl state` - the photos are the selection, or the active pane's
      folder when nothing is selected.
   2. ...
   ```

   - `name` matches the folder's name.
   - `description` (at most 1024 characters) says what the skill does **and
     when to use it**: the agent decides from this line alone whether to load
     the rest.
   - Keep `SKILL.md` short; put long material in files beside it
     (`references/*.md`, scripts) and name them from `SKILL.md` by relative
     path.
   - Write the steps the way this skill's *Inside an XeFM session* asks:
     read what XeFM shows with `xefmctl`, show results in XeFM, and change
     files only with `xefmctl copy|move|trash --wait`.
3. Check it: `xefmctl skill check <name>` prints the name and `ok`, or what keeps
   it out of sessions (exit status 1). Fix and check again until it passes.
   `xefmctl skill list` shows every skill there and whether sessions get it.
   Both only read, so they are `xefmctl_read` commands where the session has
   XeFM's tools. Outside a session, `xefm skills check|list` does the same
   where `xefm` is on PATH (a desktop-app install does not put it there).

## When it takes effect

XeFM reads `~/.xefm/skills/` each time it starts a session, so a new or edited
skill reaches **the next session**; no reload or restart is needed. The
session that wrote it does not see it as a skill: if the user wants to use it
right away, read its `SKILL.md` yourself and follow it.

In Claude Code the skill is `xefm-user:<name>` (XeFM's own is `xefm:xefm`).

## Change or remove one

Edit the files in place; the next session gets the new version. To remove a
skill, move its folder to the trash through XeFM, so the user confirms it:
`xefmctl trash <the folder's full path> --wait` (`xefmctl skill list --json`
gives the folder).

A skill that fails the check is left out of sessions (with a warning in XeFM's
log) until it is fixed.
