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

## Purpose

This repository provides:
* Reusable GitHub workflows for API repositories (linting, validation)
* Shared GitHub Actions with cross-repository value
* Validation scripts and schemas for release planning
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

### Linting

OpenAPI and test definition linting using Spectral and other linters.

* **Location**: [linting/](linting/)
* **Configuration**: [linting/config/.spectral.yaml](linting/config/.spectral.yaml)
* **Documentation**: [linting/docs/](linting/docs/)
* **Workflows**: `spectral-oas.yml`, `pr_validation.yml`

#### Caller Workflow Templates

Templates for API repositories to add to their `.github/workflows/` folder:

* [spectral-oas-caller.yml](linting/workflows/spectral-oas-caller.yml) - OpenAPI linting
* [pr_validation_caller.yml](linting/workflows/pr_validation_caller.yml) - PR validation

### Validation

Schema and semantic validation for release planning files.

* **Location**: [validation/](validation/)
* **Schemas**: [validation/schemas/](validation/schemas/) - release-plan, release-metadata
* **Scripts**: [validation/scripts/](validation/scripts/)

#### Release Plan Validation

Validates `release-plan.yaml` and `release-metadata.yaml` files against CAMARA schemas.

```bash
# Basic validation
python3 validation/scripts/validate-release-plan.py path/to/release-plan.yaml

# With file existence checks
python3 validation/scripts/validate-release-plan.py release-plan.yaml --check-files
```

### API Review (Deprecated)

Legacy API review validation system (Fall25 meta-release specific).

* **Location**: [api-review/](api-review/), [scripts/](scripts/)
* **Status**: Deprecated - not maintained for future releases
* **Workflow**: `api-review-reusable.yml`

### Shared Actions

Reusable GitHub Actions for cross-repository use.

* **Location**: [shared-actions/](shared-actions/)
* **Actions**: `validate-release-plan` — schema and semantic validation for release-plan.yaml

## Repository Structure

```text
tooling/
├── .github/
│   └── workflows/               # Reusable workflows (public interface)
│       ├── api-review-reusable.yml  # Deprecated
│       ├── pr_validation.yml
│       ├── release-automation-reusable.yml
│       └── spectral-oas.yml
├── api-review/                  # Deprecated
│   ├── docs/
│   └── workflows/
├── linting/
│   ├── config/                  # Spectral and linting configuration
│   ├── docs/
│   └── workflows/               # Caller workflow templates
├── scripts/                     # Deprecated
│   └── api_review_validator_v0_6.py
├── shared-actions/
│   └── validate-release-plan/   # Composite GitHub Action
└── validation/
    ├── docs/
    ├── schemas/                 # JSON/YAML schemas
    │   ├── release-plan-schema.yaml
    │   └── release-metadata-schema.yaml
    └── scripts/
        └── validate-release-plan.py
```

## Release Information

The latest release is [v0.2.3](https://github.com/camaraproject/tooling/releases/tag/v0.2.3).

* API repositories reference the `v0` floating tag, which tracks the latest patch release
* The release candidate of CAMARA Release Automation is on the [`release-automation`](https://github.com/camaraproject/tooling/tree/release-automation) branch (tag `ra-v1-rc`), to be merged into `main` soon
* Tested versions are in the `main` branch
* Versions under development are in feature branches

## Contributing

Maintained by **Commonalities Working Group**.

* Meetings of the working group are held virtually
  * Schedule: see [Commonalities Working Group wiki page](https://lf-camaraproject.atlassian.net/wiki/x/_QPe)
  * [Registration / Join](https://zoom-lfx.platform.linuxfoundation.org/meeting/91016460698?password=d031b0e3-8d49-49ae-958f-af3213b1e547)
  * Minutes: Access [meeting minutes](https://lf-camaraproject.atlassian.net/wiki/x/2AD7Aw)
* Mailing List
  * Subscribe / Unsubscribe to the mailing list <https://lists.camaraproject.org/g/wg-commonalities>
  * A message to the community can be sent using <wg-commonalities@lists.camaraproject.org>
