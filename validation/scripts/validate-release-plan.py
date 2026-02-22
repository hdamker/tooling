#!/usr/bin/env python3
"""
CAMARA Release Plan Validator

Validates release-plan.yaml files against JSON schema and semantic rules.

Usage:
    python3 validate-release-plan.py <release-plan-file> [--schema <schema-file>] [--check-files]

Examples:
    # Basic validation
    python3 validate-release-plan.py release-plan.yaml

    # Validate with explicit schema
    python3 validate-release-plan.py release-plan.yaml --schema ../schemas/release-plan-schema.yaml

    # Validate with file existence checks
    python3 validate-release-plan.py release-plan.yaml --check-files
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import yaml
except ImportError:
    print("Error: pyyaml package is required. Install with: pip install pyyaml")
    sys.exit(1)

try:
    import jsonschema
    from jsonschema import Draft7Validator, ValidationError
except ImportError:
    print("Error: jsonschema package is required. Install with: pip install jsonschema")
    sys.exit(1)


class ReleasePlanValidator:
    """Validator for CAMARA release-plan.yaml files."""

    # Allowed meta-release values (update as new meta-releases are added)
    ALLOWED_META_RELEASES = ['Fall25', 'Spring26', 'Fall26', 'Sync26', 'Signal27']

    def __init__(self, release_plan_file: Path, schema_file: Optional[Path] = None,
                 check_files: bool = False):
        self.release_plan_file = release_plan_file
        self.schema_file = schema_file
        self.check_files = check_files
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def load_yaml(self, file_path: Path) -> Dict[str, Any]:
        """Load and parse YAML file."""
        try:
            with open(file_path, 'r') as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            self.errors.append(f"YAML parsing error in {file_path}: {e}")
            return {}
        except FileNotFoundError:
            self.errors.append(f"File not found: {file_path}")
            return {}

    def find_schema_file(self) -> Optional[Path]:
        """Find schema file relative to script location."""
        script_dir = Path(__file__).parent
        schema_dir = script_dir.parent / 'schemas'
        schema_file = schema_dir / 'release-plan-schema.yaml'

        if schema_file.exists():
            return schema_file
        return None

    def validate_schema(self, release_plan: Dict[str, Any], schema: Dict[str, Any]) -> bool:
        """Validate release plan against JSON schema. Collects all errors."""
        validator = Draft7Validator(schema)
        errors_found = False

        for error in validator.iter_errors(release_plan):
            errors_found = True
            # Combine message and path into single error line
            if error.path:
                path_str = '.'.join(str(p) for p in error.path)
                self.errors.append(f"Schema validation error at '{path_str}': {error.message}")
            else:
                self.errors.append(f"Schema validation error: {error.message}")

        return not errors_found

    def check_semantic_rules(self, release_plan: Dict[str, Any]) -> None:
        """Check semantic rules beyond schema validation."""
        repo = release_plan.get('repository', {})
        apis = release_plan.get('apis', [])

        # Check release_track and meta_release consistency
        release_track = repo.get('release_track')
        meta_release = repo.get('meta_release')
        self._check_track_consistency(release_track, meta_release)

        # Check target release type consistency
        target_release_type = repo.get('target_release_type')
        if target_release_type:
            self._check_release_type_consistency(target_release_type, apis)

        # Check API status progression
        for api in apis:
            self._check_api_status(api)

    def _check_track_consistency(self, release_track: Optional[str], meta_release: Optional[str]) -> None:
        """Check that release_track and meta_release are consistent."""
        if release_track == 'meta-release' and not meta_release:
            self.errors.append(
                "release_track is 'meta-release' but meta_release field is missing"
            )
        elif release_track == 'independent' and meta_release:
            self.warnings.append(
                f"release_track is '{release_track}' but meta_release field is present"
            )

        # Validate meta_release value is in allowed list
        if meta_release and meta_release not in self.ALLOWED_META_RELEASES:
            self.errors.append(
                f"meta_release '{meta_release}' is not valid. "
                f"Allowed values: {', '.join(self.ALLOWED_META_RELEASES)}"
            )

    def _check_release_type_consistency(self, release_type: str, apis: List[Dict]) -> None:
        """Check that API statuses align with repository target release type.

        Rules:
        - none: No constraints (repository not targeting a release)
        - pre-release-alpha: All APIs must be at least alpha (no draft)
        - pre-release-rc: All APIs must be at least rc (no draft or alpha)
        - public-release: All APIs must be public
        - maintenance-release: All APIs must be public (can only patch released APIs)
        """
        # 'none' has no constraints - repository is not targeting a release
        if release_type == 'none':
            pass

        elif release_type == 'pre-release-alpha':
            # All APIs must be at least alpha (alpha, rc, or public)
            draft_apis = [api.get('api_name') for api in apis if api.get('target_api_status') == 'draft']
            if draft_apis:
                self.errors.append(
                    f"target_release_type is 'pre-release-alpha' but these APIs are 'draft': {', '.join(draft_apis)}"
                )

        elif release_type == 'pre-release-rc':
            # All APIs must be at least rc (rc or public)
            invalid_apis = [api.get('api_name') for api in apis
                           if api.get('target_api_status') in ['draft', 'alpha']]
            if invalid_apis:
                self.errors.append(
                    f"target_release_type is 'pre-release-rc' but these APIs are not rc/public: {', '.join(invalid_apis)}"
                )

        elif release_type == 'public-release':
            # All APIs must be public
            non_public = [api.get('api_name') for api in apis if api.get('target_api_status') != 'public']
            if non_public:
                self.errors.append(
                    f"target_release_type is 'public-release' but these APIs are not 'public': {', '.join(non_public)}"
                )

        elif release_type == 'maintenance-release':
            # Patch releases are for maintenance - all APIs should be public
            non_public = [api.get('api_name') for api in apis if api.get('target_api_status') != 'public']
            if non_public:
                self.errors.append(
                    f"target_release_type is 'maintenance-release' but these APIs are not 'public': {', '.join(non_public)}"
                )

    def _check_api_status(self, api: Dict) -> None:
        """Check individual API status consistency.

        Note: 0.x versions with 'public' status are valid - they represent
        initial public releases that are not yet stable (pre-1.0).
        The version number indicates API stability, not release status.
        """
        # Currently no per-API semantic checks beyond schema validation.
        # Future checks could include:
        # - Version format validation
        # - Status progression rules
        pass

    def check_file_existence(self, release_plan: Dict[str, Any]) -> None:
        """Check if referenced API definition files exist.

        Two-tier severity:
        - alpha/rc/public APIs: missing file is an ERROR (blocks PR)
        - draft APIs: missing file with orphan files triggers a WARNING
        """
        if not self.check_files:
            return

        apis = release_plan.get('apis', [])
        release_plan_dir = self.release_plan_file.parent
        api_definitions_dir = release_plan_dir / 'code' / 'API_definitions'

        # Collect all api_names declared in the release plan
        all_api_names = {api.get('api_name') for api in apis if api.get('api_name')}

        # Discover existing .yaml files in API_definitions (if directory exists)
        existing_file_stems: set = set()
        if api_definitions_dir.is_dir():
            existing_file_stems = {
                f.stem for f in api_definitions_dir.iterdir()
                if f.suffix == '.yaml' and f.is_file()
            }

        # Orphan files: exist in directory but not listed in release-plan.yaml
        orphan_files = existing_file_stems - all_api_names

        for api in apis:
            api_name = api.get('api_name')
            target_api_status = api.get('target_api_status')

            if not api_name:
                continue

            api_file = api_definitions_dir / f'{api_name}.yaml'
            file_exists = api_file.exists()

            if target_api_status in ('alpha', 'rc', 'public'):
                # Non-draft APIs MUST have a definition file
                if not file_exists:
                    self.errors.append(
                        f"API definition file not found for '{api_name}' "
                        f"(status: {target_api_status}). "
                        f"Expected: code/API_definitions/{api_name}.yaml"
                    )
            elif target_api_status == 'draft':
                # Draft APIs: warn about possible naming mismatch if file is
                # missing but orphan files exist in the directory
                if not file_exists and orphan_files:
                    orphan_list = ', '.join(sorted(orphan_files))
                    self.warnings.append(
                        f"No API definition file found for draft API '{api_name}'. "
                        f"Unmatched files in code/API_definitions/: {orphan_list}. "
                        f"Check for possible naming mismatch"
                    )

    def validate(self) -> bool:
        """Run full validation and return success status."""
        # Load release plan file
        release_plan = self.load_yaml(self.release_plan_file)
        if self.errors:
            return False

        # Find or use provided schema file
        if not self.schema_file:
            self.schema_file = self.find_schema_file()
            if not self.schema_file:
                self.errors.append("Cannot find release-plan-schema.yaml")
                return False

        print(f"Using schema: {self.schema_file}")

        # Load schema
        schema = self.load_yaml(self.schema_file)
        if self.errors:
            return False

        # Validate against schema (collects all schema errors)
        schema_valid = self.validate_schema(release_plan, schema)

        # Run semantic checks even if schema has errors (collect all issues)
        # But only if the basic structure is valid enough to check semantics
        if schema_valid or release_plan.get('repository') and release_plan.get('apis'):
            self.check_semantic_rules(release_plan)

        # Check file existence only if the plan is internally valid
        # (schema + semantic errors make file checks meaningless)
        if not self.errors:
            self.check_file_existence(release_plan)

        return len(self.errors) == 0

    def report(self) -> None:
        """Print validation report."""
        if self.errors:
            print("\nValidation FAILED:")
            for error in self.errors:
                print(f"  ERROR: {error}")

        if self.warnings:
            print("\nWarnings:")
            for warning in self.warnings:
                print(f"  WARNING: {warning}")

        if not self.errors and not self.warnings:
            print("\nValidation PASSED: No errors or warnings")
        elif not self.errors:
            print("\nValidation PASSED with warnings")


def main():
    parser = argparse.ArgumentParser(
        description='Validate CAMARA release-plan.yaml files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        'release_plan_file',
        type=Path,
        help='Path to release-plan.yaml file'
    )
    parser.add_argument(
        '--schema',
        type=Path,
        help='Path to schema file (uses bundled schema if not provided)'
    )
    parser.add_argument(
        '--check-files',
        action='store_true',
        help='Check if referenced API definition files exist'
    )

    args = parser.parse_args()

    if not args.release_plan_file.exists():
        print(f"Error: Release plan file not found: {args.release_plan_file}")
        sys.exit(1)

    validator = ReleasePlanValidator(
        args.release_plan_file,
        args.schema,
        args.check_files
    )

    success = validator.validate()
    validator.report()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()