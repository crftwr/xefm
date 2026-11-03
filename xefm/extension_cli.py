"""``xefm ext …`` — manage extension packages from a shell (#583).

Runs without opening a window, so it works the same from a pipx install, the
macOS bundle and the Windows package, which share ``~/.xefm/`` and nothing else.
Every subcommand is a thin layer over :mod:`xefm.extensions`; ``check`` is the
static validator an author (or an assistant writing a package) runs, and its
exit status says whether the package would install.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from xefm import extensions as ext


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xefm ext", description="Manage XeFM extension packages.")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="validate a package without running it")
    check.add_argument("source", help="what install takes: a directory, a .zip, "
                       "an https:// zip URL, or github:owner/repo[/path][@ref]")
    check.add_argument("--stable-only", action="store_true",
                       help="treat every use of a Preview API as an error")

    install = sub.add_parser("install", help="check a package and install it")
    install.add_argument("source", help="a directory, a .zip, an https:// zip "
                         "URL, or github:owner/repo[/path][@ref]")
    install.add_argument("-y", "--yes", action="store_true",
                         help="do not ask before installing")

    uninstall = sub.add_parser("uninstall", help="remove an installed package")
    uninstall.add_argument("id")
    data = uninstall.add_mutually_exclusive_group()
    data.add_argument("--delete-data", action="store_true",
                      help="also delete ~/.xefm/extension-data/<id>/")
    data.add_argument("--keep-data", action="store_true",
                      help="keep ~/.xefm/extension-data/<id>/ (no question)")

    sub.add_parser("list", help="list packages and whether they load")
    for name, text in (("enable", "load a package again"),
                       ("disable", "keep a package installed but unloaded")):
        p = sub.add_parser(name, help=text)
        p.add_argument("id")
    new = sub.add_parser("new", help="create a package that passes the check, to start from")
    new.add_argument("id")
    new.add_argument("--dir", default=".", help="where to create it (default: here)")

    # Kept as an alias of the top-level `xefm skill` (#639): the skill grew
    # beyond extensions, but instructions already out there name this one.
    _skill_arguments(sub.add_parser(
        "skill", help="the AI-agent skill for XeFM - same as `xefm skill`"))

    outdated = sub.add_parser(
        "outdated", help="list installed packages with a newer version (asks GitHub)")
    outdated.add_argument("ids", nargs="*", metavar="id",
                          help="only these packages (default: all)")
    upgrade = sub.add_parser(
        "upgrade", help="install the newer version of packages (asks GitHub)")
    upgrade.add_argument("ids", nargs="*", metavar="id",
                         help="only these packages (default: every outdated one)")
    upgrade.add_argument("-y", "--yes", action="store_true",
                         help="do not ask before upgrading")

    sub.add_parser("sync", help="reinstall listed packages whose files are missing")
    settings = sub.add_parser("settings", help="print a package's settings class "
                              "for config.py, with every default")
    settings.add_argument("id")
    return parser


def _skill_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--install", metavar="DIR",
                       help="copy it into an agent's skills directory, e.g. "
                       "~/.agents/skills")
    where.add_argument("--zip", metavar="FILE", help="write it as a zip")
    return parser


def skill_main(argv: list[str]) -> int:
    """``xefm skill [--install DIR | --zip FILE]`` — the AI-agent skill for
    editing XeFM's config and writing extensions (any Agent Skills client)."""
    parser = _skill_arguments(argparse.ArgumentParser(
        prog="xefm skill",
        description="The AI-agent skill for XeFM: editing ~/.xefm/config.py "
                    "and writing extension packages (any Agent Skills client)."))
    return _skill(parser.parse_args(argv))


def _skill(args: argparse.Namespace) -> int:
    source = ext.SKILL_DIR
    if args.zip:
        print(f"wrote {ext.write_skill_zip(Path(args.zip).expanduser())}")
        return 0
    if args.install is None:
        print(source / "SKILL.md")
        print("Copy it into your agent's skills directory with "
              "`xefm skill --install DIR` (~/.agents/skills is read by "
              "most agents), or see doc/AGENT_SKILL_FEATURE.md")
        return 0
    import shutil
    skills = Path(args.install).expanduser()
    target = ext.install_skill(skills)
    print(f"installed the {source.name} skill for XeFM {ext.skill_version()} "
          f"in {target}")
    # Only a folder that really is the old skill: this is the user's
    # directory, and a same-named folder of someone else's stays.
    legacy = skills / ext.LEGACY_SKILL_NAME
    if _skill_name(legacy / "SKILL.md") == ext.LEGACY_SKILL_NAME:
        shutil.rmtree(legacy)
        print(f"removed the old {ext.LEGACY_SKILL_NAME} skill it replaces")
    return 0


def _skill_name(skill_md: Path) -> str | None:
    """The ``name:`` in a SKILL.md's frontmatter, or None."""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    for line in parts[1].splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "name":
            return value.strip()
    return None


def _ask(prompt: str) -> bool:
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _sync_python_packages(layout: ext.Layout, *, ask: bool) -> int:
    """Install what an extension just installed asks for from PyPI — the same
    sync as `xefm deps sync`, offered rather than assumed, since it reaches
    the network and runs pip."""
    from xefm import python_packages as pp
    if ask and not _ask("It needs Python packages from PyPI. Sync them now?"):
        print("Not synced - the extension loads after `xefm deps sync`.")
        return 0
    try:
        result = pp.sync(pp.Layout(layout.home), log=print)
    except pp.SyncError as exc:
        print(f"Python packages sync failed: {exc}", file=sys.stderr)
        return 1
    print("Python packages synced"
          + (" - they take effect when XeFM next starts" if result.pending_restart else ""))
    return 0


def _note_python_packages(layout: ext.Layout) -> None:
    """One line when a change to the installed set leaves the Python
    packages out of date — the sync that removes or adds them is the user's."""
    from xefm import python_packages as pp
    if pp.check(pp.Layout(layout.home)).state == pp.NEEDS_SYNC:
        print("Python packages are out of date - run `xefm deps sync`")


def _print_problems(problems) -> None:
    for problem in problems:
        print(problem)


def _print_summary(manifest: ext.Manifest) -> None:
    """What a package adds — the same block for ``check`` and ``install``."""
    print(f"{manifest.name} {manifest.version} ({manifest.id}) adds:")
    for line in ext.summarize(manifest) or ["(nothing)"]:
        print(f"  {line}")


def _check(args: argparse.Namespace, layout: ext.Layout, root: Path) -> int:
    manifest, problems = ext.check_for_install(root, layout)
    if manifest is not None:
        _print_summary(manifest)
    previews = ext.preview_uses(manifest) if manifest is not None else []
    if args.stable_only:
        previews = ext.stable_only(previews)
    _print_problems(problems + previews)
    apis = {p.message.split(" - ")[0] if " - " in p.message else p.where
            for p in previews}
    if apis:
        print(f"{len(apis)} Preview API(s) in use; everything else this "
              "package uses is stable.")
    bad = ext.errors(problems + previews)
    if not bad:
        name = f"{manifest.id} {manifest.version}" if manifest else args.source
        print(f"ok: {name}" + (f" ({len(problems)} warning(s))" if problems else ""))
        if manifest is not None and manifest.data.get("settings") is not None:
            print(f"settings: class {ext.config_class_name(manifest)} in config.py")
    return 1 if bad else 0


def main(argv: list[str] | None = None, layout: ext.Layout | None = None) -> int:
    args = _parser().parse_args(argv)
    layout = layout or ext.Layout()

    if args.command == "check":
        # The same sources as install, fetched the same way, so checking a
        # download or a link needs no unzip or clone first (#743).
        with tempfile.TemporaryDirectory(prefix="xefm-ext-") as tmp:
            try:
                root = ext.fetch(args.source, Path(tmp))
            except ext.InstallError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            return _check(args, layout, root)

    if args.command == "install":
        try:
            with tempfile.TemporaryDirectory(prefix="xefm-ext-") as tmp:
                fetched = None
                if not args.yes:
                    # Show what it adds before anything is copied: extensions
                    # run in-process, with no sandbox. The copy shown is the
                    # one installed — fetched once.
                    fetched = ext.fetch(args.source, Path(tmp))
                    _print_summary(ext.read_manifest(fetched))
                    print("Extensions run inside XeFM with your permissions.")
                    if not _ask("Install it?"):
                        print("Not installed.")
                        return 1
                manifest = ext.install(args.source, layout, fetched=fetched)
        except ext.InstallError as exc:
            _print_problems(exc.problems)
            print(f"error: {exc}", file=sys.stderr)
            return 1
        except ext.ManifestError as exc:
            print(exc.problem, file=sys.stderr)
            return 1
        print(f"installed {manifest.id} {manifest.version} - reload the config "
              "(Tools > Reload Configuration) or restart XeFM to load it")
        if manifest.requires.get("python_packages"):
            return _sync_python_packages(layout, ask=not args.yes)
        return 0

    if args.command == "uninstall":
        delete = args.delete_data
        data_dir = layout.data_dir(args.id)
        if not delete and not args.keep_data and data_dir.exists():
            delete = _ask(f"Also delete its data in {data_dir}?")
        try:
            ext.uninstall(args.id, layout, delete_data=delete)
        except ext.InstallError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"uninstalled {args.id}")
        _note_python_packages(layout)
        return 0

    if args.command == "list":
        installed = ext.read_installed(layout)
        manifests = ext.discover(layout)
        if not manifests and not installed:
            print(f"no extension packages in {layout.packages}")
            return 0
        seen = set()
        for manifest in manifests:
            seen.add(manifest.id)
            entry = installed.get(manifest.id)
            state = "local" if entry is None else (
                "enabled" if entry.enabled else "disabled")
            bad = ext.errors(ext.check_manifest(manifest, others=manifests,
                                                machine=False))
            note = f" - will not load: {bad[0].message}" if bad else ""
            source = f"  from {entry.source}" if entry and entry.source else ""
            print(f"{manifest.id} {manifest.version} [{state}]{source}{note}")
            if manifest.data.get("settings") is not None:
                print(f"    settings: class {ext.config_class_name(manifest)} "
                      "in config.py")
        for ext_id, entry in sorted(installed.items()):
            if ext_id not in seen:
                print(f"{ext_id} {entry.version} [missing - run `xefm ext sync`]")
        return 0

    if args.command in ("enable", "disable"):
        try:
            ext.set_enabled(args.id, args.command == "enable", layout)
        except ext.InstallError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"{args.id} {args.command}d - takes effect on the next config reload")
        _note_python_packages(layout)
        return 0

    if args.command == "new":
        try:
            root = ext.scaffold(args.id, Path(args.dir))
        except ext.InstallError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"created {root} - edit it, then: xefm ext check {root}")
        return 0

    if args.command == "skill":
        return _skill(args)

    if args.command == "settings":
        manifest = next((m for m in ext.discover(layout) if m.id == args.id), None)
        if manifest is None:
            print(f"error: {args.id} is not installed", file=sys.stderr)
            return 1
        try:
            print(ext.settings_template(manifest))
        except Exception as exc:
            print(f"error: could not read the settings of {args.id}: {exc}",
                  file=sys.stderr)
            return 1
        return 0

    if args.command in ("outdated", "upgrade"):
        try:
            checks = ext.check_updates(layout, ids=args.ids)
        except ext.InstallError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if not checks:
            print("no installed extension packages to check")
            return 0
        newer = [c for c in checks if c.outdated]
        failed = [c for c in checks if c.failed]
        for check in checks:
            if check.failed:
                print(f"{check.id} {check.version}: could not check - {check.problem}",
                      file=sys.stderr)
            elif check.problem:
                print(f"{check.id} {check.version}: not checked - {check.problem}")
        if args.command == "outdated":
            for check in newer:
                print(f"{check.id} {check.version} -> {check.latest}  ({check.source})")
            current = sum(1 for c in checks if c.updates and not c.problem and not c.outdated)
            if current:
                print(f"{current} package(s) up to date")
            # Like `deps status`: non-zero when something needs doing.
            return 1 if newer or failed else 0
        if not newer:
            print("nothing to upgrade")
            return 1 if failed else 0
        for check in newer:
            print(f"{check.id} {check.version} -> {check.latest}")
        print("Extensions run inside XeFM with your permissions.")
        if not args.yes and not _ask(f"Upgrade {len(newer)} package(s)?"):
            print("Not upgraded.")
            return 1
        failed = False
        needs_packages = False
        for check in newer:
            try:
                manifest = ext.upgrade(check, layout)
            except (ext.InstallError, ext.ManifestError) as exc:
                failed = True
                print(f"error: {check.id}: {exc}", file=sys.stderr)
                continue
            print(f"upgraded {manifest.id} to {manifest.version}")
            needs_packages |= bool(manifest.requires.get("python_packages"))
        print("Reload the config (Tools > Reload Configuration) or restart XeFM "
              "to load the new versions")
        if needs_packages:
            failed |= _sync_python_packages(layout, ask=not args.yes) != 0
        return 1 if failed else 0

    if args.command == "sync":
        lines = ext.sync(layout)
        for line in lines or ["nothing to reinstall"]:
            print(line)
        return 1 if any("could not" in line for line in lines) else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
