# CAMARA Validator Test Data

This directory contains test data for validating the CAMARA validator implementation.

## Structure

- `valid/` - APIs that should pass validation
  - `regular-apis/` - Standard CAMARA APIs
  - `subscription-apis/` - APIs with subscription patterns
  - `edge-cases/` - Complex but valid APIs

- `invalid/` - APIs with known issues
  - `critical-issues/` - APIs with critical validation failures
  - `medium-issues/` - APIs with medium severity issues
  - `low-issues/` - APIs with minor issues

- `projects/` - Multi-file test projects
  - `multi-api-project/` - Multiple related APIs
  - `with-tests/` - APIs with test definitions
  - `mixed-versions/` - APIs with different versions

- `synthetic/` - Artificially created test cases
- `historical/` - Test cases from historical issues
- `from-camara/` - APIs collected from CAMARA repositories

## Usage

Run validators on test data:
```bash
# Test single file
camara-validate test-data/valid/regular-apis/simple-api.yaml

# Test entire category
camara-validate test-data/valid --recursive

# Compare validators
python scripts/compare_validators.py test-data/
```
