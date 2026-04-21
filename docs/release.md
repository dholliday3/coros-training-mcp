# Releasing `coros-training-mcp`

Releases are published to PyPI via GitHub Actions using **OIDC trusted
publishing**. No API tokens exist on any machine. The release workflow lives at
[.github/workflows/release.yml](../.github/workflows/release.yml).

## One-time setup (per maintainer)

Done once when the package is first registered with PyPI:

1. **Register the pending publisher on PyPI**
   Go to <https://pypi.org/manage/account/publishing/> → "Add a new pending publisher":
   - PyPI Project Name: `coros-training-mcp`
   - Owner: `dholliday3`
   - Repository name: `coros-training-mcp`
   - Workflow name: `release.yml`
   - Environment name: `pypi`

2. **Create the `pypi` GitHub environment**
   Repo → Settings → Environments → "New environment" → `pypi`. Recommended
   protection rules:
   - Required reviewers: yourself (one-click approval gate before publish).
   - Deployment branches and tags: "Selected branches and tags" → add a
     **Tag** rule (not Branch) with pattern `v*`. If this is set to a branch
     rule, tag pushes will fail at the deployment gate because `refs/tags/...`
     doesn't match a branch policy.

After the first successful publish, the "pending" publisher becomes
project-scoped; no further action needed.

## Cutting a release

```bash
# 1. Bump the version in pyproject.toml
#    (the release workflow refuses to run if the tag and pyproject don't match)

# 2. Commit + push
git commit -am "chore: bump to 0.3.0"
git push

# 3. Tag + push the tag
git tag v0.3.0
git push origin v0.3.0
```

The workflow runs automatically:
- Checks out the tagged commit.
- Verifies `pyproject.toml` version matches the tag AND the tag is strict
  `vX.Y.Z` semver (refuses to publish otherwise).
- Runs the full non-live test suite.
- Builds sdist + wheel with `uv build`.
- Smoke-tests the built wheel in a throwaway venv.
- Publishes to PyPI via OIDC.

## If something goes wrong

- **Wrong tag version** — the workflow fails with a clear error at the
  "Verify tag matches pyproject.toml version" step. Delete the tag
  (`git push --delete origin vX.Y.Z`), fix `pyproject.toml`, re-tag.
- **Yanked a bad release** — yank it on PyPI via the project settings; do not
  re-use the version number.
- **Lost access to the repo** — as long as PyPI still has the trusted publisher
  pointing at this workflow file, anyone with push access to `main` who can
  create tags can publish. Remove trusted publishers on PyPI to revoke.

## Why OIDC, not API tokens

- Nothing to leak. No `PYPI_TOKEN` in GitHub secrets, in `~/.pypirc`, in
  Keychain, or anywhere else.
- Short-lived: tokens minted by PyPI last ~15 minutes and are scoped to this
  specific workflow run.
- Revocation is "delete the trusted publisher registration"; no hunt-and-purge
  for leaked credentials.
- Audit trail: every release is a tagged commit + a workflow run, not
  "I ran `uv publish` on Tuesday with whatever was in my working tree."
