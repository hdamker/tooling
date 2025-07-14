# Contributing to CAMARA Validator

## Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/camaraproject/tooling.git
   cd tooling
   ```

2. **Run the setup script**:
   ```bash
   ./setup-dev-env.sh
   ```

3. **Activate the virtual environment**:
   ```bash
   source venv/bin/activate
   ```

## Project Structure

```
camara-validator/
├── src/camara_validator/     # Source code
│   ├── cli.py               # CLI entry point
│   ├── engine.py            # Validation engine
│   ├── models.py            # Data models
│   ├── config/              # Version configurations
│   ├── rules/               # Validation rules
│   └── reporting/           # Report generation
└── tests/                   # Test suite
    ├── unit/               # Unit tests
    ├── integration/        # Integration tests
    └── fixtures/           # Test data
```

## Development Workflow

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/my-new-rule
   ```

2. **Make your changes**:
   - Add new validation rules in `src/camara_validator/rules/`
   - Update tests in `tests/`
   - Update documentation

3. **Run tests**:
   ```bash
   ./scripts/dev/run-tests.sh
   ```

4. **Format code**:
   ```bash
   black scripts/camara-validator/src
   isort scripts/camara-validator/src
   ```

5. **Type check**:
   ```bash
   mypy scripts/camara-validator/src
   ```

6. **Commit with pre-commit hooks**:
   ```bash
   git add .
   git commit -m "feat: add new validation rule"
   ```

## Adding a New Validation Rule

1. Create a new rule class in `src/camara_validator/rules/`:

```python
from camara_validator.rules.base import ValidationRule
from camara_validator.models import ValidationContext, ValidationResult, ValidationIssue, Severity

class MyNewRule(ValidationRule):
    """Description of what this rule validates"""
    
    @property
    def name(self) -> str:
        return "My New Rule"
    
    @property
    def category(self) -> str:
        return "My Category"
    
    def applies_to(self, context: ValidationContext) -> bool:
        # Determine if this rule applies to the API
        return True
    
    def validate(self, context: ValidationContext, result: ValidationResult) -> None:
        # Implement validation logic
        if some_condition:
            result.issues.append(ValidationIssue(
                severity=Severity.CRITICAL,
                category=self.category,
                description="Description of the issue",
                location="path.to.problem",
                fix="How to fix it"
            ))
```

2. Register the rule in the appropriate config file (e.g., `config/v0_6.py`):

```python
from camara_validator.rules.my_new_rule import MyNewRule

VALIDATION_RULES = [
    # ... existing rules
    MyNewRule(),
]
```

3. Add tests for your rule in `tests/unit/rules/test_my_new_rule.py`

## Testing

### Unit Tests
Test individual rules and components:
```bash
pytest tests/unit/rules/test_my_new_rule.py -v
```

### Integration Tests
Test full validation flow:
```bash
pytest tests/integration/ -v
```

### Coverage
Generate coverage report:
```bash
pytest --cov=camara_validator --cov-report=html
```

## Performance Testing

Run the benchmark script to compare with legacy validator:
```bash
./scripts/dev/benchmark.py
```

## Code Style

- Follow PEP 8 with 100-character line limit
- Use type hints for all public APIs
- Write docstrings for all classes and functions
- Use meaningful variable names
- Keep functions small and focused

## Commit Messages

Follow conventional commits:
- `feat:` New features
- `fix:` Bug fixes
- `docs:` Documentation changes
- `test:` Test additions or changes
- `refactor:` Code refactoring
- `style:` Code style changes
- `perf:` Performance improvements
- `chore:` Maintenance tasks

## Questions?

If you have questions or need help:
1. Check existing issues in the repository
2. Create a new issue with your question
3. Join the CAMARA community discussions
