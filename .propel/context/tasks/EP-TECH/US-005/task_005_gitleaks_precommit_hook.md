---
id: TASK-005
title: "Add `gitleaks` Pre-Commit Hook to Block Secret Commits"
user_story: US-005
epic: EP-TECH
sprint: 1
layer: DevSecOps
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-14
assignee: Security Engineer
upstream: []
---

# TASK-005: Add `gitleaks` Pre-Commit Hook to Block Secret Commits

> **Story:** US-005 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** DevSecOps | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

US-005 Scenario 4 requires that a `gitleaks` pre-commit hook blocks commits containing secrets. A `.pre-commit-config.yaml` file does not currently exist in the repository. This task creates it with `gitleaks` as the first hook, plus a `detect-private-key` hook from the standard `pre-commit-hooks` library as a lightweight backup check.

All developers and CI pipelines must install `pre-commit` (`pip install pre-commit`) and run `pre-commit install` after cloning the repository. This onboarding step is documented in TASK-007 (BOOTSTRAP.md update).

---

## Acceptance Criteria Addressed

| US-005 AC | Requirement |
|---|---|
| **Scenario 4** | Commit blocked with descriptive error when developer commits an AWS access key pattern or DB URL with credentials |

---

## Implementation Steps

### 1. Create `.pre-commit-config.yaml` at the repository root

```yaml
# .pre-commit-config.yaml
# SmartHandoff — pre-commit hooks for secret detection and code quality.
# Install: pip install pre-commit && pre-commit install
# Run manually: pre-commit run --all-files

default_install_hook_types: [pre-commit]

repos:
  # ── Secret detection — gitleaks ────────────────────────────────────────
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks
        name: "gitleaks — detect hardcoded secrets"
        description: "Scan staged files for secrets, API keys, and credentials."
        # --no-git: scan staged content rather than the full git history
        # --redact: mask secret values in the output so they are not echoed to terminal
        args: ["--no-git", "--redact", "--verbose"]

  # ── Pre-commit standard hooks ──────────────────────────────────────────
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: detect-private-key
        name: "detect-private-key — block RSA/EC key commits"
      - id: check-added-large-files
        args: ["--maxkb=1024"]
      - id: end-of-file-fixer
      - id: trailing-whitespace
        args: ["--markdown-linebreak-ext=md"]
```

### 2. Create `.gitleaks.toml` at the repository root for project-specific configuration

The default gitleaks ruleset is comprehensive but may produce false positives on `terraform.tfvars.example` placeholder values. The `.gitleaks.toml` file adds allowlist entries for known-safe patterns:

```toml
# .gitleaks.toml
# SmartHandoff-specific gitleaks configuration.
# Extends the built-in ruleset with project-specific allowlists.
title = "SmartHandoff Gitleaks Config"

[extend]
# Inherit all gitleaks default rules
useDefault = true

[[allowlists]]
description = "Terraform example variable files — intentional placeholder values"
paths = [
  "infra/terraform/environments/.*/terraform\\.tfvars\\.example",
]

[[allowlists]]
description = "BOOTSTRAP.md — placeholder echo commands in documentation"
paths = [
  "infra/BOOTSTRAP\\.md",
]
regexes = [
  "PLACEHOLDER_REPLACE_BEFORE_USE",
  "actual-value",
]
```

### 3. Add developer setup instruction to repository README

Add the following section to `README.md` under a "Development Setup" heading (or extend the existing one):

```markdown
## Pre-Commit Hooks (Secret Detection)

This repository uses [gitleaks](https://github.com/gitleaks/gitleaks) to prevent
secrets from being committed.

**One-time setup (required for all contributors):**

```bash
pip install pre-commit
pre-commit install
```

To run all hooks manually against all files:

```bash
pre-commit run --all-files
```
```

---

## Files Modified / Created

| File | Action |
|---|---|
| `.pre-commit-config.yaml` | Create with `gitleaks` and `pre-commit-hooks` configuration |
| `.gitleaks.toml` | Create with project-specific allowlists |
| `README.md` | Add "Pre-Commit Hooks" setup section |

---

## Verification

```bash
# Install hooks
pip install pre-commit
pre-commit install

# Test: attempt to commit a fake AWS key — should be blocked
echo 'AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE' > /tmp/test_secret.env
git add /tmp/test_secret.env
git commit -m "test"
# Expected: gitleaks hook FAILED with detected secret pattern

# Clean up
git restore --staged /tmp/test_secret.env
rm /tmp/test_secret.env

# Confirm clean repo passes
pre-commit run --all-files
# Expected: all hooks pass on current repository state
```
