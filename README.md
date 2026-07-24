<a href="https://github.com/camaraproject/tooling/commits/" title="Last Commit"><img src="https://img.shields.io/github/last-commit/camaraproject/tooling?style=plastic"></a>
<a href="https://github.com/camaraproject/tooling/issues" title="Open Issues"><img src="https://img.shields.io/github/issues/camaraproject/tooling?style=plastic"></a>
<a href="https://github.com/camaraproject/tooling/pulls" title="Open Pull Requests"><img src="https://img.shields.io/github/issues-pr/camaraproject/tooling?style=plastic"></a>
<a href="https://github.com/camaraproject/tooling/graphs/contributors" title="Contributors"><img src="https://img.shields.io/github/contributors/camaraproject/tooling?style=plastic"></a>
<a href="https://github.com/camaraproject/tooling" title="Repo Size"><img src="https://img.shields.io/github/repo-size/camaraproject/tooling?style=plastic"></a>
<a href="https://github.com/camaraproject/tooling/blob/main/LICENSE" title="License"><img src="https://img.shields.io/badge/License-Apache%202.0-green.svg?style=plastic"></a>
<a href="https://github.com/camaraproject/Governance/blob/main/ProjectStructureAndRoles.md" title="Working Group"><img src="https://img.shields.io/badge/Working%20Group-red?style=plastic"></a>

# tooling

Repository to develop and provide shared tooling across the CAMARA project and its API repositories.

Maintained under the supervision of Commonalities Working Group.

* Commonalities Working Group: https://github.com/camaraproject/Commonalities
* Working Group wiki: https://lf-camaraproject.atlassian.net/wiki/x/_QPe

> **CAMARA Validation and Release Automation V1 is in release candidate phase.**
> See the [release candidate documentation](https://github.com/camaraproject/tooling/blob/main/documentation/README.md) for codeowners and contributors using the new framework on their API repositories.

## Purpose

This repository provides:
* Reusable GitHub workflows for API repositories (linting, validation, release automation)
* Shared GitHub Actions with cross-repository value
* Validation scripts and schemas for release planning
* Release automation for API repository releases
* Configuration files and documentation for workflows

## Scope

**Belongs here:**
* Reusable CI workflows consumed by API repositories
* Shared GitHub Actions used by workflows
* Validation scripts, schemas, and configuration
* Supporting documentation for the above

**Does not belong here:**
* Project-wide campaigns (see [project-administration](https://github.com/camaraproject/project-administration))
* Cross-repository orchestration
* Authoritative project-level data

## Current Content

The repository ships one active consumption line:

* **v1-rc** — unified validation framework (linting, validation, release automation) in release candidate phase. All active CAMARA API repositories use v1-rc.

The historical **v0** tag covered legacy PR linting only. Active CAMARA API repositories have disabled v0 callers; the tag is retained only for compatibility with old references and is not advanced for new releases.

### v1-rc — CAMARA Validation and Release Automation V1

A single lightweight tag (`v1-rc`) covers:

* **Linting** — OpenAPI and test definition Spectral rulesets, including the Spring26 (Commonalities rc2) ruleset
* **Validation** — API definitions, test files, and release-plan / release-metadata files; results appear on pull requests and Release Issues
* **Release automation** — `/create-snapshot` → `/publish-release` workflow

See the [release candidate documentation](https://github.com/camaraproject/tooling/blob/main/documentation/README.md) for linting and validation, and the [Release Process Guide](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/README.md) (in ReleaseManagement) for release automation.

### v0 (retired legacy)

v0 shipped linting only and is retired. **There is no v0 release automation**, Release Management no longer supports manual releases, and active repositories should not use v0 caller workflows.

### Shared Actions

Reusable GitHub Actions for cross-repository use.

* **Location**: [shared-actions/](shared-actions/)
* **Actions**:
  * `validate-release-plan` — release-plan.yaml schema and semantic validation
  * `create-snapshot` — create release snapshot branches
  * `derive-release-state` — determine release state from repository artifacts
  * `post-bot-comment` — post formatted bot comments on issues
  * `run-validation` — invoke the v1-rc validation framework
  * `sync-release-issue` — synchronize release issue state and body
  * `update-issue-section` — update marked sections in issue bodies

## Repository Structure

```text
tooling/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/                    # Reusable workflows (public interface)
│       ├── pr_validation.yml         # retired v0 linting
│       ├── release-automation-regression.yml
│       ├── release-automation-reusable.yml
│       ├── spectral-oas.yml          # retired v0 linting
│       ├── update-floating-tag.yml
│       ├── validation-regression.yml
│       ├── validation-settings-ci.yml
│       └── validation.yml
├── config/
│   └── validation-settings.yaml      # Central per-repo validation settings
├── CHANGELOG.md                      # Numbered tooling release history
├── documentation/                    # User-facing documentation
│   └── validation/
├── linting/
│   ├── config/                       # Spectral rulesets (.spectral.yaml, .spectral-r3.4.yaml, .spectral-r4.yaml) and lint functions
│   ├── docs/
│   └── workflows/                    # Caller workflow templates for retired v0 linting
├── release_automation/
│   ├── config/
│   ├── docs/
│   ├── regression/                   # Release Automation regression fixtures
│   ├── scripts/
│   ├── templates/                    # Mustache templates for issues, PRs, comments
│   ├── tests/
│   └── workflows/                    # Caller workflow template
├── shared-actions/
│   ├── create-snapshot/
│   ├── derive-release-state/
│   ├── post-bot-comment/
│   ├── run-validation/
│   ├── sync-release-issue/
│   ├── update-issue-section/
│   └── validate-release-plan/
├── tooling_lib/                      # Shared Python library
│   └── tests/
├── VERSION.yaml                      # Current numbered tooling release version
└── validation/                       # CAMARA Validation Framework v1
    ├── bundling/                     # Redocly bundling pipeline
    ├── config/
    ├── context/
    ├── docs/
    ├── engines/                      # Engine adapters (Spectral, yamllint, gherkin, Python)
    │   └── python_checks/
    ├── output/                       # Summary, annotations, PR comment, status
    ├── postfilter/
    ├── rules/                        # Rule metadata YAML
    ├── schemas/                      # JSON/YAML schemas (findings, rule metadata, release-plan, release-metadata)
    ├── scripts/
    ├── tests/
    └── workflows/                    # Caller workflow template
```

## Release Information

* **[`VERSION.yaml`](VERSION.yaml)** — records the current numbered tooling release version.
* **[`CHANGELOG.md`](CHANGELOG.md)** — records numbered release notes and links to GitHub comparisons.
* **`v1-rc`** — floating lightweight tag covering the validation and release automation framework v1 release candidate. This is the active consumption line for CAMARA API repositories.
* **Numbered release tags** — immutable tags such as `v0.8.1` mark release points on `main`.
* **`v0`** — retired legacy linting tag. It is kept for historical compatibility and is not advanced for new releases.
* **`main`** — active development branch.

## Contributing

Maintained by **Commonalities Working Group**.

* Meetings of the working group are held virtually
  * Schedule: see [Commonalities Working Group wiki page](https://lf-camaraproject.atlassian.net/wiki/x/_QPe)
  * [Registration / Join](https://zoom-lfx.platform.linuxfoundation.org/meeting/91016460698?password=d031b0e3-8d49-49ae-958f-af3213b1e547)
  * Minutes: Access [meeting minutes](https://lf-camaraproject.atlassian.net/wiki/x/2AD7Aw)
* Mailing List
  * Subscribe / Unsubscribe to the mailing list <https://lists.camaraproject.org/g/wg-commonalities>
  * A message to the community can be sent using <wg-commonalities@lists.camaraproject.org>
