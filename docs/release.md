# Releasing

## One-time setup, by the owner

These are settings on GitHub and PyPI, so no file in this repository can make them.

**PyPI** (https://pypi.org/manage/project/honestly/settings/publishing/), add a **Trusted Publisher** of type GitHub:

| Field | Value |
|---|---|
| Owner | `kennywu411-dev` |
| Repository name | `honestly` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

Then set the repository variable `PYPI_TRUSTED_PUBLISHER` to `true` (Settings > Secrets and variables > Actions > Variables). Until it is set, the `publish to PyPI` job is skipped and a release is uploaded by hand.

After the first release published this way works, on https://pypi.org/manage/account/token/ revoke the API token used for uploads, and remove any copy of it from your machine (`~/.pypirc`, environment variables, keychain).

**GitHub environment** (Settings > Environments > New environment, named `pypi`):

- Required reviewers: yourself, so that a pushed tag waits for your approval before it publishes.
- Deployment branches and tags: selected tags only, pattern `v*`.

**GitHub branch and tag rules** (Settings > Rules > Rulesets):

- A branch ruleset for `main`: require a pull request, require the status checks `lint and package check` and `analyze`, block force pushes, block deletion.
- A tag ruleset for `v*`: block updates and deletion, so a published tag cannot be moved. Restrict creation to yourself.

**GitHub Actions** (Settings > Actions > General):

- Under Actions permissions, turn on "Require actions to be pinned to a full-length commit SHA".
- Leave fork pull request approval at first-time contributors, as it is now.

**Security alerts** (Settings > Advanced Security):

- Turn on Dependabot alerts and Dependabot security updates. Dependabot version updates are already configured in `.github/dependabot.yml`.

**Signed commits and tags**: set up a signing key on your machine (`git config user.signingkey`, `git config gpg.format ssh` if you use an SSH key) and add it to your GitHub account as a signing key.

## Each release

1. Update `version` in `pyproject.toml` and `.claude-plugin/plugin.json`, and `CHANGELOG.md`. Merge to `main`.
2. Tag it, signed: `git tag -s v0.8.0 -m "honestly 0.8.0"`, then `git push origin v0.8.0`.
3. The `release` workflow tests, builds and waits for your approval on the `pypi` environment. Approve it. If `PYPI_TRUSTED_PUBLISHER` is not set yet, the publish job is skipped: build from the tag and upload with `twine upload dist/*`.
4. Check https://pypi.org/project/honestly/ shows the version and its provenance, then create the GitHub release: `gh release create v0.8.0 --verify-tag --notes-from-tag`.

## Checking a build

The wheel is reproducible: built from the same commit with `SOURCE_DATE_EPOCH` set to that commit's time and the tools in `.github/release/requirements.txt`, it is byte-for-byte the same. The sdist is not. To check a published wheel:

```bash
git checkout v0.8.0
python -m pip install --require-hashes -r .github/release/requirements.txt
SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)" python -m build --no-isolation --wheel
sha256sum dist/*.whl    # compare with the digest on PyPI
```
