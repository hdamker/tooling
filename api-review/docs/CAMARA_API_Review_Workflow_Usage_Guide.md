# CAMARA API Review Workflow Usage Guide

This guide provides instructions for using the automated CAMARA API review workflow system with GitHub Actions.

## Quick Start

### Comment Triggers (Recommended)

**For release candidate reviews:**
1. **Prepare issue**: Ensure your release review issue has the PR URL on line 3 or 4:
   ```markdown
   # Release Review for MyAPI v1.0.0-rc.1
   
   https://github.com/camaraproject/MyAPI/pull/123
   ```

2. **Trigger review**: Comment `/rc-api-review` in the issue

3. **Wait for results**: Bot will post results automatically in the same issue

**For work-in-progress reviews:**
1. **In an issue**: Comment `/wip-api-review` to review the main branch
2. **In a pull request**: Comment `/wip-api-review` to review the current PR

### Branch Determination Logic

| Trigger Command | In Issue | In Pull Request |
|----------------|----------|----------------|
| `/rc-api-review` | Reviews PR from issue description lines 3-4 | Reviews current PR |
| `/wip-api-review` | Reviews main branch of current repository | Reviews current PR |

### Context Examples

**Release Candidate Review in Issue:**
```markdown
# Release Review for MyAPI v1.0.0-rc.1

https://github.com/camaraproject/MyAPI/pull/123

Comment: /rc-api-review
→ Reviews: MyAPI pull request #123
```

**Work-in-Progress Review in Issue:**
```markdown
# WIP Review Request

Comment: /wip-api-review  
→ Reviews: Current repository's main branch
```

**Any Review in Pull Request:**
```markdown
Comment in PR #456: /rc-api-review
→ Reviews: Current pull request #456

Comment in PR #456: /wip-api-review
→ Reviews: Current pull request #456
```

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

| Aspect | `/rc-api-review` | `/wip-api-review` |
|--------|----------------|------------------|
| **Purpose** | Release candidate validation | Work-in-progress validation |
| **In Issue** | Reviews PR from issue description | Reviews main branch |
| **In PR** | Reviews current PR | Reviews current PR |
| **Requirement** | PR URL must be in issue (lines 3-4) | No special requirements |
| **Use Case** | Final release reviews | Development validation |
| **Review Type** | `release-candidate` | `wip` |

## Version Support

The workflow currently supports only CAMARA Commonalities version 0.6:

| Commonalities Version | Validator Script | Status | Key Validation Rules |
|----------------------|------------------|---------|---------------------|
| **0.6** | `api_review_validator_v0_6.py` | ✅ **Implemented** | - Updated XCorrelator pattern<br>- UNAUTHENTICATED (not AUTHENTICATION_REQUIRED)<br>- No IDENTIFIER_MISMATCH<br>- Mandatory description templates |

**Important:** Only version 0.6 is currently implemented. Future versions will be added as new Commonalities releases become available.

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

### Step 1: Verify Tooling Repository Setup

Ensure the following files exist in `camaraproject/tooling`:

```
tooling/
├── .github/
│   └── workflows/
│       └── api-review-reusable.yml     # Reusable validation workflow
└── scripts/
    └── api_review_validator_v0_6.py    # REQUIRED: Commonalities 0.6 validator
```

**⚠️ CRITICAL REQUIREMENT**: The validator script **MUST** be present in `camaraproject/tooling/scripts/`. The workflow will fail if the required script is missing.

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
    tooling_repository: "camaraproject/tooling"
    # ... other parameters
  secrets: inherit
```

### Required Permissions

Ensure repositories have:
- **Read access** to all CAMARA project repositories
- **Write access** to post comments on issues (for repositories with trigger workflow)
- **Actions permissions** to run workflows

## Testing Deployment

### Using Custom Tooling Repository

For testing purposes, you can use a custom tooling repository by modifying the trigger workflow:

```yaml
call-review-workflow:
  uses: your-username/tooling/.github/workflows/api-review-reusable.yml@main
  with:
    tooling_repository: "your-username/tooling"
    # ... other parameters
  secrets: inherit
```

**Requirements for custom tooling repository:**
- Must contain `api-review-reusable.yml` in `.github/workflows/`
- Must contain `api_review_validator_v0_6.py` in `scripts/`
- Must be accessible by the workflow runner

**Note:** This is intended for testing and development only. Production deployments should use `camaraproject/tooling`.

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

## Usage Instructions

The workflow can be triggered in two ways:

### Method 1: Comment Trigger (Recommended)

This is the most convenient method for release managers.

#### Step 1: Prepare the Release Review Issue

1. Create or navigate to a release review issue in the ReleaseManagement repository
2. Ensure the issue description contains the PR URL on line 3 or 4
3. The URL must be in the format: `https://github.com/camaraproject/[repo]/pull/[number]`

**Example issue description:**
```markdown
# Release Review for QualityOnDemand v1.2.0-rc.1

Review request for the following pull request:
https://github.com/camaraproject/QualityOnDemand/pull/456

Please review the API definitions and provide feedback.
```

#### Step 2: Trigger the Review

1. In the release review issue, add a comment that starts with: `/rc-api-review`
2. The workflow will automatically:
   - Extract the PR URL from the issue description
   - Validate the PR exists and is accessible
   - Run the API review validation
   - Post results back to the same issue

**Example comment:**
```
/rc-api-review
```

#### Step 3: Review Results

The workflow will post results automatically, including:
- Summary of validation results
- Critical issues found
- Detailed report artifacts
- Next steps recommendations

### Method 2: Manual Workflow Dispatch

For advanced users who need more control over parameters.

#### Step 1: Navigate to Actions

1. Go to the repository containing the trigger workflow
2. Click on "Actions" tab
3. Select "CAMARA API Review Trigger" workflow
4. Click "Run workflow"

#### Step 2: Configure Parameters

Fill in the required parameters:
- **Pull Request URL**: Full URL of the PR to review
- **Review Type**: Choose between `release-candidate` or `wip`
- **Commonalities Version**: Select `0.6` (currently the only supported version)

#### Step 3: Review Results

Results will be posted to the workflow summary page and available as downloadable artifacts.

## Sample Results

### Successful Review Example
```markdown
## ✅ API Review Complete

**Triggered by**: Comment `/rc-api-review` by @release-manager
**Pull Request**: https://github.com/camaraproject/QualityOnDemand/pull/456
**Review Type**: release-candidate
**Commonalities Version**: 0.6

### ✅ **Ready for Release**

**APIs Reviewed**:
- 📄 `Quality On Demand` v1.2.0-rc.1 (regular)

**Issues Summary**:
- 🔴 Critical: 0
- 🟡 Medium: 1
- 🔵 Low: 2

**Recommendation**: ✅ No critical issues found - API is ready for release!

📄 **Detailed Report**: Download the `api-review-detailed-report-0.6` artifact
```

### Issues Found Example
```markdown
## ✅ API Review Complete

**Triggered by**: Comment `/rc-api-review` by @developer
**Pull Request**: https://github.com/camaraproject/DedicatedNetworks/pull/42
**Review Type**: release-candidate
**Commonalities Version**: 0.6

### ⚠️ **Conditional Approval**

**APIs Reviewed**:
- 📄 `Dedicated Network - Networks` v0.1.0-rc.1 (regular)
- 📄 `Dedicated Network - Network Profiles` v0.1.0-rc.1 (regular)
- 📄 `Dedicated Network - Accesses` v0.1.0-rc.1 (regular)

**Issues Summary**:
- 🔴 Critical: 3
- 🟡 Medium: 2
- 🔵 Low: 1

**Critical Issues Requiring Immediate Attention**:

*Dedicated Network - Networks*:
- ExternalDocs: Missing externalDocs object

*Dedicated Network - Accesses*:
- Error Responses: Forbidden error code 'IDENTIFIER_MISMATCH' found
- Security Schemes: Undefined security scheme 'oAuth2' referenced

**Recommendation**: ❌ Address 3 critical issue(s) before release

📄 **Detailed Report**: Download the `api-review-detailed-report-0.6` artifact
```

## Troubleshooting

### Script Not Found Error

If you see: `❌ Validator script not found at review-tools/scripts/api_review_validator_v0_6.py`

1. **Verify tooling repository**: Ensure scripts exist in `camaraproject/tooling/scripts/`
2. **Check workflow reference**: Confirm trigger workflow uses correct path to reusable workflow
3. **Verify file location**: Script must be in `/scripts/` directory of tooling repository
4. **Check permissions**: Ensure workflow has read access to tooling repository

### Version Support Issues

#### "❌ Unsupported Commonalities Version"
Currently, only Commonalities 0.6 is supported. If you see an error like:

```
❌ Commonalities 0.7 is not yet supported
```

**Solution:** Use `commonalities_version: 0.6` for all reviews.

### No Results Posted

If results aren't posted to the issue:
1. Check workflow permissions for issue write access
2. Verify the issue number is correctly captured
3. Check Actions logs for error messages
4. Ensure the workflow completed successfully

### Comment Trigger Issues

#### "No valid CAMARA PR URL found in lines 3-4 of issue description"
- Ensure the PR URL is on line 3 or 4 of the issue description
- URL must start with `https://github.com/camaraproject/`
- URL must follow exact format: `https://github.com/camaraproject/[repo]/pull/[number]`
- Check for extra characters or formatting

**Example of correct format:**
```markdown
Line 1: # Release Review Title
Line 2: 
Line 3: https://github.com/camaraproject/QualityOnDemand/pull/456
Line 4: 
```

#### "Comment does not start with '/rc-api-review' or '/wip-api-review'"
- Ensure the comment starts exactly with `/rc-api-review` or `/wip-api-review`
- Case sensitive - must be lowercase
- No spaces before the command
- Additional text after the command is allowed

#### No Response from Bot
- Check that the comment was posted in the correct repository
- Verify GitHub Actions are enabled in the repository
- Check workflow permissions in repository settings
- Look for workflow runs in the Actions tab

### Manual Trigger Issues

#### "Invalid PR URL format"
- Ensure URL follows exact format: `https://github.com/owner/repo/pull/123`
- No trailing slashes or query parameters
- Must be from camaraproject organization

#### "Repository must be from camaraproject organization"
- URL must start with `https://github.com/camaraproject/`
- Verify the repository name is correct

### Common Issues (Both Methods)

#### "PR is not open or does not exist"
- Verify the PR number is correct
- Ensure the PR is still open
- Check repository name spelling

#### "No API definition files found"
- Verify files are in `/code/API_definitions/`
- Ensure files have `.yaml` or `.yml` extensions
- Check the PR branch has the expected file structure

#### "Workflow failed"
- Check the Actions logs for specific error messages
- Verify GitHub token permissions
- Ensure target repository is accessible
- **Most common**: Check if the Python validation script exists

### Debug Steps

#### For Version-Specific Issues
1. **Verify script exists**: Check `scripts/api_review_validator_v0_6.py` in tooling repository
2. **Check workflow logs**: Look for the "Locate Version-Specific API Validator Script" step
3. **Verify version support**: Ensure you're using Commonalities 0.6
4. **Check version validation**: Look for "Validate Commonalities Version Support" step

#### For Comment Triggers
1. Check if the comment appears in the issue
2. Look for workflow runs in Actions
3. Search for runs triggered by "issue_comment"
4. Review the "check-comment-trigger" job logs

#### For Manual Triggers
1. Go to Actions tab
2. Find the manually triggered workflow run
3. Review the "validate-input" job logs
4. Check PR URL parsing and validation steps

#### For Both Methods
1. Verify the target PR exists and is open
2. Check that API files exist in `/code/API_definitions/`
3. Review the detailed validation logs in the "api-review" job
4. Download workflow artifacts if available
5. **Always check**: Ensure version-specific validator script exists in tooling repository

## Best Practices

1. **Deploy Strategically**: 
   - Use ReleaseManagement for formal release reviews
   - Deploy in API repositories for continuous PR validation
2. **Version Alignment**: Specify commonalities version 0.6 for all reviews
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

## Limitations

1. **File Location**: Only checks standard CAMARA directories (`/code/API_definitions/`)
2. **Cross-file References**: Limited validation of external references
3. **Business Logic**: Cannot validate API design appropriateness
4. **Real-time Data**: No validation against external systems or live endpoints
5. **Language Support**: Currently focused on YAML/OpenAPI definitions only
6. **Version Support**: Currently limited to Commonalities 0.6 only

## Support and Feedback

For issues with the workflow system:
1. **Check version compatibility**: Verify you're using Commonalities 0.6
2. **Check script location**: Verify `scripts/api_review_validator_v0_6.py` exists in tooling repository
3. **Check the GitHub Actions logs** for detailed error information
4. **Review this usage guide** for common troubleshooting steps
5. **Create an issue** in the `tooling` repository with:
   - Workflow run details
   - Commonalities version used
   - Error messages from logs
   - Expected vs. actual behavior

---

**Last Updated**: Based on architectural decisions and implementation analysis
**Current Version**: Supports Commonalities 0.6 validation
**Deployment Model**: Distributed architecture with centralized validation logic