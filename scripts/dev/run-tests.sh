#!/bin/bash
# Run tests for CAMARA validator

set -e

echo "🧪 Running CAMARA Validator tests..."

# Activate virtual environment if not already active
if [[ -z "$VIRTUAL_ENV" ]]; then
    source venv/bin/activate
fi

# Run unit tests
echo "🧪 Running unit tests..."
pytest scripts/camara-validator/tests/unit -v

# Run integration tests
echo "🧪 Running integration tests..."
pytest scripts/camara-validator/tests/integration -v

# Generate coverage report
echo "📊 Generating coverage report..."
pytest scripts/camara-validator/tests --cov=camara_validator --cov-report=html --cov-report=term

echo "✅ All tests passed!"
echo "📊 Coverage report available at: htmlcov/index.html"
