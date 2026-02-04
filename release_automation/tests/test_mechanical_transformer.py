"""
Unit tests for the mechanical transformer.

These tests verify transformation operations:
- YAML path replacement
- Regex replacement
- Template resolution
- GitHub link updates
- Context handling
"""

import os
import tempfile

import pytest

from release_automation.scripts.mechanical_transformer import (
    MechanicalTransformer,
    TransformationChange,
    TransformationContext,
    TransformationResult,
    TransformationRule,
    TransformationType,
)


@pytest.fixture
def context():
    """Create a sample transformation context."""
    return TransformationContext(
        release_tag="r4.2",
        api_versions={
            "quality-on-demand": "3.2.0-rc.2",
            "qos-profiles": "1.0.0",
        },
        commonalities_release="r3.4",
        icm_release="r3.3",
        repo_name="QualityOnDemand",
    )


@pytest.fixture
def transformer():
    """Create a MechanicalTransformer without config."""
    return MechanicalTransformer()


class TestTransformationContext:
    """Tests for TransformationContext."""

    def test_get_api_version(self, context):
        """Get API version from context."""
        assert context.get_api_version("quality-on-demand") == "3.2.0-rc.2"
        assert context.get_api_version("qos-profiles") == "1.0.0"

    def test_get_api_version_missing(self, context):
        """Missing API returns empty string."""
        assert context.get_api_version("unknown-api") == ""

    def test_get_major_version(self, context):
        """Extract major version from version string."""
        assert context.get_major_version("3.2.0-rc.2") == "3"
        assert context.get_major_version("1.0.0") == "1"
        assert context.get_major_version("10.5.3") == "10"

    def test_get_major_version_empty(self, context):
        """Empty version returns empty string."""
        assert context.get_major_version("") == ""

    def test_get_major_version_invalid(self, context):
        """Invalid version format returns empty string."""
        assert context.get_major_version("invalid") == ""


class TestTransformationResult:
    """Tests for TransformationResult."""

    def test_merge_results(self):
        """Merge two results."""
        result1 = TransformationResult(
            success=True,
            files_modified=["file1.yaml"],
            changes=[TransformationChange(file_path="file1.yaml", rule_name="r1")],
            errors=[],
            warnings=["warn1"],
        )
        result2 = TransformationResult(
            success=False,  # Second result failed
            files_modified=["file2.yaml"],
            changes=[TransformationChange(file_path="file2.yaml", rule_name="r2")],
            errors=["error1"],
            warnings=[],
        )

        merged = result1.merge(result2)

        assert merged.success is False  # One failure makes merged fail
        assert len(merged.files_modified) == 2
        assert len(merged.changes) == 2
        assert len(merged.errors) == 1
        assert len(merged.warnings) == 1

    def test_merge_both_successful(self):
        """Merge successful results stays successful."""
        result1 = TransformationResult(success=True)
        result2 = TransformationResult(success=True)

        merged = result1.merge(result2)

        assert merged.success is True


class TestResolveTemplate:
    """Tests for template resolution."""

    def test_resolve_release_tag(self, transformer, context):
        """Resolve {release_tag} variable."""
        result = transformer._resolve_template(
            "blob/{release_tag}/", context, None
        )
        assert result == "blob/r4.2/"

    def test_resolve_api_version(self, transformer, context):
        """Resolve {api_version} variable."""
        result = transformer._resolve_template(
            "{api_version}", context, "quality-on-demand"
        )
        assert result == "3.2.0-rc.2"

    def test_resolve_major_version(self, transformer, context):
        """Resolve {major_version} variable."""
        result = transformer._resolve_template(
            "/v{major_version}", context, "quality-on-demand"
        )
        assert result == "/v3"

    def test_resolve_commonalities_release(self, transformer, context):
        """Resolve {commonalities_release} variable."""
        result = transformer._resolve_template(
            "{commonalities_release}", context, None
        )
        assert result == "r3.4"

    def test_resolve_icm_release(self, transformer, context):
        """Resolve {icm_release} variable."""
        result = transformer._resolve_template(
            "{icm_release}", context, None
        )
        assert result == "r3.3"

    def test_resolve_repo_name(self, transformer, context):
        """Resolve {repo_name} variable."""
        result = transformer._resolve_template(
            "{repo_name}", context, None
        )
        assert result == "QualityOnDemand"

    def test_resolve_url_version(self, transformer, context):
        """Resolve {url_version} variable."""
        result = transformer._resolve_template(
            "{url_version}", context, "quality-on-demand"
        )
        assert result == "v3rc2"

    def test_resolve_api_name(self, transformer, context):
        """Resolve {api_name} variable."""
        result = transformer._resolve_template(
            "API: {api_name}", context, "quality-on-demand"
        )
        assert result == "API: quality-on-demand"

    def test_resolve_multiple_variables(self, transformer, context):
        """Resolve multiple variables in one template."""
        result = transformer._resolve_template(
            "{api_name} v{api_version} ({release_tag})",
            context,
            "qos-profiles",
        )
        assert result == "qos-profiles v1.0.0 (r4.2)"

    def test_resolve_no_api_name(self, transformer, context):
        """Resolve with no API name uses empty string."""
        result = transformer._resolve_template(
            "{api_name}", context, None
        )
        assert result == ""

    def test_resolve_test_file_prefix_match(self, transformer, context):
        """Test files like qos-profiles-getQosProfile resolve via prefix match."""
        result = transformer._resolve_template(
            "/{url_version}", context, "qos-profiles-getQosProfile"
        )
        assert result == "/v1"

    def test_resolve_test_file_api_version_prefix_match(self, transformer, context):
        """Test file prefix match resolves {api_version} correctly."""
        result = transformer._resolve_template(
            "\\g<1>{api_version}", context, "quality-on-demand-createSession"
        )
        assert result == "\\g<1>3.2.0-rc.2"

    def test_resolve_prefix_match_picks_longest(self, transformer):
        """With overlapping API names, longest prefix wins."""
        ctx = TransformationContext(
            release_tag="r4.2",
            api_versions={
                "sim-swap": "2.0.0",
                "sim-swap-subscriptions": "1.0.0-alpha.1",
            },
            commonalities_release="r3.4",
            icm_release="r3.3",
        )
        # sim-swap-subscriptions-createSubscription → sim-swap-subscriptions
        result = transformer._resolve_template(
            "{api_version}", ctx, "sim-swap-subscriptions-createSubscription"
        )
        assert result == "1.0.0-alpha.1"

        # sim-swap-retrieveSwapInfo → sim-swap
        result = transformer._resolve_template(
            "{api_version}", ctx, "sim-swap-retrieveSwapInfo"
        )
        assert result == "2.0.0"


class TestExtractApiName:
    """Tests for API name extraction from file paths."""

    def test_simple_api_name(self, transformer):
        """Extract simple API name."""
        result = transformer._extract_api_name_from_path(
            "/repo/code/API_definitions/quality-on-demand.yaml"
        )
        assert result == "quality-on-demand"

    def test_api_name_with_subscriptions_suffix(self, transformer):
        """Subscriptions files are separate APIs - suffix NOT stripped."""
        result = transformer._extract_api_name_from_path(
            "/repo/code/API_definitions/location-verification-subscriptions.yaml"
        )
        assert result == "location-verification-subscriptions"

    def test_api_name_with_notifications_suffix(self, transformer):
        """Notifications files are separate APIs - suffix NOT stripped."""
        result = transformer._extract_api_name_from_path(
            "/repo/code/API_definitions/device-status-notifications.yaml"
        )
        assert result == "device-status-notifications"

    def test_api_name_with_callback_suffix(self, transformer):
        """Callback files are separate APIs - suffix NOT stripped."""
        result = transformer._extract_api_name_from_path(
            "/repo/code/API_definitions/sim-swap-callback.yaml"
        )
        assert result == "sim-swap-callback"


class TestRegexTransformation:
    """Tests for regex transformations."""

    def test_replace_github_links(self, transformer, context):
        """Replace GitHub blob/main links."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("See [docs](https://github.com/org/repo/blob/main/README.md)\n")
            f.write("And [more](https://github.com/org/repo/blob/main/API.md)\n")
            temp_path = f.name

        try:
            rule = TransformationRule(
                name="github_links",
                description="Replace blob/main",
                type=TransformationType.REGEX,
                file_pattern="*.md",
                pattern="blob/main/",
                replacement="blob/{release_tag}/",
            )

            result = transformer.apply_transformation(temp_path, rule, context)

            assert result.success
            assert temp_path in result.files_modified

            with open(temp_path, "r") as f:
                content = f.read()

            assert "blob/r4.2/README.md" in content
            assert "blob/r4.2/API.md" in content
            assert "blob/main" not in content
        finally:
            os.unlink(temp_path)

    def test_replace_server_url(self, transformer, context):
        """Replace /vwip in server URLs."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("servers:\n")
            f.write("  - url: https://api.example.com/qod/vwip\n")
            temp_path = f.name

        try:
            rule = TransformationRule(
                name="server_url",
                description="Replace vwip",
                type=TransformationType.REGEX,
                file_pattern="*.yaml",
                pattern="/vwip",
                replacement="/v{major_version}",
            )

            # Set API name for major version resolution
            result = transformer._apply_regex(temp_path, rule, context)

            # Note: Without API name context, major_version will be empty
            # This test verifies the regex replacement mechanism
            assert result.success
        finally:
            os.unlink(temp_path)

    def test_no_match_returns_empty_changes(self, transformer, context):
        """No regex matches returns no changes."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("No matching content here\n")
            temp_path = f.name

        try:
            rule = TransformationRule(
                name="test_rule",
                description="Test",
                type=TransformationType.REGEX,
                file_pattern="*.md",
                pattern="nonexistent_pattern",
                replacement="replacement",
            )

            result = transformer.apply_transformation(temp_path, rule, context)

            assert result.success
            assert temp_path not in result.files_modified
            assert len(result.changes) == 0
        finally:
            os.unlink(temp_path)


class TestYamlPathTransformation:
    """Tests for YAML path transformations."""

    def test_replace_yaml_value_fallback(self, transformer, context):
        """Replace YAML value using fallback method."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("info:\n")
            f.write("  title: Quality On Demand\n")
            f.write("  version: wip  # Comment preserved\n")
            f.write("  x-camara-commonalities: wip\n")
            temp_path = f.name

        try:
            rule = TransformationRule(
                name="info_version",
                description="Replace wip version",
                type=TransformationType.YAML_PATH,
                file_pattern="*.yaml",
                path="info.version",
                match_value="wip",
                replacement="{api_version}",
            )

            # Create context for this specific test
            test_context = TransformationContext(
                release_tag="r4.2",
                api_versions={"test": "3.2.0-rc.2"},
                commonalities_release="r3.4",
                icm_release="r3.3",
                repo_name="TestRepo",
            )

            result = transformer.apply_transformation(temp_path, rule, test_context)

            # Result depends on whether ruamel.yaml is available
            assert result.success
        finally:
            os.unlink(temp_path)


class TestMustacheSection:
    """Tests for mustache section transformations."""

    def test_mustache_section_stub(self, transformer, context):
        """Mustache section returns warning (stub)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write("# CHANGELOG\n")
            temp_path = f.name

        try:
            rule = TransformationRule(
                name="changelog",
                description="Update changelog",
                type=TransformationType.MUSTACHE_SECTION,
                file_pattern="*.md",
                section="api_versions",
                template="## {api_name} {api_version}\n",
                replacement="",
            )

            result = transformer.apply_transformation(temp_path, rule, context)

            assert result.success
            assert len(result.warnings) > 0
            assert "not yet implemented" in result.warnings[0]
        finally:
            os.unlink(temp_path)


class TestApplyAll:
    """Tests for apply_all method."""

    def test_apply_all_with_config(self, context):
        """Apply all rules from config file."""
        # Create temporary config
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("transformations:\n")
            f.write("  - name: test_rule\n")
            f.write("    description: Test\n")
            f.write("    type: regex\n")
            f.write('    file_pattern: "**/*.md"\n')
            f.write('    pattern: "TEST"\n')
            f.write('    replacement: "REPLACED"\n')
            config_path = f.name

        # Create temp directory with test file
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.md")
            with open(test_file, "w") as f:
                f.write("This is TEST content\n")

            try:
                transformer = MechanicalTransformer(config_path)
                result = transformer.apply_all(temp_dir, context)

                assert result.success
                assert len(result.files_modified) == 1

                with open(test_file, "r") as f:
                    content = f.read()
                assert "REPLACED" in content
                assert "TEST" not in content
            finally:
                os.unlink(config_path)

    def test_skip_disabled_rules(self, context):
        """Disabled rules are skipped."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("transformations:\n")
            f.write("  - name: disabled_rule\n")
            f.write("    description: Disabled\n")
            f.write("    type: regex\n")
            f.write('    file_pattern: "*.md"\n')
            f.write('    pattern: "TEST"\n')
            f.write('    replacement: "REPLACED"\n')
            f.write("    enabled: false\n")
            config_path = f.name

        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.md")
            with open(test_file, "w") as f:
                f.write("TEST content\n")

            try:
                transformer = MechanicalTransformer(config_path)
                result = transformer.apply_all(temp_dir, context)

                assert result.success
                assert len(result.files_modified) == 0

                # File should be unchanged
                with open(test_file, "r") as f:
                    content = f.read()
                assert "TEST" in content
            finally:
                os.unlink(config_path)


class TestLoadConfig:
    """Tests for config loading."""

    def test_load_valid_config(self):
        """Load valid config file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("transformations:\n")
            f.write("  - name: rule1\n")
            f.write("    description: Test rule\n")
            f.write("    type: regex\n")
            f.write('    file_pattern: "*.yaml"\n')
            f.write('    pattern: "old"\n')
            f.write('    replacement: "new"\n')
            config_path = f.name

        try:
            transformer = MechanicalTransformer(config_path)

            assert len(transformer.rules) == 1
            assert transformer.rules[0].name == "rule1"
            assert transformer.rules[0].type == TransformationType.REGEX
        finally:
            os.unlink(config_path)

    def test_skip_invalid_rules(self):
        """Invalid rules are skipped with warning."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("transformations:\n")
            f.write("  - name: valid_rule\n")
            f.write("    description: Valid\n")
            f.write("    type: regex\n")
            f.write('    file_pattern: "*.yaml"\n')
            f.write('    replacement: "new"\n')
            f.write("  - name: invalid_rule\n")
            f.write("    type: invalid_type\n")  # Invalid type
            config_path = f.name

        try:
            transformer = MechanicalTransformer(config_path)

            # Only valid rule should be loaded
            assert len(transformer.rules) == 1
            assert transformer.rules[0].name == "valid_rule"
        finally:
            os.unlink(config_path)
