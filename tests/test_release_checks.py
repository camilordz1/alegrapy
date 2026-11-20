import importlib.util
import pathlib
import tarfile
import tempfile
import unittest
import zipfile

_SCRIPT_PATH = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "release_checks.py"
_SPEC = importlib.util.spec_from_file_location("release_checks", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
release_checks = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(release_checks)


def _write_tar_gz(path: pathlib.Path, entries: list[str]) -> None:
    with tarfile.open(path, "w:gz") as tf:
        for entry in entries:
            info = tarfile.TarInfo(name=entry)
            info.size = 0
            tf.addfile(info)


def _write_wheel(path: pathlib.Path, entries: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for entry in entries:
            zf.writestr(entry, "")


class TestReleaseChecks(unittest.TestCase):

    def test_check_version_matches_and_rejects_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            version_file = pathlib.Path(tmp) / "_version.py"
            version_file.write_text('__version__ = "0.1.0"\n', encoding="utf-8")

            self.assertEqual(release_checks.check_version("v0.1.0", version_file), "0.1.0")
            with self.assertRaises(ValueError):
                release_checks.check_version("v0.1.1", version_file)

    def test_extract_release_notes_variants_and_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            cl = pathlib.Path(tmp) / "CHANGELOG.md"

            cl.write_text("## [Unreleased]\n\n- Pending\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                release_checks.extract_release_notes("0.1.0", cl)

            cl.write_text(
                "## [0.1.0] - 2026-01-01\n\n## [0.0.4] - 2025-01-01\n- Old\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                release_checks.extract_release_notes("0.1.0", cl)

            cl.write_text(
                "## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n- Feature A\n\n## [0.0.4]\n- Old\n",
                encoding="utf-8",
            )
            self.assertEqual(
                release_checks.extract_release_notes("0.1.0", cl),
                "- Feature A",
            )

            cl.write_text("## [0.1.0]\n\n- Last section\n", encoding="utf-8")
            self.assertEqual(
                release_checks.extract_release_notes("0.1.0", cl),
                "- Last section",
            )

    def test_check_archives_allows_nested_main_and_rejects_forbidden_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            sdist = root / "alegrapy-0.1.0.tar.gz"
            wheel = root / "alegrapy-0.1.0-py3-none-any.whl"

            _write_tar_gz(sdist, [
                "alegrapy-0.1.0/pyproject.toml",
                "alegrapy-0.1.0/alegrapy/__init__.py",
                "alegrapy-0.1.0/alegrapy/main.py",
            ])
            _write_wheel(wheel, [
                "alegrapy/__init__.py",
                "alegrapy/main.py",
                "alegrapy-0.1.0.dist-info/METADATA",
            ])
            release_checks.check_archives([sdist, wheel])

            for bad_entry in (
                "config.ini",
                "alegra.log",
                ".env",
                "RELEASING.md",
                "main.py",
                "tests/test_a.py",
                "scripts/release_checks.py",
                "odd/briefs/x.md",
                "site/index.html",
                "env/bin/python",
            ):
                with self.subTest(bad_entry=bad_entry):
                    bad_sdist = root / "bad.tar.gz"
                    _write_tar_gz(bad_sdist, [
                        "alegrapy-0.1.0/pyproject.toml",
                        f"alegrapy-0.1.0/{bad_entry}",
                    ])
                    with self.assertRaises(ValueError):
                        release_checks.check_archives([bad_sdist])

                    bad_whl = root / "bad.whl"
                    _write_wheel(bad_whl, ["alegrapy/__init__.py", bad_entry])
                    with self.assertRaises(ValueError):
                        release_checks.check_archives([bad_whl])

    def test_secret_files_are_rejected_at_any_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)

            def wheel(name, extra):
                path = tmp / name
                with zipfile.ZipFile(path, "w") as zf:
                    zf.writestr("alegrapy/__init__.py", "")
                    zf.writestr("alegrapy-0.1.0.dist-info/METADATA", "Name: AlegraPy")
                    for entry in extra:
                        zf.writestr(entry, "secret")
                return path

            def sdist(extra):
                # Unique staging dir per call: names differing only by case would collide on
                # case-insensitive filesystems (macOS, Windows)
                source = pathlib.Path(tempfile.mkdtemp(dir=tmp))
                (source / "alegrapy").mkdir(parents=True)
                (source / "PKG-INFO").write_text("Name: AlegraPy")
                (source / "alegrapy" / "__init__.py").write_text("")
                for entry in extra:
                    target = source / entry
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("secret")
                path = source.with_suffix(".tar.gz")
                with tarfile.open(path, "w:gz") as tf:
                    tf.add(source, arcname="alegrapy-0.1.0")
                return path

            # Control: same shapes without secrets pass
            release_checks.check_archives([wheel("clean.whl", []), sdist([])])

            # .env.example / .env.sample are rejected on purpose: the guard fails closed, and
            # templates do not belong in a published package
            secrets = ("config.ini", ".env", "alegra.log", "Config.INI", ".ENV",
                       ".env.local", ".env.production", ".env.example", ".env.sample")
            for index, secret in enumerate(secrets):
                nested = f"alegrapy/sub/{secret}"
                archives = {
                    "wheel": wheel(f"bad-{index}.whl", [nested]),
                    "sdist": sdist([nested]),
                }
                for kind, archive in archives.items():
                    with self.subTest(secret=secret, kind=kind):
                        with self.assertRaises(ValueError) as ctx:
                            release_checks.check_archives([archive])
                        self.assertIn(secret, str(ctx.exception))

    def test_secret_names_do_not_flag_similar_legitimate_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "ok.whl"
            with zipfile.ZipFile(path, "w") as zf:
                for entry in ("alegrapy/env.py", "alegrapy/config_example.py",
                              "alegrapy/environment/__init__.py"):
                    zf.writestr(entry, "")
            release_checks.check_archives([path])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            cl = root / "CHANGELOG.md"
            out = root / "notes.md"
            cl.write_text("## [0.1.0] - 2026-01-01\n\n- Added X\n", encoding="utf-8")

            rc = release_checks.main([
                "release-notes", "--version", "0.1.0",
                "--changelog", str(cl), "--out", str(out),
            ])
            self.assertEqual(rc, 0)
            self.assertEqual(out.read_text(encoding="utf-8"), "- Added X\n")

            bad_rc = release_checks.main([
                "release-notes", "--version", "0.2.0",
                "--changelog", str(cl), "--out", str(out),
            ])
            self.assertEqual(bad_rc, 1)


    def test_cli_check_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            version_file = root / "_version.py"
            version_file.write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            self.assertEqual(release_checks.main(
                ["check-version", "--tag", "v0.1.0", "--version-file", str(version_file)]), 0)
            self.assertEqual(release_checks.main(
                ["check-version", "--tag", "v0.1.1", "--version-file", str(version_file)]), 1)

    def test_cli_check_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            clean = root / "clean.whl"
            with zipfile.ZipFile(clean, "w") as zf:
                zf.writestr("alegrapy/__init__.py", "")
            dirty = root / "dirty.whl"
            with zipfile.ZipFile(dirty, "w") as zf:
                zf.writestr("alegrapy/config.ini", "secret")
            self.assertEqual(release_checks.main(["check-archives", str(clean)]), 0)
            self.assertEqual(release_checks.main(["check-archives", str(clean), str(dirty)]), 1)

    def test_sdist_top_level_secret_outside_prefix_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "alegrapy-0.1.0").mkdir()
            (root / "alegrapy-0.1.0" / "PKG-INFO").write_text("Name: AlegraPy")
            (root / ".env").write_text("secret")
            sdist = root / "odd.tar.gz"
            with tarfile.open(sdist, "w:gz") as tf:
                tf.add(root / "alegrapy-0.1.0", arcname="alegrapy-0.1.0")
                tf.add(root / ".env", arcname=".env")
            with self.assertRaises(ValueError) as ctx:
                release_checks.check_archives([sdist])
            self.assertIn("'.env'", str(ctx.exception))

    def test_root_entries_match_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            for entry in ("Tests/test_x.py", "releasing.md", "ODD/notes.md"):
                with self.subTest(entry=entry):
                    path = pathlib.Path(tmp) / f"w-{entry.replace('/', '_')}.whl"
                    with zipfile.ZipFile(path, "w") as zf:
                        zf.writestr(entry, "")
                    with self.assertRaises(ValueError) as ctx:
                        release_checks.check_archives([path])
                    self.assertIn(entry, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
