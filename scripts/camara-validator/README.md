# CAMARA Validator

A modular, extensible validation tool for CAMARA API specifications.

## Features

- 🔍 **Comprehensive Validation**: Validates CAMARA APIs against Commonalities specifications
- 🧩 **Modular Architecture**: Rule-based validation system for easy extension
- 🚀 **Performance**: Optimized for fast validation of multiple APIs
- 📊 **Detailed Reporting**: Markdown and GitHub-compatible output formats
- 🔧 **Extensible**: Easy to add new validation rules and Commonalities versions
- 🧪 **Well-Tested**: Comprehensive test suite with >85% coverage

## Installation

### From Source (Development)

```bash
git clone https://github.com/camaraproject/tooling.git
cd tooling/scripts/camara-validator
pip install -e .
```

### From Package

```bash
pip install ./scripts/camara-validator
```

## Usage

### Command Line Interface

```bash
# Basic usage
camara-validate /path/to/api/repo --version 0.6 --output ./reports

# Full options
camara-validate /path/to/api/repo \
  --version 0.6 \
  --output ./reports \
  --repo-name MyAPI \
  --pr-number 123 \
  --verbose
```

### Options

- `repo_path`: Path to repository containing API definitions (required)
- `--version`: CAMARA Commonalities version (default: 0.6)
- `--output`: Output directory for reports (required)
- `--repo-name`: Repository name for reporting
- `--pr-number`: Pull request number for context
- `--verbose`: Enable verbose logging

### Output

The validator generates two files:

1. **summary.md**: Brief summary suitable for GitHub comments
2. **api_review_*.md**: Detailed report with all findings

## Architecture

### Rule-Based Validation

The validator uses a rule-based architecture where each validation check is implemented as a separate rule:

```python
class MyRule(ValidationRule):
    def validate(self, context: ValidationContext, result: ValidationResult):
        # Validation logic here
        pass
```

### Validation Categories

- **Structure Rules**: OpenAPI structure, info object, servers
- **Security Rules**: Authentication, authorization, scopes
- **Error Rules**: Error responses, status codes, error schemas
- **Schema Rules**: Data models, common schemas, consistency
- **Subscription Rules**: Event subscriptions, notifications
- **Consistency Rules**: Cross-file validation, naming conventions

## Adding New Rules

1. Create a new rule class in `src/camara_validator/rules/`:

```python
from camara_validator.rules.base import ValidationRule

class MyNewRule(ValidationRule):
    @property
    def name(self) -> str:
        return "My New Rule"

    def validate(self, context, result):
        # Add validation logic
        pass
```

2. Register the rule in the appropriate config file:

```python
# config/v0_6.py
VALIDATION_RULES = [
    # ... existing rules
    MyNewRule(),
]
```

## API Types

The validator automatically detects and applies appropriate rules for different API types:

- **Regular APIs**: Standard CAMARA APIs
- **Explicit Subscription APIs**: APIs with `/subscriptions` endpoints
- **Implicit Subscription APIs**: APIs with callback mechanisms

## Performance

The modular architecture provides:
- Parallel rule execution capability
- Efficient YAML parsing with caching
- Minimal memory footprint
- Linear scaling with API count

## Testing

Run the test suite:

```bash
# All tests
pytest

# With coverage
pytest --cov=camara_validator

# Specific test file
pytest tests/unit/rules/test_security_rules.py
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

This project is licensed under the Apache License 2.0 - see the LICENSE file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/camaraproject/tooling/issues)
- **Wiki**: [CAMARA Wiki](https://github.com/camaraproject/tooling/wiki)
- **Community**: [CAMARA Project](https://camaraproject.org/)

## Roadmap

- [x] Phase 0: Infrastructure setup
- [ ] Phase 1: Package foundation
- [ ] Phase 2: Core rules migration
- [ ] Phase 3: Complete migration
- [ ] Phase 4: Selective rollout
- [ ] Phase 5: Full migration
- [ ] Future: Support for Commonalities 0.7+
