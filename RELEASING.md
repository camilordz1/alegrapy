# Releasing AlegraPy

Releases are published to PyPI via GitHub Actions using **Trusted Publishing** (OIDC, no long-lived API tokens) when a `vX.Y.Z` tag is pushed.

## One-time setup

Before the first release, configure these settings once in PyPI, TestPyPI, and GitHub:

1. **PyPI Trusted Publisher** (on <https://pypi.org/manage/account/publishing/>):
   - PyPI Project Name: `AlegraPy`
   - Owner: `camilordz1`
   - Repository name: `alegrapy`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
2. **TestPyPI Trusted Publisher** (on <https://test.pypi.org/manage/account/publishing/>):
   - PyPI Project Name: `AlegraPy`
   - Owner: `camilordz1`
   - Repository name: `alegrapy`
   - Workflow name: `release.yml`
   - Environment name: `testpypi`
3. **GitHub Environments** (Repository **Settings -> Environments**):
   - Create `pypi` with **Required reviewers** set to the maintainer so every PyPI publish requires manual approval, and set **Deployment branches and tags -> Selected tags -> `v*`**.
   - Create `testpypi` (reviewer optional) for manual `workflow_dispatch` dry runs.
   - The workflow cannot check these environment protections itself: if `pypi` is missing,
     GitHub creates it without rules on the first run. Verify the settings before tagging.

## TestPyPI dry run

Run the **Release** workflow manually (`target: testpypi`). The upload does **not** skip existing
files, so a dry run either really uploads or fails: TestPyPI accepts each version only once. To
rehearse again with the same code, publish the next dry run from a throwaway branch with a
`.devN` suffix in `alegrapy/_version.py` (for example `0.1.0.dev1`); never tag that branch.

## Per-release checklist

1. Ensure `master` is clean and all CI checks are green.
2. Update the version in `alegrapy/_version.py` (`__version__ = "X.Y.Z"`).
3. Update `CHANGELOG.md`: move `## [Unreleased]` items into `## [X.Y.Z] - YYYY-MM-DD` (leaving an empty `## [Unreleased]` section above it).
4. Commit the release preparation on `master` (e.g., `chore(release): prepare X.Y.Z`).
5. Create and push an annotated tag:
   ```bash
   git tag -a vX.Y.Z -m "AlegraPy X.Y.Z"
   git push origin master vX.Y.Z
   ```
6. Open the triggered **Release** workflow run in GitHub Actions and approve the `pypi` environment deployment.
   - If a PyPI upload fails partway through, check which distribution files already exist on PyPI before re-running the job (`skip-existing` is intentionally disabled on both PyPI and TestPyPI).
   - The `github-release` job is safe to re-run: it edits the existing release and replaces its assets.
7. Wait for `publish-pypi` and `github-release` to finish, then verify installation in a fresh virtual environment:
   ```bash
   python -m venv /tmp/verify-alegrapy
   /tmp/verify-alegrapy/bin/pip install "AlegraPy==X.Y.Z"
   /tmp/verify-alegrapy/bin/python -c "import alegrapy; print(alegrapy.__version__)"
   ```
