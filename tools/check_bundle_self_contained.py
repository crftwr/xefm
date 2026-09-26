#!/usr/bin/env python3
"""Fail when anything in a macOS .app bundle loads code from outside it.

A distributed XeFM.app carries its own CPython, so the machine that opens it is
not required to have Python installed at all. That only holds while every
Mach-O in the bundle resolves its dependencies inside the bundle: one load
command still naming /Library/Frameworks/Python.framework or /opt/homebrew is
enough to turn "works here" into a dyld failure on a customer's Mac, and the
build machine is the one place that failure cannot be observed.

What counts as a dependency is narrower than `otool -L` suggests:

* Only LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB and LC_REEXPORT_DYLIB are ones. A
  library's own LC_ID_DYLIB is printed first by `otool -L` but is not a
  dependency - dyld resolves by what the *dependent* asks for, so a vendored
  copy keeping the install name it was built with is cosmetic.
* `otool -L` prints a `<path> (architecture X):` header per slice of a
  universal binary, and that path is the file's own, under the build tree. A
  filter that reads every line reports those headers as external dependencies.

Both are why this reads `otool -l` rather than grepping `otool -L`.

@rpath dependencies are resolved against the binary's own LC_RPATH list, so a
vestigial rpath left in a wheel (pointing at a Homebrew cellar, or at the CI
machine that built it) is not a finding by itself - only a dependency that
lands outside the bundle, or nowhere, is.

Usage:
    python3 tools/check_bundle_self_contained.py path/to/XeFM.app
"""

import os
import subprocess
import sys

# Resolved here, these are the OS's own: present on every supported macOS and
# not something a bundle can or should carry.
SYSTEM_PREFIXES = ("/usr/lib/", "/System/")

DEPENDENCY_COMMANDS = {"LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB"}

MACHO_MAGICS = (
    b"\xcf\xfa\xed\xfe",  # 64-bit little-endian
    b"\xce\xfa\xed\xfe",  # 32-bit little-endian
    b"\xca\xfe\xba\xbe",  # universal
    b"\xbe\xba\xfe\xca",  # universal, byte-swapped
)


def iter_macho(root):
    """Every Mach-O file under root, symlinks skipped (their target is walked)."""
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as handle:
                    if handle.read(4) in MACHO_MAGICS:
                        yield path
            except OSError:
                continue


def is_executable_macho(path):
    """True for MH_EXECUTE, which is what @executable_path is measured from."""
    described = subprocess.run(["file", "-b", path], capture_output=True, text=True).stdout
    return "executable" in described


def load_commands(path):
    """(dependencies, rpaths) for one Mach-O, across all of its slices."""
    listing = subprocess.run(["otool", "-l", path], capture_output=True, text=True).stdout
    dependencies, rpaths, command = set(), [], None
    for line in listing.splitlines():
        line = line.strip()
        if line.startswith("cmd "):
            command = line.split()[1]
        elif line.startswith("name ") and command in DEPENDENCY_COMMANDS:
            dependencies.add(line.split()[1])
        elif line.startswith("path ") and command == "LC_RPATH":
            rpaths.append(line.split()[1])
    return dependencies, rpaths


def candidates_for(dependency, path, rpaths, executable_dirs):
    """Where dyld would look for this dependency, in the order it would look."""
    loader_dir = os.path.dirname(path)

    def expand(prefix, rest):
        if prefix == "@loader_path":
            return [os.path.join(loader_dir, rest)]
        if prefix == "@executable_path":
            return [os.path.join(d, rest) for d in executable_dirs]
        return []

    for prefix in ("@loader_path/", "@executable_path/"):
        if dependency.startswith(prefix):
            return expand(prefix.rstrip("/"), dependency[len(prefix):])

    if dependency.startswith("@rpath/"):
        rest = dependency[len("@rpath/"):]
        found = []
        for rpath in rpaths:
            head, _, tail = rpath.partition("/")
            bases = expand(head, tail) if head.startswith("@") else [rpath]
            found += [os.path.join(base, rest) for base in bases]
        return found

    return [dependency]


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2

    bundle = os.path.realpath(argv[1])
    if not os.path.isdir(bundle):
        print(f"No such bundle: {argv[1]}", file=sys.stderr)
        return 2

    binaries = sorted(iter_macho(bundle))
    # The app's own executable and the embedded interpreter are both processes
    # this bundle starts (the latter runs external programs - see
    # xefm/external_programs.py), so @executable_path can mean either.
    executable_dirs = sorted({os.path.dirname(p) for p in binaries if is_executable_macho(p)})

    external, unresolved, inside = [], [], 0
    for path in binaries:
        dependencies, rpaths = load_commands(path)
        for dependency in sorted(dependencies):
            if dependency.startswith(SYSTEM_PREFIXES):
                continue
            target = next(
                (os.path.realpath(c)
                 for c in candidates_for(dependency, path, rpaths, executable_dirs)
                 if os.path.exists(c)),
                None,
            )
            relative = os.path.relpath(path, bundle)
            if target is None:
                unresolved.append((relative, dependency))
            elif not target.startswith(bundle + os.sep):
                external.append((relative, dependency, target))
            else:
                inside += 1

    print(f"Checked {len(binaries)} Mach-O files; "
          f"{inside} dependencies resolve inside the bundle")

    for relative, dependency, target in external:
        print(f"  OUTSIDE  {relative}\n             {dependency} -> {target}")
    for relative, dependency in unresolved:
        print(f"  MISSING  {relative}\n             {dependency}")

    if external or unresolved:
        print(f"\n{len(external)} dependency(ies) resolve outside the bundle, "
              f"{len(unresolved)} resolve nowhere.")
        print("The app would load code from the build machine, or fail to launch,")
        print("on a Mac that does not happen to have these files.")
        return 1

    print("Every dependency is either inside the bundle or part of macOS.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
