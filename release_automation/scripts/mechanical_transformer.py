"""
Mechanical transformer for CAMARA release automation.

This module applies automated placeholder replacements to release branches.
Transformations include YAML path modifications, regex replacements, and
template insertions.

Requires: ruamel.yaml>=0.18.0 for YAML round-trip preservation
"""

import glob
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Try to import ruamel.yaml for round-trip YAML preservation
try:
    from ruamel.yaml import YAML

    RUAMEL_AVAILABLE = True
except ImportError:
    RUAMEL_AVAILABLE = False


class TransformationType(Enum):
    """Types of transformations supported."""

    YAML_PATH = "yaml_path"
    REGEX = "regex"
    MUSTACHE_SECTION = "mustache_section"


@dataclass
class TransformationRule:
    """A single transformation rule from config."""

    name: str
    description: str
    type: TransformationType
    file_pattern: str
    replacement: str
    path: Optional[str] = None  # For yaml_path
    match_value: Optional[str] = None  # For yaml_path
    pattern: Optional[str] = None  # For regex
    section: Optional[str] = None  # For mustache_section
    template: Optional[str] = None  # For mustache_section
    enabled: bool = True


@dataclass
class TransformationChange:
    """Record of a single change made."""

    file_path: str
    rule_name: str
    line_number: Optional[int] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None


@dataclass
class TransformationContext:
    """Context for resolving transformation templates."""

    release_tag: str
    api_versions: Dict[str, str]
    commonalities_release: str  # Release tag, e.g., "r3.4"
    icm_release: str  # Release tag, e.g., "r3.3"
    repo_name: str = ""  # Repository name, e.g., "QualityOnDemand"
    release_plan: Dict[str, Any] = field(default_factory=dict)

    def get_api_version(self, api_name: str) -> str:
        """Get version for a specific API."""
        return self.api_versions.get(api_name, "")

    def get_major_version(self, version: str) -> str:
        """Extract major version from version string."""
        if not version:
            return ""
        match = re.match(r"^(\d+)\.", version)
        return match.group(1) if match else ""


@dataclass
class TransformationResult:
    """Result of transformation operations."""

    success: bool
    files_modified: List[str] = field(default_factory=list)
    changes: List[TransformationChange] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def merge(self, other: "TransformationResult") -> "TransformationResult":
        """Merge another result into this one."""
        return TransformationResult(
            success=self.success and other.success,
            files_modified=self.files_modified + other.files_modified,
            changes=self.changes + other.changes,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


class MechanicalTransformer:
    """
    Apply mechanical transformations to release branch files.

    Supports three transformation types:
    - yaml_path: Modify specific YAML paths preserving structure
    - regex: Pattern replacement with template variables
    - mustache_section: Template insertion (stub for future)
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize transformer with configuration.

        Args:
            config_path: Path to transformations.yaml config file.
                        If None, uses default config location.
        """
        self.rules: List[TransformationRule] = []
        if config_path:
            self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        """Load transformation rules from config file."""
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        for rule_data in config.get("transformations", []):
            try:
                rule = TransformationRule(
                    name=rule_data["name"],
                    description=rule_data.get("description", ""),
                    type=TransformationType(rule_data["type"]),
                    file_pattern=rule_data.get("file_pattern", ""),
                    replacement=rule_data.get("replacement", ""),
                    path=rule_data.get("path"),
                    match_value=rule_data.get("match_value"),
                    pattern=rule_data.get("pattern"),
                    section=rule_data.get("section"),
                    template=rule_data.get("template"),
                    enabled=rule_data.get("enabled", True),
                )
                self.rules.append(rule)
            except (KeyError, ValueError) as e:
                print(f"Warning: Skipping invalid rule: {e}")

    def apply_all(
        self,
        repo_path: str,
        context: TransformationContext,
    ) -> TransformationResult:
        """
        Apply all enabled transformations to repository.

        Args:
            repo_path: Path to repository root
            context: Transformation context with variables

        Returns:
            TransformationResult with all changes and any errors
        """
        result = TransformationResult(success=True)

        for rule in self.rules:
            if not rule.enabled:
                continue

            rule_result = self._apply_rule(repo_path, rule, context)
            result = result.merge(rule_result)

        return result

    def _apply_rule(
        self,
        repo_path: str,
        rule: TransformationRule,
        context: TransformationContext,
    ) -> TransformationResult:
        """Apply a single transformation rule to matching files."""
        result = TransformationResult(success=True)

        if not rule.file_pattern:
            return result

        # Find matching files
        pattern = os.path.join(repo_path, rule.file_pattern)
        files = glob.glob(pattern, recursive=True)

        for file_path in files:
            try:
                file_result = self.apply_transformation(file_path, rule, context)
                result = result.merge(file_result)
            except Exception as e:
                result.errors.append(f"Error processing {file_path}: {e}")
                result.success = False

        return result

    def apply_transformation(
        self,
        file_path: str,
        rule: TransformationRule,
        context: TransformationContext,
    ) -> TransformationResult:
        """
        Apply a transformation to a single file.

        Args:
            file_path: Path to file to transform
            rule: Transformation rule to apply
            context: Context for template resolution

        Returns:
            TransformationResult for this file
        """
        if rule.type == TransformationType.YAML_PATH:
            return self._apply_yaml_path(file_path, rule, context)
        elif rule.type == TransformationType.REGEX:
            return self._apply_regex(file_path, rule, context)
        elif rule.type == TransformationType.MUSTACHE_SECTION:
            return self._apply_mustache_section(file_path, rule, context)
        else:
            return TransformationResult(
                success=False, errors=[f"Unknown transformation type: {rule.type}"]
            )

    def _apply_yaml_path(
        self,
        file_path: str,
        rule: TransformationRule,
        context: TransformationContext,
    ) -> TransformationResult:
        """
        Apply YAML path transformation.

        Uses ruamel.yaml for round-trip preservation if available,
        otherwise falls back to simple text replacement.
        """
        result = TransformationResult(success=True)

        if not rule.path:
            result.warnings.append(f"No path specified for rule {rule.name}")
            return result

        # Extract API name from file path for context
        api_name = self._extract_api_name_from_path(file_path)

        # Resolve replacement template
        replacement_value = self._resolve_template(
            rule.replacement, context, api_name
        )

        if RUAMEL_AVAILABLE:
            result = self._apply_yaml_path_ruamel(
                file_path, rule, replacement_value, result
            )
        else:
            result = self._apply_yaml_path_fallback(
                file_path, rule, replacement_value, result
            )

        return result

    def _apply_yaml_path_ruamel(
        self,
        file_path: str,
        rule: TransformationRule,
        replacement_value: str,
        result: TransformationResult,
    ) -> TransformationResult:
        """Apply YAML path using ruamel.yaml for round-trip preservation."""
        yaml_handler = YAML()
        yaml_handler.preserve_quotes = True

        with open(file_path, "r") as f:
            data = yaml_handler.load(f)

        # Navigate to the path
        path_parts = rule.path.split(".")
        current = data
        parent = None
        last_key = None

        for part in path_parts:
            if current is None:
                result.warnings.append(
                    f"Path {rule.path} not found in {file_path}"
                )
                return result
            parent = current
            last_key = part
            current = current.get(part) if isinstance(current, dict) else None

        # Check if value matches expected
        if rule.match_value and current != rule.match_value:
            return result  # No change needed

        # Apply replacement
        if parent is not None and last_key is not None:
            old_value = parent.get(last_key)
            parent[last_key] = replacement_value

            with open(file_path, "w") as f:
                yaml_handler.dump(data, f)

            result.files_modified.append(file_path)
            result.changes.append(
                TransformationChange(
                    file_path=file_path,
                    rule_name=rule.name,
                    old_value=str(old_value) if old_value else None,
                    new_value=replacement_value,
                )
            )

        return result

    def _apply_yaml_path_fallback(
        self,
        file_path: str,
        rule: TransformationRule,
        replacement_value: str,
        result: TransformationResult,
    ) -> TransformationResult:
        """
        Fallback YAML path replacement using text manipulation.

        This preserves comments but only works for simple key: value patterns.
        """
        with open(file_path, "r") as f:
            content = f.read()

        # Get the last key in the path
        path_parts = rule.path.split(".")
        last_key = path_parts[-1]

        # Build pattern to match the key-value pair
        if rule.match_value:
            pattern = rf"^(\s*{re.escape(last_key)}:\s*){re.escape(rule.match_value)}(\s*(?:#.*)?)$"
            replacement = rf"\g<1>{replacement_value}\2"
        else:
            # Match any value for this key
            pattern = rf"^(\s*{re.escape(last_key)}:\s*)(\S+)(\s*(?:#.*)?)$"
            replacement = rf"\g<1>{replacement_value}\3"

        new_content, count = re.subn(
            pattern, replacement, content, flags=re.MULTILINE
        )

        if count > 0:
            with open(file_path, "w") as f:
                f.write(new_content)

            result.files_modified.append(file_path)
            result.changes.append(
                TransformationChange(
                    file_path=file_path,
                    rule_name=rule.name,
                    old_value=rule.match_value,
                    new_value=replacement_value,
                )
            )
        else:
            result.warnings.append(
                f"No match for {rule.name} in {file_path} "
                "(ruamel.yaml not available for precise path matching)"
            )

        return result

    def _apply_regex(
        self,
        file_path: str,
        rule: TransformationRule,
        context: TransformationContext,
    ) -> TransformationResult:
        """Apply regex transformation."""
        result = TransformationResult(success=True)

        if not rule.pattern:
            result.warnings.append(f"No pattern specified for rule {rule.name}")
            return result

        # Extract API name from file path for context
        api_name = self._extract_api_name_from_path(file_path)

        # Resolve pattern and replacement templates
        pattern = self._resolve_template(rule.pattern, context, api_name)
        replacement = self._resolve_template(rule.replacement, context, api_name)

        with open(file_path, "r") as f:
            content = f.read()

        # Apply regex replacement
        new_content, count = re.subn(pattern, replacement, content)

        if count > 0:
            with open(file_path, "w") as f:
                f.write(new_content)

            result.files_modified.append(file_path)
            result.changes.append(
                TransformationChange(
                    file_path=file_path,
                    rule_name=rule.name,
                    old_value=f"({count} occurrences)",
                    new_value=replacement,
                )
            )

        return result

    def _apply_mustache_section(
        self,
        file_path: str,
        rule: TransformationRule,
        context: TransformationContext,
    ) -> TransformationResult:
        """
        Apply mustache section transformation (stub).

        This is a placeholder for future template insertion functionality.
        """
        result = TransformationResult(success=True)
        result.warnings.append(
            f"Mustache section transformation not yet implemented: {rule.name}"
        )
        return result

    def _resolve_template(
        self,
        template: str,
        context: TransformationContext,
        api_name: Optional[str] = None,
    ) -> str:
        """
        Resolve template variables in a string.

        Supported variables:
        - {release_tag}
        - {api_version}
        - {url_version} - URL path version per CAMARA API Design Guide
        - {major_version}
        - {repo_name}
        - {commonalities_release}
        - {icm_release}
        - {api_name}

        Args:
            template: Template string with {variable} placeholders
            context: Context with variable values
            api_name: API name for API-specific variables

        Returns:
            Resolved string with variables replaced
        """
        from .version_calculator import calculate_url_version

        result = template

        # Get API-specific values
        api_version = ""
        major_version = ""
        url_version = ""
        if api_name:
            api_version = context.get_api_version(api_name)
            # For test files like "qos-profiles-getQosProfile", the filename
            # doesn't match an API name directly. Find the longest API name
            # that is a prefix of the filename (e.g., "qos-profiles").
            if not api_version:
                matching = [
                    k for k in context.api_versions
                    if api_name.startswith(k + "-") or api_name.startswith(k + "_")
                ]
                if matching:
                    best = max(matching, key=len)
                    api_version = context.api_versions[best]
                    api_name = best
            major_version = context.get_major_version(api_version)
            url_version = calculate_url_version(api_version) if api_version else ""

        # Replace variables
        replacements = {
            "{release_tag}": context.release_tag,
            "{api_version}": api_version,
            "{url_version}": url_version,
            "{major_version}": major_version,
            "{repo_name}": context.repo_name,
            "{commonalities_release}": context.commonalities_release,
            "{icm_release}": context.icm_release,
            "{api_name}": api_name or "",
        }

        for var, value in replacements.items():
            result = result.replace(var, value)

        return result

    def _extract_api_name_from_path(self, file_path: str) -> Optional[str]:
        """
        Extract API name from file path.

        Simply returns the filename without extension. Files like
        location-verification-subscriptions.yaml are separate APIs with
        their own version tracking in release-plan.yaml, not auxiliary files.

        Args:
            file_path: Path to API file

        Returns:
            API name or None if not extractable
        """
        filename = Path(file_path).stem  # Remove extension
        return filename if filename else None
