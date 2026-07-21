---
id: TASK-006
title: "Security Audit — Verify Zero Hardcoded Credentials in All Terraform Sources"
user_story: US-001
epic: EP-TECH
sprint: 1
layer: Security / Compliance
estimate: 1h
priority: Must Have
status: Done
date: 2026-07-14
assignee: DevOps Engineer
upstream: [TASK-001, TASK-002, TASK-003]
---

# TASK-006: Security Audit — Verify Zero Hardcoded Credentials in All Terraform Sources

> **Story:** US-001 | **Epic:** EP-TECH | **Sprint:** 1 | **Layer:** Security / Compliance | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-14

---

## Context

**Acceptance Criterion 4** and the DoD item state:

> *"Zero plaintext secrets found; all secrets are mounted from Secret Manager."*
> *"No hardcoded credentials in any `.tf`, `.tfvars`, or CI configuration files."*

This task performs a structured static scan of all Terraform files to confirm compliance before the PR is raised for code review. It is a blocking gate — any finding must be remediated before TASK-008 (code review) begins.

References: **OWASP A07:2021 – Identification and Authentication Failures**, **OWASP A05:2021 – Security Misconfiguration**.

---

## Acceptance Criteria Addressed

| US-001 AC | Requirement |
|---|---|
| **Scenario 4** | Every Cloud Run service's environment variables and container image layers inspected — zero plaintext secrets |
| **DoD** | No hardcoded credentials in `.tf`, `.tfvars`, or CI configuration files |

---

## Implementation Steps

### 1. Run Credential Pattern Scan on All `.tf` Files

Execute the following scan from the repository root. Any match is a blocker:

```bash
# Scan for common credential patterns in .tf files
grep -rn --include="*.tf" \
  -E "(password|secret|api_key|token|private_key|signing_key|auth_token)\s*=\s*\"[^$\"][^\"]{6,}\"" \
  infra/terraform/ \
  | grep -v "PLACEHOLDER_CHANGE_BEFORE_DEPLOY" \
  | grep -v "#"
```

**Expected output:** No matches. Any match that is not a variable reference (`var.*`), module output reference (`module.*`), resource attribute reference, or explicit placeholder must be remediated.

### 2. Scan `.tfvars` and `.tfvars.example` Files

```bash
# Check .tfvars.example files contain only placeholder values
grep -rn --include="*.tfvars*" \
  -E "(password|secret|key|token)\s*=\s*\"[^<\"][^\"]{5,}\"" \
  infra/terraform/environments/
```

**Expected output:** No real credentials. Placeholder values follow the pattern `"<REPLACE_WITH_...>"` or `"PLACEHOLDER_..."`.

Verify `.gitignore` contains:
```
# Terraform variable files with real values — never commit
infra/terraform/environments/**/*.tfvars
!infra/terraform/environments/**/*.tfvars.example
```

### 3. Verify Cloud Run Container Definitions Have No Plaintext Secret Values

Review the `dynamic "env"` blocks added in TASK-002 in `modules/cloud_run/main.tf`:

```bash
# Ensure no env var has a literal value containing a secret pattern
grep -n "value\s*=" infra/terraform/modules/cloud_run/main.tf \
  | grep -v "var\." \
  | grep -v "each\." \
  | grep -v "local\." \
  | grep -v "ENVIRONMENT\|GCP_PROJECT_ID\|REGION"
```

**Expected output:** Only the three non-sensitive env vars (`ENVIRONMENT`, `GCP_PROJECT_ID`, `REGION`) should have literal values. All others must use `value_source.secret_key_ref`.

### 4. Verify No Terraform State Files Committed to Source Control

```bash
# Ensure no .tfstate files are tracked by git
git ls-files infra/terraform/ | grep -E "\.tfstate$|\.tfstate\.backup$"
```

**Expected output:** Empty. If any state files are tracked, remove them with `git rm --cached` and add `*.tfstate` to `.gitignore`.

### 5. Verify `terraform.tfvars` Not Committed

```bash
git ls-files infra/terraform/environments/ | grep "\.tfvars$" | grep -v "\.example$"
```

**Expected output:** Empty. Only `terraform.tfvars.example` files should be tracked.

### 6. Scan for Sensitive Patterns in CI/CD Configuration Files

```bash
grep -rn --include="*.yml" --include="*.yaml" \
  -E "(DB_PASSWORD|REDIS_AUTH|JWT_SECRET|API_KEY|AUTH_TOKEN)\s*:" \
  .github/workflows/ \
  | grep -v "\${{" \
  | grep -v "secrets\."
```

**Expected output:** No matches. All secret references in CI workflows must use `${{ secrets.* }}` syntax.

---

## Remediation Guide

| Finding | Remediation |
|---|---|
| Plaintext credential in `.tf` | Replace with `var.<name>` reference and add variable to `variables.tf`; pass value via Secret Manager or CI secret |
| Real value in `.tfvars.example` | Replace with `<REPLACE_WITH_REAL_VALUE>` placeholder |
| `.tfstate` committed | `git rm --cached <file>`, add to `.gitignore`, rotate any exposed credentials |
| Secret in CI YAML | Move to GitHub Actions secret or GCP Secret Manager; reference via `${{ secrets.NAME }}` |

---

## Definition of Done

- [ ] `grep` credential scan returns zero matches in all `.tf` files
- [ ] All `.tfvars.example` files contain only placeholder values
- [ ] `git ls-files` confirms no `.tfstate` or real `.tfvars` files are tracked
- [ ] Cloud Run `main.tf` has no literal secret values — only `ENVIRONMENT`, `GCP_PROJECT_ID`, `REGION`
- [ ] CI/CD YAML files reference only `${{ secrets.* }}` for credentials
- [ ] `.gitignore` excludes `*.tfvars` (real) while tracking `*.tfvars.example`
- [ ] Scan results documented as a checklist comment in the PR

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-002 | Preceding task | Cloud Run secret mounts must be in place before scanning for plaintext |
| TASK-003 | Preceding task | Secrets module wiring must be complete |

---

## Files Modified

| File | Action |
|---|---|
| `.gitignore` | Verify/add `*.tfvars` exclusion rule if missing |
| `infra/terraform/environments/dev/terraform.tfvars.example` | Verify all values are placeholders |
| `infra/terraform/environments/staging/terraform.tfvars.example` | Verify all values are placeholders |
| `infra/terraform/environments/prod/terraform.tfvars.example` | Verify all values are placeholders |
