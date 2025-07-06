# CAMARA API Review Workflow Usage Guide

This guide provides instructions for using the automated CAMARA API review workflow system with GitHub Actions.

> 📋 **Version**: Updated based on implementation analysis and architectural decisions

## Quick Start (Recommended Method)

**For most release reviews, use the comment trigger:**

1. **Prepare issue**: Ensure your release review issue has the PR URL on line 3 or 4:
   ```markdown
   # Release Review for MyAPI v1.0.0-rc.1
   
   https://github.com/camaraproject/MyAPI/pull/123
   ```

2. **Trigger review**: Comment `/rc-api-review` in the issue

3. **Wait for results**: Bot will post results automatically in the same issue

**That's it!** The workflow uses sensible defaults for most release candidate reviews.

---

## 📦 Repository Architecture

### Standard Deployment Model
The CAMARA API Review system uses a distributed architecture:

1. **Tooling Repository** (`camaraproject/tooling`):
   - Contains: Reusable workflow (`api-review-reusable.yml`)
   - Contains: Validator scripts (`/scripts/api_review_validator_v0_6.py`)
   - Purpose: Centralized maintenance of validation logic

2. **Trigger Locations** (flexible):
   - **ReleaseManagement Repository**: For release review processes
   - **Individual API Repositories**: For PR-based reviews
   - Contains: Trigger workflow (`api-review-trigger.yml`)
   - Purpose: Initiate reviews in context

### Important Path Information
- **In Repository**: Scripts are stored in `/scripts/` directory
- **During Execution**: The tooling repository is checked out as `review-tools/`, so scripts are accessed from `review-tools/scripts/`

### Deployment Flexibility
The trigger workflow can be deployed in:
- `camaraproject/ReleaseManagement` - For centralized release reviews
- `camaraproject/QualityOnDemand` - For API-specific PR reviews  
- Any CAMARA API repository - For repository-specific validation

---

| Aspect | Comment Trigger | Manual Trigger |
|--------|----------------|----------------|
| **Convenience** | ⭐⭐⭐ Very easy - just comment `/rc-api-review` | ⭐⭐ Requires navigating to Actions tab |
| **Setup Required** | PR URL must be in issue description (lines 3-4) | Manual entry of all parameters |
| **Customization** | Uses defaults (release-candidate, v0.6) | Full control over all parameters |
| **Use Case** | Standard release reviews | Special cases, different parameters |
| **User Permission** | Anyone who can comment on issues | Users with Actions workflow permissions |
| **Audit Trail** | Visible in issue comments | Visible in Actions history |

## Version Support

The workflow supports different CAMARA Commonalities versions with dedicated validation logic:

| Commonalities Version | Validator Script | Status | Key Validation Rules |
|----------------------|------------------|---------|---------------------|
| **0.6** | `api_review_validator_v0_6.py` | ✅ **Implemented** | - Updated XCorrelator pattern<br>- UNAUTHENTICATED (not AUTHENTICATION_REQUIRED)<br>- No IDENTIFIER_MISMATCH<br>- Mandatory description templates |
| **0.7** | `api_review_validator_v0_7.py` | 📅 **Planned** | Future Commonalities 0.7 requirements |
| **0.8** | `api_review_validator_v0_8.py` | 📅 **Planned** | Future Commonalities 0.8 requirements |
| **1.0** | `api_review_validator_v1_0.py` | 📅 **Planned** | Future Commonalities 1.0 requirements |

> **Design Note**: The validator acts as a reporter for manual review. It will always exit successfully to provide comprehensive feedback for human reviewers who can assess false positives and make final decisions.

## Architecture

```
Trigger Repository (ReleaseManagement or API Repository)
    ↓ Manual Dispatch or Comment Trigger
┌─────────────────────────────────────────┐
│  api-review-trigger.yml                 │
│  - Validates inputs                     │
│  - Checks comment triggers              │
│  - Calls reusable workflow              │  
│  - Posts results to issue/summary       │
└─────────────────────────────────────────┘
    ↓ Calls workflow from tooling
┌─────────────────────────────────────────┐
│  camaraproject/tooling                  │
│  /.github/workflows/                    │
│     api-review-reusable.yml             │
│  - Checks out tooling as "review-tools" │
│  - Validates Commonalities version      │
│  - Loads script from:                   │
│    review-tools/scripts/                │
│  - Checks out target PR                 │
│  - Runs validation                      │
│  - Creates artifacts                    │
└─────────────────────────────────────────┘
    ↓ Uses Version-Specific Script
┌─────────────────────────────────────────┐
│  /scripts/api_review_validator_v0_6.py  │
│  (accessed as review-tools/scripts/*)   │
│  - Commonalities 0.6 validation logic   │
│  - Reports findings for manual review   │
│  - Generates detailed reports           │
└─────────────────────────────────────────┘
```

### Key Points:
- **Trigger workflow** can be in any repository
- **Reusable workflow and scripts** are centralized in tooling repository
- **Validator** produces reports for manual review (always exits successfully)

## Setup Instructions

### Step 1: Tooling Repository Setup

Ensure the following files exist in `camaraproject/tooling`:

```
tooling/
├── .github/
│   └── workflows/
│       └── api-review-reusable.yml     # Reusable validation workflow
└── scripts/
    └── api_review_validator_v0_6.py    # REQUIRED: Validator script
```

### Step 2: Deploy Trigger Workflow

The trigger workflow can be deployed in multiple locations:

#### Option A: ReleaseManagement Repository (for release reviews)
```
ReleaseManagement/
└── .github/
    └── workflows/
        └── api-review-trigger.yml      # Trigger workflow for release reviews
```

#### Option B: Individual API Repositories (for PR reviews)
```
QualityOnDemand/  (or any API repository)
└── .github/
    └── workflows/
        └── api-review-trigger.yml      # Trigger workflow for PR reviews
```

### Step 3: Configure Trigger Workflow

In `api-review-trigger.yml`, ensure it references the tooling repository:

```yaml
call-review-workflow:
  uses: camaraproject/tooling/.github/workflows/api-review-reusable.yml@main
  with:
    # ... parameters
  secrets: inherit
```

### Required Permissions

Ensure repositories have:
- **Read access** to all CAMARA project repositories
- **Write access** to post comments on issues (for repositories with trigger workflow)
- **Actions permissions** to run workflows

## Design Philosophy

### Validator as Reporter
The validator is designed as a **reporting tool for manual review**, not an automated gatekeeper:
- Always exits successfully to provide comprehensive feedback
- Human reviewers assess false positives and context
- Supports informed decision-making in the release process

### Version Handling
When a non-0.6 version is requested:
- The validator warns about the version mismatch
- Continues validation using v0.6 rules
- Clearly indicates in reports which rules were applied

### Deployment Flexibility
The trigger workflow can be deployed wherever reviews are needed:
- Centralized in ReleaseManagement for release reviews
- Distributed in API repositories for PR reviews
- Customized per repository's needs

## Troubleshooting

### Script Not Found Error

If you see: `❌ Validator script not found at review-tools/scripts/api_review_validator_v0_6.py`

1. **Verify tooling repository**: Ensure scripts exist in `camaraproject/tooling/scripts/`
2. **Check workflow reference**: Confirm trigger workflow uses correct path to reusable workflow
3. **Verify file location**: Script must be in `/scripts/` directory of tooling repository
4. **Check permissions**: Ensure workflow has read access to tooling repository

### Version Mismatch Warning

The validator will process files using v0.6 rules regardless of the version parameter. To avoid confusion:
- Always use `commonalities_version: 0.6` until other versions are implemented
- Future versions will require new validator scripts

### No Results Posted

If results aren't posted to the issue:
1. Check workflow permissions for issue write access
2. Verify the issue number is correctly captured
3. Check Actions logs for error messages
4. Ensure the workflow completed successfully

## Best Practices

1. **Deploy Strategically**: 
   - Use ReleaseManagement for formal release reviews
   - Deploy in API repositories for continuous PR validation
2. **Version Alignment**: Specify commonalities version 0.6 until others are available
3. **Review Reports**: Always download detailed artifacts for comprehensive analysis
4. **Manual Review**: Use validator output as input for human decision-making
5. **PR Format**: Keep PR URLs on line 3 or 4 of issue descriptions for comment triggers
6. **Monitor Workflows**: Check Actions logs if issues occur

## Security Considerations

- Workflows only have **read access** to target repositories
- Scripts run in isolated GitHub Actions environments
- Filenames are sanitized to prevent path traversal attacks
- No sensitive data is stored in artifacts
- Comments are posted using GitHub token with minimal permissions

## Future Enhancements

Based on analysis, these improvements are recommended:

1. **Additional Version Support**: Add validators for Commonalities 0.7, 0.8, 1.0
2. **API Selection**: Add ability to validate specific APIs within a repository
3. **Exclusion Patterns**: Support for ignoring certain files

---

**Last Updated**: Based on architectural decisions and implementation analysis
**Current Version**: Supports Commonalities 0.6 validation
**Deployment Model**: Distributed architecture with centralized validation logic