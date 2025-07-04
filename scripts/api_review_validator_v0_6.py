#!/usr/bin/env python3
"""
Enhanced CAMARA API Review Validator v0.6 - Production Ready
=============================================================

Production-ready enhanced version of the CAMARA API validator with:
- Robust CLI interface with comprehensive argument parsing
- Enhanced error handling and logging
- Improved report generation
- GitHub Actions integration optimizations
- Comprehensive progress reporting

Usage:
    python api_review_validator_v0_6.py <target_directory> [options]

Options:
    --output <dir>              Output directory for reports (default: ./output)
    --repo-name <name>          Repository name for reporting
    --pr-number <number>        Pull request number for reporting
    --commonalities-version <v> CAMARA Commonalities version (default: 0.6)
    --review-type <type>        Review type (default: release-candidate)
    --verbose                   Enable verbose logging
    --help                      Show this help message

Author: CAMARA API Review Team
Version: 0.6 (Production Ready)
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
import re
import traceback

# External dependencies (GitHub Actions compatible)
try:
    import yaml
    import jsonschema
    from openapi_spec_validator import validate_spec
    import requests
except ImportError as e:
    print(f"❌ Error: Required dependency not found: {e}")
    print("Please ensure the following packages are installed:")
    print("  - pyyaml")
    print("  - jsonschema")
    print("  - openapi-spec-validator")
    print("  - requests")
    sys.exit(2)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class Severity(Enum):
    """Issue severity levels"""
    CRITICAL = "critical"
    MEDIUM = "medium"
    LOW = "low"


class APIType(Enum):
    """API type classification"""
    REGULAR = "regular"
    EXPLICIT_SUBSCRIPTION = "explicit-subscription"
    IMPLICIT_SUBSCRIPTION = "implicit-subscription"


class ValidationIssue:
    """Represents a validation issue"""
    
    def __init__(self, severity: Severity, category: str, message: str, location: str = ""):
        self.severity = severity
        self.category = category
        self.message = message
        self.location = location
        self.timestamp = datetime.now()
    
    def __str__(self):
        return f"[{self.severity.value.upper()}] {self.category}: {self.message}"


class ValidationResult:
    """Stores validation results for a single API"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.api_name = Path(file_path).stem
        self.version = "unknown"
        self.api_type = APIType.REGULAR
        self.issues: List[ValidationIssue] = []
        self.validation_timestamp = datetime.now()
    
    @property
    def critical_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.CRITICAL])
    
    @property
    def medium_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.MEDIUM])
    
    @property
    def low_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.LOW])
    
    @property
    def total_issues(self) -> int:
        return len(self.issues)


class ProgressReporter:
    """Handles progress reporting and logging"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.start_time = time.time()
        self.steps_completed = 0
        self.total_steps = 0
    
    def set_total_steps(self, total: int):
        self.total_steps = total
    
    def step(self, message: str, detail: str = ""):
        self.steps_completed += 1
        elapsed = time.time() - self.start_time
        
        if self.total_steps > 0:
            progress = (self.steps_completed / self.total_steps) * 100
            print(f"[{self.steps_completed}/{self.total_steps}] {message} ({progress:.1f}%, {elapsed:.1f}s)")
        else:
            print(f"[{self.steps_completed}] {message} ({elapsed:.1f}s)")
        
        if self.verbose and detail:
            print(f"  └─ {detail}")
        
        logger.info(f"Step {self.steps_completed}: {message}")
    
    def error(self, message: str, exception: Exception = None):
        print(f"❌ Error: {message}")
        logger.error(f"Error: {message}")
        
        if exception and self.verbose:
            print(f"  └─ Exception: {str(exception)}")
            logger.error(f"Exception details: {traceback.format_exc()}")
    
    def warning(self, message: str):
        print(f"⚠️  Warning: {message}")
        logger.warning(f"Warning: {message}")
    
    def info(self, message: str):
        print(f"ℹ️  Info: {message}")
        logger.info(f"Info: {message}")


class EnhancedCAMARAValidator:
    """Enhanced CAMARA API Validator with production-ready features"""
    
    def __init__(self, commonalities_version: str = "0.6", verbose: bool = False):
        self.commonalities_version = commonalities_version
        self.verbose = verbose
        self.progress = ProgressReporter(verbose)
        
        # Validation statistics
        self.stats = {
            'files_processed': 0,
            'total_issues': 0,
            'critical_issues': 0,
            'medium_issues': 0,
            'low_issues': 0,
            'apis_by_type': {}
        }
        
        # Load validation rules for the specified version
        self._load_validation_rules()
    
    def _load_validation_rules(self):
        """Load version-specific validation rules"""
        if self.commonalities_version == "0.6":
            self._load_v0_6_rules()
        else:
            raise ValueError(f"Unsupported Commonalities version: {self.commonalities_version}")
    
    def _load_v0_6_rules(self):
        """Load Commonalities 0.6 validation rules"""
        self.required_openapi_version = "3.0.3"
        self.forbidden_error_codes = [
            'AUTHENTICATION_REQUIRED',
            'IDENTIFIER_MISMATCH'
        ]
        
        # Common schemas expected in CAMARA APIs
        self.expected_common_schemas = {
            'ErrorInfo': True,
            'XCorrelator': True,
            'Device': False  # Optional, depends on API type
        }
        
        # Security scope pattern
        self.scope_pattern = re.compile(r'^[a-z][a-z0-9\-]*:[a-z][a-z0-9\-]*(?::[a-z][a-z0-9\-]*)?$')
    
    def find_api_files(self, target_dir: str) -> List[str]:
        """Find all API definition files in the target directory"""
        api_dir = Path(target_dir) / "code" / "API_definitions"
        
        if not api_dir.exists():
            self.progress.error(f"API definitions directory not found: {api_dir}")
            return []
        
        api_files = []
        for yaml_file in api_dir.glob("*.yaml"):
            if yaml_file.name.startswith('.') or yaml_file.name.startswith('_'):
                continue
            api_files.append(str(yaml_file))
        
        for yml_file in api_dir.glob("*.yml"):
            if yml_file.name.startswith('.') or yml_file.name.startswith('_'):
                continue
            api_files.append(str(yml_file))
        
        return sorted(api_files)
    
    def validate_api_file(self, file_path: str) -> ValidationResult:
        """Validate a single API file"""
        result = ValidationResult(file_path)
        
        try:
            # Load and parse YAML
            with open(file_path, 'r', encoding='utf-8') as f:
                api_spec = yaml.safe_load(f)
            
            if not api_spec:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "File Format",
                    "Empty or invalid YAML file"
                ))
                return result
            
            # Extract basic info
            result.api_name = Path(file_path).stem
            result.version = api_spec.get('info', {}).get('version', 'unknown')
            result.api_type = self._determine_api_type(api_spec)
            
            # Run validation rules
            self._validate_openapi_structure(api_spec, result)
            self._validate_info_object(api_spec, result)
            self._validate_servers(api_spec, result)
            self._validate_security(api_spec, result)
            self._validate_paths(api_spec, result)
            self._validate_components(api_spec, result)
            self._validate_external_docs(api_spec, result)
            
            # API type-specific validation
            if result.api_type != APIType.REGULAR:
                self._validate_subscription_api(api_spec, result)
            
            # Update statistics
            self.stats['files_processed'] += 1
            self.stats['total_issues'] += result.total_issues
            self.stats['critical_issues'] += result.critical_count
            self.stats['medium_issues'] += result.medium_count
            self.stats['low_issues'] += result.low_count
            
            api_type_str = result.api_type.value
            self.stats['apis_by_type'][api_type_str] = self.stats['apis_by_type'].get(api_type_str, 0) + 1
            
        except yaml.YAMLError as e:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "YAML Parsing",
                f"Invalid YAML syntax: {str(e)}"
            ))
        except Exception as e:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Validation Error",
                f"Unexpected error during validation: {str(e)}"
            ))
            self.progress.error(f"Error validating {file_path}", e)
        
        return result
    
    def _determine_api_type(self, api_spec: dict) -> APIType:
        """Determine the API type based on its structure"""
        paths = api_spec.get('paths', {})
        
        # Check for subscription management endpoints
        for path in paths.keys():
            if 'subscriptions' in path:
                return APIType.EXPLICIT_SUBSCRIPTION
        
        # Check for webhook/notification schemas
        components = api_spec.get('components', {})
        schemas = components.get('schemas', {})
        
        for schema_name in schemas.keys():
            if any(term in schema_name.lower() for term in ['notification', 'event', 'callback']):
                return APIType.IMPLICIT_SUBSCRIPTION
        
        return APIType.REGULAR
    
    def _validate_openapi_structure(self, api_spec: dict, result: ValidationResult):
        """Validate basic OpenAPI structure"""
        # Check OpenAPI version
        openapi_version = api_spec.get('openapi')
        if not openapi_version:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "OpenAPI Version",
                "Missing 'openapi' field"
            ))
        elif openapi_version != self.required_openapi_version:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "OpenAPI Version",
                f"Expected OpenAPI version {self.required_openapi_version}, found {openapi_version}"
            ))
        
        # Check required top-level fields
        required_fields = ['info', 'paths']
        for field in required_fields:
            if field not in api_spec:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Required Fields",
                    f"Missing required field: {field}"
                ))
    
    def _validate_info_object(self, api_spec: dict, result: ValidationResult):
        """Validate the info object"""
        info = api_spec.get('info', {})
        
        # Required fields
        required_fields = ['title', 'version', 'description']
        for field in required_fields:
            if field not in info:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Info Object",
                    f"Missing required field in info: {field}"
                ))
        
        # Check title format
        title = info.get('title', '')
        if title and not title.replace(' ', '').replace('-', '').isalnum():
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Info Object",
                "Title should contain only alphanumeric characters, spaces, and hyphens"
            ))
        
        # Check version format
        version = info.get('version', '')
        if version and not re.match(r'^\d+\.\d+\.\d+(-\w+)?$', version):
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Info Object",
                f"Version format should be semantic (e.g., 1.0.0): {version}"
            ))
    
    def _validate_servers(self, api_spec: dict, result: ValidationResult):
        """Validate servers configuration"""
        servers = api_spec.get('servers', [])
        
        if not servers:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Servers",
                "Missing servers configuration"
            ))
            return
        
        for i, server in enumerate(servers):
            if 'url' not in server:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Servers",
                    f"Server {i} missing URL"
                ))
            
            url = server.get('url', '')
            if url and not (url.startswith('http://') or url.startswith('https://') or url.startswith('{')):
                result.issues.append(ValidationIssue(
                    Severity.MEDIUM, "Servers",
                    f"Server URL should be absolute or templated: {url}"
                ))
    
    def _validate_security(self, api_spec: dict, result: ValidationResult):
        """Validate security configuration"""
        components = api_spec.get('components', {})
        security_schemes = components.get('securitySchemes', {})
        
        # Check for required openId security scheme
        if 'openId' not in security_schemes:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Security",
                "Missing required 'openId' security scheme"
            ))
        else:
            openid_scheme = security_schemes['openId']
            if openid_scheme.get('type') != 'openIdConnect':
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Security",
                    "openId scheme must be of type 'openIdConnect'"
                ))
        
        # Validate security scopes
        paths = api_spec.get('paths', {})
        for path, path_obj in paths.items():
            for method, operation in path_obj.items():
                if method in ['get', 'post', 'put', 'delete', 'patch']:
                    security = operation.get('security', [])
                    for sec_req in security:
                        for scheme_name, scopes in sec_req.items():
                            for scope in scopes:
                                if not self.scope_pattern.match(scope):
                                    result.issues.append(ValidationIssue(
                                        Severity.MEDIUM, "Security Scopes",
                                        f"Invalid scope format: {scope} (should match pattern: api-name:resource:action)"
                                    ))
    
    def _validate_paths(self, api_spec: dict, result: ValidationResult):
        """Validate paths and operations"""
        paths = api_spec.get('paths', {})
        
        if not paths:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Paths",
                "No paths defined"
            ))
            return
        
        for path, path_obj in paths.items():
            # Validate path format
            if not path.startswith('/'):
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Paths",
                    f"Path must start with '/': {path}"
                ))
            
            # Validate operations
            for method, operation in path_obj.items():
                if method in ['get', 'post', 'put', 'delete', 'patch']:
                    self._validate_operation(operation, f"{method.upper()} {path}", result)
    
    def _validate_operation(self, operation: dict, operation_id: str, result: ValidationResult):
        """Validate a single operation"""
        # Check required fields
        required_fields = ['operationId', 'description', 'responses']
        for field in required_fields:
            if field not in operation:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Operation",
                    f"Missing required field '{field}' in {operation_id}"
                ))
        
        # Validate operationId format
        op_id = operation.get('operationId', '')
        if op_id and not re.match(r'^[a-zA-Z][a-zA-Z0-9]*$', op_id):
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Operation",
                f"operationId should be camelCase: {op_id}"
            ))
        
        # Validate responses
        responses = operation.get('responses', {})
        if responses:
            self._validate_responses(responses, operation_id, result)
    
    def _validate_responses(self, responses: dict, operation_id: str, result: ValidationResult):
        """Validate operation responses"""
        # Check for success response
        success_codes = ['200', '201', '202', '204']
        has_success = any(code in responses for code in success_codes)
        
        if not has_success:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Responses",
                f"No success response defined for {operation_id}"
            ))
        
        # Check for error responses
        error_codes = ['400', '401', '403', '404', '500']
        for code in error_codes:
            if code in responses:
                error_response = responses[code]
                content = error_response.get('content', {})
                
                if 'application/json' in content:
                    schema = content['application/json'].get('schema', {})
                    if '$ref' in schema:
                        ref_path = schema['$ref']
                        if not ref_path.endswith('/ErrorInfo'):
                            result.issues.append(ValidationIssue(
                                Severity.MEDIUM, "Error Responses",
                                f"Error response should reference ErrorInfo schema: {operation_id}"
                            ))
    
    def _validate_components(self, api_spec: dict, result: ValidationResult):
        """Validate components section"""
        components = api_spec.get('components', {})
        
        if not components:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Components",
                "No components defined"
            ))
            return
        
        schemas = components.get('schemas', {})
        
        # Check for required common schemas
        for schema_name, required in self.expected_common_schemas.items():
            if required and schema_name not in schemas:
                result.issues.append(ValidationIssue(
                    Severity.CRITICAL, "Common Schemas",
                    f"Missing required schema: {schema_name}"
                ))
        
        # Validate schema structure
        for schema_name, schema_def in schemas.items():
            if isinstance(schema_def, dict):
                self._validate_schema(schema_def, schema_name, result)
    
    def _validate_schema(self, schema: dict, schema_name: str, result: ValidationResult):
        """Validate a single schema"""
        # Check for description
        if 'description' not in schema and 'allOf' not in schema:
            result.issues.append(ValidationIssue(
                Severity.LOW, "Schema Documentation",
                f"Schema '{schema_name}' missing description"
            ))
        
        # Check for proper type definitions
        if 'type' not in schema and 'allOf' not in schema and '$ref' not in schema:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Schema Structure",
                f"Schema '{schema_name}' missing type definition"
            ))
    
    def _validate_external_docs(self, api_spec: dict, result: ValidationResult):
        """Validate external documentation"""
        external_docs = api_spec.get('externalDocs')
        
        if not external_docs:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "External Documentation",
                "Missing externalDocs"
            ))
            return
        
        # Check required fields
        if 'url' not in external_docs:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "External Documentation",
                "Missing URL in externalDocs"
            ))
        
        # Check URL format
        url = external_docs.get('url', '')
        if url and not url.startswith('https://github.com/camaraproject/'):
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "External Documentation",
                "External docs URL should point to CAMARA project repository"
            ))
    
    def _validate_subscription_api(self, api_spec: dict, result: ValidationResult):
        """Validate subscription-specific requirements"""
        # This is a placeholder for subscription-specific validation
        # In a full implementation, this would check for:
        # - Proper webhook/callback definitions
        # - CloudEvents compliance
        # - Subscription lifecycle management
        pass
    
    def generate_report(self, results: List[ValidationResult], output_dir: str, 
                       repo_name: str, pr_number: str) -> str:
        """Generate comprehensive validation report"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"{repo_name}_pr{pr_number}_api_review_report_v{self.commonalities_version}.md"
        report_path = Path(output_dir) / report_filename
        
        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Calculate statistics
        total_critical = sum(result.critical_count for result in results)
        total_medium = sum(result.medium_count for result in results)
        total_low = sum(result.low_count for result in results)
        total_issues = sum(result.total_issues for result in results)
        
        # Generate detailed report
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(f"# CAMARA API Review Report\n\n")
            f.write(f"**Repository**: {repo_name}\n")
            f.write(f"**PR Number**: {pr_number}\n")
            f.write(f"**Commonalities Version**: {self.commonalities_version}\n")
            f.write(f"**Review Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Validator Version**: 0.6 (Production Ready)\n\n")
            
            # Executive Summary
            f.write("## Executive Summary\n\n")
            f.write(f"**APIs Reviewed**: {len(results)}\n")
            f.write(f"**Total Issues**: {total_issues}\n")
            f.write(f"- 🔴 Critical: {total_critical}\n")
            f.write(f"- 🟡 Medium: {total_medium}\n")
            f.write(f"- 🔵 Low: {total_low}\n\n")
            
            # Overall Assessment
            if total_critical == 0:
                if total_medium == 0:
                    f.write("✅ **Status**: Ready for Release\n\n")
                else:
                    f.write("⚠️ **Status**: Conditional Approval (Medium issues should be addressed)\n\n")
            else:
                f.write("❌ **Status**: Critical Issues Must Be Fixed\n\n")
            
            # API Details
            f.write("## API Analysis\n\n")
            for result in results:
                f.write(f"### {result.api_name} v{result.version}\n\n")
                f.write(f"**Type**: {result.api_type.value}\n")
                f.write(f"**File**: `{Path(result.file_path).name}`\n")
                f.write(f"**Issues**: {result.total_issues} total\n\n")
                
                if result.issues:
                    # Group issues by severity
                    critical_issues = [i for i in result.issues if i.severity == Severity.CRITICAL]
                    medium_issues = [i for i in result.issues if i.severity == Severity.MEDIUM]
                    low_issues = [i for i in result.issues if i.severity == Severity.LOW]
                    
                    for severity, issues, emoji in [
                        (Severity.CRITICAL, critical_issues, "🔴"),
                        (Severity.MEDIUM, medium_issues, "🟡"),
                        (Severity.LOW, low_issues, "🔵")
                    ]:
                        if issues:
                            f.write(f"#### {emoji} {severity.value.title()} Issues\n\n")
                            for issue in issues:
                                f.write(f"- **{issue.category}**: {issue.message}\n")
                                if issue.location:
                                    f.write(f"  - Location: {issue.location}\n")
                            f.write("\n")
                else:
                    f.write("✅ No issues found\n\n")
            
            # Recommendations
            f.write("## Recommendations\n\n")
            if total_critical > 0:
                f.write("1. **Address Critical Issues**: Fix all critical issues before proceeding\n")
            if total_medium > 0:
                f.write("2. **Consider Medium Issues**: Review and address medium priority issues\n")
            if total_low > 0:
                f.write("3. **Low Priority Improvements**: Consider addressing low priority issues for better compliance\n")
            f.write("4. **Validate Changes**: Re-run validation after making changes\n\n")
            
            # Validation Statistics
            f.write("## Validation Statistics\n\n")
            f.write(f"- Files processed: {self.stats['files_processed']}\n")
            f.write(f"- Processing time: {time.time() - self.progress.start_time:.2f} seconds\n")
            f.write(f"- APIs by type:\n")
            for api_type, count in self.stats['apis_by_type'].items():
                f.write(f"  - {api_type}: {count}\n")
            f.write("\n")
        
        # Generate summary for GitHub comments
        self._generate_summary(results, output_dir, repo_name, pr_number)
        
        return str(report_path)
    
    def _generate_summary(self, results: List[ValidationResult], output_dir: str, 
                         repo_name: str, pr_number: str):
        """Generate summary for GitHub comments"""
        summary_path = Path(output_dir) / "summary.md"
        
        # Calculate statistics
        total_critical = sum(result.critical_count for result in results)
        total_medium = sum(result.medium_count for result in results)
        total_low = sum(result.low_count for result in results)
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            # Status indicator
            if total_critical == 0:
                if total_medium == 0:
                    f.write("✅ **Ready for Release**\n\n")
                else:
                    f.write("⚠️ **Conditional Approval**\n\n")
            else:
                f.write("❌ **Critical Issues Found**\n\n")
            
            # Quick stats
            f.write("**APIs Reviewed**:\n")
            for result in results:
                type_icon = {
                    APIType.REGULAR: "📄",
                    APIType.EXPLICIT_SUBSCRIPTION: "🔔",
                    APIType.IMPLICIT_SUBSCRIPTION: "📧"
                }[result.api_type]
                f.write(f"- {type_icon} `{result.api_name}` v{result.version}\n")
            
            f.write(f"\n**Issues Summary**:\n")
            f.write(f"- 🔴 Critical: {total_critical}\n")
            f.write(f"- 🟡 Medium: {total_medium}\n")
            f.write(f"- 🔵 Low: {total_low}\n\n")
            
            # Critical issues detail (limited to prevent overly long comments)
            if total_critical > 0:
                f.write("**Critical Issues Requiring Immediate Attention**:\n")
                critical_count = 0
                for result in results:
                    critical_issues = [i for i in result.issues if i.severity == Severity.CRITICAL]
                    for issue in critical_issues:
                        if critical_count < 10:  # Limit to prevent spam
                            f.write(f"- {result.api_name}: {issue.category} - {issue.message}\n")
                            critical_count += 1
                        else:
                            f.write(f"- ... and {total_critical - critical_count} more critical issues\n")
                            break
                    if critical_count >= 10:
                        break
                f.write("\n")
            
            # Next steps
            f.write("**Next Steps**:\n")
            f.write("1. Review the detailed report in the workflow artifacts\n")
            if total_critical > 0:
                f.write("2. Fix all critical issues\n")
                f.write("3. Re-run validation\n")
            else:
                f.write("2. Consider addressing medium and low priority issues\n")
                f.write("3. Proceed with release process\n")


def setup_argument_parser() -> argparse.ArgumentParser:
    """Setup command line argument parser"""
    parser = argparse.ArgumentParser(
        description="Enhanced CAMARA API Review Validator v0.6 - Production Ready",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python api_review_validator_v0_6.py /path/to/repo
  python api_review_validator_v0_6.py /path/to/repo --output ./reports --verbose
  python api_review_validator_v0_6.py /path/to/repo --repo-name QualityOnDemand --pr-number 123
        """
    )
    
    parser.add_argument(
        'target_directory',
        help='Target directory containing the API repository'
    )
    
    parser.add_argument(
        '--output',
        default='./output',
        help='Output directory for reports (default: ./output)'
    )
    
    parser.add_argument(
        '--repo-name',
        default='Unknown',
        help='Repository name for reporting'
    )
    
    parser.add_argument(
        '--pr-number',
        default='0',
        help='Pull request number for reporting'
    )
    
    parser.add_argument(
        '--commonalities-version',
        default='0.6',
        help='CAMARA Commonalities version (default: 0.6)'
    )
    
    parser.add_argument(
        '--review-type',
        default='release-candidate',
        help='Review type (default: release-candidate)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    return parser


def main():
    """Main entry point"""
    parser = setup_argument_parser()
    args = parser.parse_args()
    
    # Setup logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    print(f"🚀 CAMARA API Review Validator v0.6 (Production Ready)")
    print(f"📁 Target Directory: {args.target_directory}")
    print(f"📄 Repository: {args.repo_name}")
    print(f"🔢 PR Number: {args.pr_number}")
    print(f"📋 Review Type: {args.review_type}")
    print(f"📊 Commonalities Version: {args.commonalities_version}")
    print(f"📝 Output Directory: {args.output}")
    print(f"🔍 Verbose Mode: {'Enabled' if args.verbose else 'Disabled'}")
    print()
    
    # Validate inputs
    target_path = Path(args.target_directory)
    if not target_path.exists():
        print(f"❌ Error: Target directory does not exist: {args.target_directory}")
        sys.exit(2)
    
    if not target_path.is_dir():
        print(f"❌ Error: Target path is not a directory: {args.target_directory}")
        sys.exit(2)
    
    try:
        # Initialize validator
        validator = EnhancedCAMARAValidator(
            commonalities_version=args.commonalities_version,
            verbose=args.verbose
        )
        
        # Find API files
        validator.progress.step("Discovering API files")
        api_files = validator.find_api_files(args.target_directory)
        
        if not api_files:
            print("❌ No API definition files found in /code/API_definitions/")
            print("   Please ensure YAML files are present in the correct directory")
            sys.exit(1)
        
        print(f"📁 Found {len(api_files)} API definition files")
        for api_file in api_files:
            print(f"   - {Path(api_file).name}")
        print()
        
        # Set up progress tracking
        validator.progress.set_total_steps(len(api_files) + 2)  # +2 for discovery and report generation
        
        # Validate each API file
        results = []
        for api_file in api_files:
            validator.progress.step(f"Validating {Path(api_file).name}")
            result = validator.validate_api_file(api_file)
            results.append(result)
            
            # Progress feedback
            if result.total_issues == 0:
                print(f"   ✅ No issues found")
            else:
                print(f"   🔴 {result.critical_count} critical, 🟡 {result.medium_count} medium, 🔵 {result.low_count} low")
        
        # Generate report
        validator.progress.step("Generating comprehensive report")
        report_path = validator.generate_report(results, args.output, args.repo_name, args.pr_number)
        
        # Final summary
        total_critical = sum(result.critical_count for result in results)
        total_medium = sum(result.medium_count for result in results)
        total_low = sum(result.low_count for result in results)
        total_issues = sum(result.total_issues for result in results)
        
        print(f"\n📊 Validation Complete!")
        print(f"   📄 Files processed: {len(results)}")
        print(f"   🔴 Critical issues: {total_critical}")
        print(f"   🟡 Medium issues: {total_medium}")
        print(f"   🔵 Low issues: {total_low}")
        print(f"   📝 Total issues: {total_issues}")
        print(f"   📋 Report generated: {report_path}")
        print(f"   📄 Summary generated: {Path(args.output) / 'summary.md'}")
        
        # Determine exit code
        if total_critical > 0:
            print(f"\n❌ Validation failed with {total_critical} critical issues")
            sys.exit(1)
        elif total_medium > 0:
            print(f"\n⚠️ Validation completed with {total_medium} medium priority issues")
            sys.exit(0)
        else:
            print(f"\n✅ Validation passed successfully!")
            sys.exit(0)
            
    except KeyboardInterrupt:
        print(f"\n⚠️ Validation interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {str(e)}")
        if args.verbose:
            print(f"   Exception details: {traceback.format_exc()}")
        sys.exit(2)


if __name__ == "__main__":
    main()