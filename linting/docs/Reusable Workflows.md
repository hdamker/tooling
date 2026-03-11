# Reusable Workflows Implementation Guide

## Overview

This guide focuses on implementing caller workflows in CAMARA API repositories that utilize reusable liniting workflows from the `tooling` repository. 
For comprehensive information about reusable workflows, refer to the official GitHub documentation: [Reusing workflows](https://docs.github.com/en/actions/sharing-automations/reusing-workflows).


## `tooling` Repository Structure

All files needed for implementation are stored in `tooling` repository.
```
tooling/
├── .github/workflows/          # Standard GitHub workflows location
├── linting/
│   ├── workflows/              # Caller workflows that use reusable workflows
│   ├── config/                 # Configuration files for linting tools
│   └── docs/                   # Documentation for linting  workflows
└── ...                         # other tools

```

### Reusable Workflows in `tooling` Repository

Reusable workflows are stored in the `tooling` repository under `.github/workflows/`.

Currenly definded workflows:

- **pr_validation.yml** - workflow to check the PR is related to API definition (OpenAPI specification, Gherkin test definitions) using Megalinter
[Megalinter](https://megalinter.io) is a comprehensive linting tool designed to analyze and improve code quality across multiple programming languages and file types.
Megalinter combines dozens of popular linters into a single tool, allowing to check code quality, formatting, security issues, and best practices across an entire repository.
Additional checks can be performed for Release PRs (tbd).

- **spectral-oas.yml** - workflow to manually trigger [Spectral](https://meta.stoplight.io/docs/spectral) linter for OpenAPI with CAMARA ruleset.
Manual run of this workflow produces more detailed output compared to results presented by Megalinter.

### Workflow configuration files in `linting` folder

Configuration files in `/linting/config/`:
- **.gherkin-lintrc** - ruleset for [gherkin-lint](https://github.com/gherkin-lint/gherkin-lint) tool
- **.spectral.yaml** - CAMARA rulest for [Spectral](https://meta.stoplight.io/docs/spectral) linter
- **.yamllint.yml** - ruleset for [yamllint](https://yamllint.readthedocs.io/en/stable/index.html) tool

The rulesets above are copied from [Commonalities/artifacts](https://github.com/camaraproject/Commonalities/tree/main/artifacts/linting_rules).


### Caller Workflows in `linting` folder
Caller workflows are stored in `/linting/workflows/`.

Currenly definded workflows:
- **pr_validation_caller.yml** - caller for PR validation workflow
- **spectral-oas-caller.yml** - caller for Spectral linter with CAMARA ruleset



## Setting Up Linting Workflows

### API Repository Structure

```
API-repository/
├── .github/workflows/           # Standard GitHub workflows location
├── code
├── documentation
├── ...

```

### Deployment of Caller Workflows

Caller workflows need to be placed in  the `.github/workflows` folder of the API repository. This is the **only** required action.

```
API-repository/
├── .github/workflows/
   ├── pr_validation_caller.yml
   └── spectral-oas-caller.yml 
```
    
The caller workflow `uses:` line selects which version of `tooling` provides the reusable workflow, for example:

```yaml
uses: camaraproject/tooling/.github/workflows/pr_validation.yml@v0
```

Inside `pr_validation.yml`, workflow-owned assets are resolved from that same effective tooling repository and commit, so branch-based or SHA-based pilot calls stay internally consistent.

For backward compatibility, callers that still use the older permissions block without `id-token: write` can still start the reusable workflow and automatically fall back to the legacy internal `camaraproject/tooling@v0` asset resolution. That keeps existing API repositories working while a coordinated caller migration is prepared.

The `configurations` input does **not** select a tooling branch. It selects a subfolder inside `/linting/config/` from the tooling ref already chosen by the reusable workflow call.

```yaml
#    with:
#      configurations: staging
```
This way custom configurations can be used if needed by a given repository. Create the relevant subfolder in `tooling/linting/config/` and reference it through `configurations`.

## Runnig Linting Workflows

###  PR validation
This workflow is triggered for each Pull Request in the API Repository.
Additional job (to be defined) is executed for PRs modifying CHANGELOG.md file (like Release PRs).


### Manual execution of Spectral linting with CAMARA ruleset
This workflow can be triggered manually  (on `workflow_dispatch') from Actions menu of Github repository.
