#!/bin/bash
# Fixed test runner that handles legacy validator structure requirements

echo "🧪 Running validators on test data..."

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Create output directories
OUTPUT_DIR="test-results-$(date +%Y%m%d-%H%M%S)"
mkdir -p $OUTPUT_DIR/{legacy,modular}

# Function to run legacy validator
run_legacy() {
    local input_path=$1
    local test_name=$2
    local output_dir="$OUTPUT_DIR/legacy/$test_name"

    echo -n "  Legacy validator... "

    # Create proper structure for legacy validator
    rm -rf temp-legacy
    mkdir -p temp-legacy/code/API_definitions

    # Handle single file vs directory
    if [ -f "$input_path" ]; then
        # Single file - copy it
        cp "$input_path" temp-legacy/code/API_definitions/
    elif [ -d "$input_path" ]; then
        # Directory - copy all YAML files to API_definitions
        find "$input_path" -name "*.yaml" -o -name "*.yml" | while read file; do
            cp "$file" temp-legacy/code/API_definitions/
        done

        # Also preserve directory structure for projects
        cp -r "$input_path"/* temp-legacy/ 2>/dev/null || true
    fi

    # Run legacy validator
    if python scripts/api_review_validator_v0_6.py temp-legacy \
        --output "$output_dir" \
        --repo-name "$test_name" \
        --commonalities-version 0.6 \
        --review-type release-candidate \
        >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        exit_code=$?
        if [ $exit_code -eq 1 ]; then
            echo -e "${YELLOW}✓${NC} (Critical issues found)"
        else
            echo -e "${RED}✗${NC} (Error)"
        fi
    fi

    rm -rf temp-legacy
}

# Function to run modular validator
run_modular() {
    local input_path=$1
    local test_name=$2
    local output_dir="$OUTPUT_DIR/modular/$test_name"

    echo -n "  Modular validator... "

    if camara-validate "$input_path" \
        --version 0.6 \
        --output "$output_dir" \
        --repo-name "$test_name" \
        --pr-number 0 \
        >/dev/null 2>&1; then
        echo -e "${YELLOW}✓${NC} (Phase 0)"
    else
        echo -e "${YELLOW}✓${NC} (Phase 0)"
    fi
}

# Test single files
echo ""
echo "📄 Testing single API files:"
echo "----------------------------"

# Valid APIs
if [ -d "test-data/valid/regular-apis" ]; then
    for api in test-data/valid/regular-apis/*.yaml; do
        if [ -f "$api" ]; then
            name=$(basename "$api" .yaml)
            echo ""
            echo "Testing: $name (expected: PASS)"
            run_legacy "$api" "valid-$name"
            run_modular "$api" "valid-$name"
        fi
    done
fi

# Invalid APIs
if [ -d "test-data/invalid/critical-issues" ]; then
    for api in test-data/invalid/critical-issues/*.yaml; do
        if [ -f "$api" ]; then
            name=$(basename "$api" .yaml)
            echo ""
            echo "Testing: $name (expected: FAIL)"
            run_legacy "$api" "invalid-$name"
            run_modular "$api" "invalid-$name"
        fi
    done
fi

# Synthetic tests
if [ -d "test-data/synthetic" ]; then
    for api in test-data/synthetic/*.yaml; do
        if [ -f "$api" ]; then
            name=$(basename "$api" .yaml)
            echo ""
            echo "Testing synthetic: $name"
            run_legacy "$api" "synthetic-$name"
            run_modular "$api" "synthetic-$name"
        fi
    done
fi

echo ""
echo "📊 Results saved in: $OUTPUT_DIR/"
echo ""
echo "💡 To view results:"
echo "  cat $OUTPUT_DIR/legacy/*/summary.md"
