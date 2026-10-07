# Security (DevSecOps) for TaskBoard Lite

**Student:** Vivek Singh Solanki | **Roll number:** 24bcs10338

Every push to `main` runs five independent checks before an image may be
published or deployed. They are wired in `.github/workflows/final-pipeline.yml`
and configured from this directory.

| Stage | Category | Tool | Config | What it catches |
|---|---|---|---|---|
| `test` | quality | pytest + pytest-cov | `application/pytest.ini` | broken behaviour before anything else runs |
| `sast` | SAST (static analysis of our code) | bandit (CodeQL is the GitHub-native alternative, see below) | `bandit.yaml` | dangerous Python patterns: `eval`, shell=True, hard-coded passwords, weak hashes, binding to all interfaces, SQL built with string formatting |
| `sca` | SCA (software composition analysis) | pip-audit | `application/requirements.txt` | published CVEs in the pinned dependencies (Flask, Werkzeug, gunicorn, ...) |
| `secret-scan` | secret scanning | gitleaks | `.gitleaks.toml` | credentials committed to git history: AWS keys, GitHub tokens, private keys, high-entropy `password = ...` strings |
| `image-scan` | container image scanning | trivy | `trivy.yaml`, `.trivyignore` | CVEs in the Debian base image packages and the Python packages inside the final image |
| `security-gate` | gate | shell step | workflow | blocks `push-image` and `deploy-kubernetes` unless every stage above succeeded |

## Running each tool locally

All commands run from `final-devops-project/` (Apple Silicon friendly; every
tool has an arm64 build).

```bash
# one-off tool install
pip install -r application/requirements-dev.txt     # pytest, bandit, pip-audit
brew install gitleaks trivy

# 1. tests
( cd application && pytest -v --cov=app )

# 2. SAST
bandit -r application -c security/bandit.yaml                    # human readable
bandit -r application -c security/bandit.yaml -f json -o bandit-report.json --exit-zero
bandit -r application -c security/bandit.yaml --severity-level high   # exit 1 only on HIGH

# 3. SCA
pip-audit -r application/requirements.txt --strict --desc on

# 4. secret scanning (run from the repository root so git history is included)
( cd ../.. && gitleaks git --config session-21-final-devops-project/final-devops-project/security/.gitleaks.toml --verbose )
gitleaks dir --config security/.gitleaks.toml .                  # working tree only

# 5. image scanning
docker build -f docker/Dockerfile -t taskboard-lite:local .
trivy image --config security/trivy.yaml --ignorefile security/.trivyignore taskboard-lite:local
```

## What each configuration file does

### `bandit.yaml`
- `exclude_dirs: [tests, ...]` - test code uses `assert` and throw-away values on purpose.
- `skips: [B101]` - B101 is "use of assert"; it would only produce noise.
- Everything else stays enabled. The one accepted finding in the code base is
  documented inline: `app.run(host="0.0.0.0")` carries `# nosec B104` because a
  container must bind all interfaces. The pipeline uploads the full JSON report
  and fails only on **HIGH** severity findings, so MEDIUM/LOW results are visible
  but not blocking.

### `.gitleaks.toml`
- `[extend] useDefault = true` keeps the complete default rule set.
- One narrow allowlist covers the **demo** secret value (`demo-only-change-me`)
  in `kubernetes/secret.yaml`, the Helm values files and the compose file. The
  value is intentionally committed so that secret injection can be demonstrated
  (`/api/config` reports `db_password_set: true`). Only that literal string is
  ignored, and only in those files; a real token pasted into the same file is
  still reported. Real deployments source the password from a vault / sealed
  secret and never commit it.

### `trivy.yaml` and `.trivyignore`
- `severity: [HIGH, CRITICAL]` and `exit-code: 1` - lower severities are listed
  but do not fail the build.
- `ignore-unfixed: true` - CVEs without an upstream fix are not actionable;
  they are tracked, not blocked on.
- `.trivyignore` is empty. If a specific CVE must be accepted temporarily, add
  it there with an expiry and a justification in the pull request.

## How the security gate blocks the pipeline

```
test -> sast -> sca -> secret-scan -> docker-build -> image-scan
                                                          |
                                               security-gate (if: always())
                                                          |
                               push-image (push to main) -> deploy-kubernetes
```

- The scan jobs are chained with `needs`, so a failure stops the chain early.
- `security-gate` runs with `if: always()` so it executes even when an earlier
  job failed. It reads `needs.<job>.result` for every stage, prints a summary
  table to the job summary page and exits 1 if any result is not `success`.
- `push-image` and `deploy-kubernetes` depend on `security-gate`. When the gate
  fails they are skipped: no image reaches GHCR and nothing is deployed.
- Reports (`bandit-report.json`, `pip-audit-report.json`, `trivy-results.sarif`,
  gitleaks results) are uploaded as artifacts, and the SARIF file is also sent
  to the repository **Security -> Code scanning** tab.

## About CodeQL

CodeQL is GitHub's own SAST engine. It can be enabled with one click under
**Settings -> Code security -> Code scanning -> Default setup** and then runs
on every pull request next to this pipeline. bandit is used in the workflow
because it is fast, Python-specific and runs identically on a laptop.

## Handling a red stage

| Red stage | Typical cause | Fix |
|---|---|---|
| `sast` | new HIGH bandit finding | fix the code; if it is a false positive add `# nosec <id>` with a comment explaining why |
| `sca` | CVE in a pinned package | bump the pin in `requirements.txt`, re-run tests |
| `secret-scan` | real credential committed | rotate the credential first, then remove it from history (`git filter-repo`), never just allowlist it |
| `image-scan` | CVE in the base image | rebuild (pulls the latest `python:3.12-slim`), or bump the base image tag |
