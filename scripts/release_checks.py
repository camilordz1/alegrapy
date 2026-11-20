"""Pre-publish checks for AlegraPy release artifacts."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tarfile
import zipfile
from typing import Sequence

DEFAULT_VERSION_FILE = pathlib.Path("alegrapy/_version.py")
DEFAULT_CHANGELOG = pathlib.Path("CHANGELOG.md")

# Files that may hold secrets or private data: rejected at ANY depth, because a copy inside
# the package directory would ship just the same:
# - config.ini: local credential file used in development
# - alegra.log: legacy log file written by old versions (may contain request data)
# - .env: local environment variables / secrets
# Matching always lowercases each path component (so Config.ini and .ENV are caught), and
# any name starting with ".env." (.env.local, .env.production, also .env.example) is treated
# as a secret too: the guard fails closed, and env templates do not belong in the package.
FORBIDDEN_ANY_DEPTH_FILES = frozenset({
    "config.ini",
    "alegra.log",
    ".env",
})


def _is_secret_name(name: str) -> bool:
    lowered = name.lower()
    return lowered in FORBIDDEN_ANY_DEPTH_FILES or lowered.startswith(".env.")

# Root-level files that must not ship (nested files with these names are legitimate):
# - RELEASING.md: maintainer release checklist (repo-only)
# - main.py: root-level example script (nested alegrapy/main.py is allowed)
FORBIDDEN_ROOT_FILES = frozenset({
    "RELEASING.md",
    "main.py",
})

# Root-level directories that must never be shipped in an sdist or wheel:
# - env: local virtual environment
# - odd: internal planning/briefs directory
# - site: built MkDocs documentation
# - tests: test suite (excluded from sdist)
# - scripts: repository helper scripts (including this file)
FORBIDDEN_ROOT_DIRS = frozenset({
    "env",
    "odd",
    "site",
    "tests",
    "scripts",
})


def read_version(version_file: pathlib.Path = DEFAULT_VERSION_FILE) -> str:
    """Read ``__version__`` from ``alegrapy/_version.py`` without importing the package."""
    namespace: dict[str, object] = {}
    exec(version_file.read_text(encoding="utf-8"), namespace)
    version = namespace.get("__version__")
    if not isinstance(version, str) or not version:
        raise ValueError(f"Missing __version__ string in {version_file}")
    return version


def check_version(tag: str, version_file: pathlib.Path = DEFAULT_VERSION_FILE) -> str:
    """Verify that ``tag`` (with leading ``v`` stripped) matches ``__version__``."""
    version = read_version(version_file)
    tag_version = tag[1:] if tag.startswith("v") else tag
    if tag_version != version:
        raise ValueError(f"Tag {tag!r} does not match __version__ {version!r}")
    return version


def extract_release_notes(
    version: str,
    changelog_path: pathlib.Path = DEFAULT_CHANGELOG,
) -> str:
    """Extract the non-empty ``## [version]`` section from ``CHANGELOG.md``."""
    changelog = changelog_path.read_text(encoding="utf-8")
    pattern = rf"^## \[{re.escape(version)}\](?:[ \t]+-[^\n]*)?[ \t]*\n(.*?)(?=^## \[|\Z)"
    match = re.search(pattern, changelog, flags=re.MULTILINE | re.DOTALL)
    notes = match.group(1).strip() if match else ""
    if not notes:
        raise ValueError(
            f"{changelog_path} has no non-empty '## [{version}]' section"
        )
    return notes


def _check_members(
    archive: pathlib.Path,
    members: Sequence[str],
    *,
    strip_root: bool,
) -> None:
    forbidden: list[str] = []
    for raw in members:
        parts = pathlib.PurePosixPath(raw).parts
        if strip_root:
            if len(parts) <= 1:
                continue
            parts = parts[1:]
        if not parts:
            continue
        root_entry = parts[0]
        if (root_entry in FORBIDDEN_ROOT_FILES or root_entry in FORBIDDEN_ROOT_DIRS
                or any(_is_secret_name(part) for part in parts)):
            forbidden.append(raw)
    if forbidden:
        raise ValueError(f"Forbidden entries in {archive}: {forbidden}")


def check_archives(paths: Sequence[pathlib.Path]) -> None:
    """Fail if any sdist or wheel contains secret files (any depth) or forbidden root entries."""
    if not paths:
        raise ValueError("No archive paths provided")
    for path in paths:
        if path.name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as tf:
                names = [member.name for member in tf.getmembers()]
            _check_members(path, names, strip_root=True)
        elif path.suffix == ".whl":
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
            _check_members(path, names, strip_root=False)
        else:
            raise ValueError(f"Unsupported archive format: {path}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_version = subparsers.add_parser("check-version", help="Verify tag matches __version__")
    p_version.add_argument("--tag", required=True, help="Git tag (e.g. v0.1.0)")
    p_version.add_argument("--version-file", type=pathlib.Path, default=DEFAULT_VERSION_FILE)

    p_notes = subparsers.add_parser("release-notes", help="Extract CHANGELOG section")
    p_notes.add_argument("--version", required=True, help="Version without leading v")
    p_notes.add_argument("--out", type=pathlib.Path, required=True, help="Output markdown path")
    p_notes.add_argument("--changelog", type=pathlib.Path, default=DEFAULT_CHANGELOG)

    p_archives = subparsers.add_parser("check-archives", help="Guard sdist and wheel contents")
    p_archives.add_argument("archives", nargs="+", type=pathlib.Path)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check-version":
            version = check_version(args.tag, args.version_file)
            print(f"Verified version {version} matches tag {args.tag}")
        elif args.command == "release-notes":
            notes = extract_release_notes(args.version, args.changelog)
            args.out.write_text(notes + "\n", encoding="utf-8")
            print(f"Wrote {len(notes)} chars of release notes to {args.out}")
        elif args.command == "check-archives":
            check_archives(args.archives)
            print(f"Verified {len(args.archives)} archive(s) clean")
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
