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
> See the [release candidate documentation](https://github.com/camaraproject/tooling/blob/validation-framework/documentation/README.md) for codeowners and contributors using the new framework on their API repositories.

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

The repository ships two consumption lines:

* **v1-rc** — unified validation framework (linting, validation, release automation) in release candidate phase for volunteer repositories (to get onboarded, update your `release-plan.yaml` file with a planned next release (`target_release_type: pre-release-alpha` or `pre-release-rc`). If not yet onboarded you will receive a PR with the caller workflows at latest on the next working day.)
* **v0** — legacy linting only, kept for repositories not yet onboarded to v1-rc

### v1-rc — CAMARA Validation and Release Automation V1

A single tag (`v1-rc`, lightweight, on the [`validation-framework`](https://github.com/camaraproject/tooling/tree/validation-framework) branch) covers:

* **Linting** — OpenAPI and test definition Spectral rulesets, including the Spring26 (Commonalities rc2) ruleset
* **Validation** — API definitions, test files, and release-plan / release-metadata files; results appear on pull requests and Release Issues
* **Release automation** — `/create-snapshot` → `/publish-release` workflow

See the [release candidate documentation](https://github.com/camaraproject/tooling/blob/validation-framework/documentation/README.md) for linting and validation, and the [Release Process Guide](https://github.com/camaraproject/ReleaseManagement/blob/main/documentation/README.md) (in ReleaseManagement) for release automation.

### v0 (legacy)

v0 ships linting only, kept available for repositories not yet onboarded to v1-rc. **There is no v0 release automation**, and Release Management no longer supports manual releases. Repositories that need to create a release must onboard to v1-rc.

#### v0 Linting

Spectral ruleset and MegaLinter invoked through `pr_validation.yml` and `spectral-oas.yml`.

* **Configuration**: [.spectral.yaml](linting/config/.spectral.yaml)
* **Caller templates**: [spectral-oas-caller.yml](linting/workflows/spectral-oas-caller.yml), [pr_validation_caller.yml](linting/workflows/pr_validation_caller.yml)

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
  * `update-readme-release-info` — update README release information block

## Repository Structure (v1-rc)

This is the structure on the `validation-framework` branch (the active v1-rc line) and will soon become the structure on `main`.

```text
tooling/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/                    # Reusable workflows (public interface)
│       ├── pr_validation.yml         # v0 linting
│       ├── release-automation-regression.yml
│       ├── release-automation-reusable.yml
│       ├── spectral-oas.yml          # v0 linting
│       ├── update-floating-tag.yml
│       ├── validation-regression.yml
│       ├── validation-settings-ci.yml
│       └── validation.yml
├── config/
│   └── validation-settings.yaml      # Central per-repo validation settings
├── documentation/                    # User-facing documentation
│   └── validation/
├── linting/
│   ├── config/                       # Spectral rulesets (.spectral.yaml, .spectral-r3.4.yaml, .spectral-r4.yaml) and lint functions
│   ├── docs/
│   └── workflows/                    # Caller workflow templates
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
│   ├── update-readme-release-info/
│   └── validate-release-plan/
├── tooling_lib/                      # Shared Python library
│   └── tests/
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

* **`v1-rc`** — lightweight tag on the `validation-framework` branch; promoted to `v1` (release 1.0.0) at GA
* **`v0`** — floating tag tracking the latest v0.x release ([v0.3.0](https://github.com/camaraproject/tooling/releases/tag/v0.3.0))
* **`main`** — tested v0 line
* **`validation-framework`** — active development for v1-rc

## Contributing

Maintained by **Commonalities Working Group**.

* Meetings of the working group are held virtually
  * Schedule: see [Commonalities Working Group wiki page](https://lf-camaraproject.atlassian.net/wiki/x/_QPe)
  * [Registration / Join](https://zoom-lfx.platform.linuxfoundation.org/meeting/91016460698?password=d031b0e3-8d49-49ae-958f-af3213b1e547)
  * Minutes: Access [meeting minutes](https://lf-camaraproject.atlassian.net/wiki/x/2AD7Aw)
* Mailing List
  * Subscribe / Unsubscribe to the mailing list <https://lists.camaraproject.org/g/wg-commonalities>
  * A message to the community can be sent using <wg-commonalities@lists.camaraproject.org>
