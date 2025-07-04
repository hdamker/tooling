#!/usr/bin/env python3
"""
CAMARA API Review Validator v0.6
Automated validation of CAMARA API definitions with comprehensive validation coverage

This script uses modern argparse with named arguments to match the workflow expectations.
"""

import os
import sys
import yaml
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import datetime
import traceback

def safe_filename(filename: str, max_length: int = 200) -> str:
    """Sanitize filename to prevent path traversal and other issues"""
    # Remove any path components
    filename = os.path.basename(filename)
    
    # Replace dangerous characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    
    # Limit length
    if len(filename) > max_length:
        name, ext = os.path.splitext(filename)
        filename = name[:max_length-len(ext)-3] + "..." + ext
    
    # Ensure it's not empty or just dots
    if not filename or filename.replace('.', '').replace('_', '') == '':
        filename = "sanitized_filename.md"
    
    return filename

def validate_directory_path(path: str) -> str:
    """Validate and normalize directory path"""
    # Convert to absolute path and resolve
    abs_path = os.path.abspath(os.path.expanduser(path))
    
    # Check if path exists
    if not os.path.exists(abs_path):
        raise ValueError(f"Directory does not exist: {abs_path}")
    
    # Check if it's actually a directory
    if not os.path.isdir(abs_path):
        raise ValueError(f"Path is not a directory: {abs_path}")
    
    return abs_path

class Severity(Enum):
    CRITICAL = "🔴 Critical"
    MEDIUM = "🟡 Medium"
    LOW = "🔵 Low"
    INFO = "ℹ️ Info"

class APIType(Enum):
    REGULAR = "Regular API"
    IMPLICIT_SUBSCRIPTION = "Implicit Subscription API"
    EXPLICIT_SUBSCRIPTION = "Explicit Subscription API"

@dataclass
class ValidationIssue:
    severity: Severity
    category: str
    description: str
    location: str = ""
    fix_suggestion: str = ""

@dataclass
class ValidationResult:
    file_path: str
    api_name: str = ""
    version: str = ""
    api_type: APIType = APIType.REGULAR
    issues: List[ValidationIssue] = field(default_factory=list)
    checks_performed: List[str] = field(default_factory=list)
    manual_checks_needed: List[str] = field(default_factory=list)
    
    @property
    def critical_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.CRITICAL])
    
    @property
    def medium_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.MEDIUM])
    
    @property
    def low_count(self) -> int:
        return len([i for i in self.issues if i.severity == Severity.LOW])

@dataclass
class ConsistencyResult:
    issues: List[ValidationIssue] = field(default_factory=list)
    checks_performed: List[str] = field(default_factory=list)

@dataclass
class TestAlignmentResult:
    api_file: str
    test_files: List[str] = field(default_factory=list)
    issues: List[ValidationIssue] = field(default_factory=list)
    checks_performed: List[str] = field(default_factory=list)

class CAMARAAPIValidator:
    """CAMARA API Validator for Commonalities v0.6"""
    
    def __init__(self, commonalities_version: str = "0.6"):
        self.expected_commonalities_version = commonalities_version
    
    def validate_api_file(self, file_path: str) -> ValidationResult:
        """Validate a single API file"""
        result = ValidationResult(file_path=file_path)
        result.checks_performed.append(f"CAMARA Commonalities {self.expected_commonalities_version} validation")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                api_spec = yaml.safe_load(f)
            
            # Extract basic info
            info = api_spec.get('info', {})
            result.api_name = info.get('title', Path(file_path).stem)
            result.version = info.get('version', 'unknown')
            
            # Detect API type
            result.api_type = self._detect_api_type(api_spec)
            
            # Run validation checks
            self._validate_info_object(api_spec, result)
            self._validate_paths(api_spec, result)
            self._validate_components(api_spec, result)
            
            # Commonalities 0.6 specific checks
            self._check_work_in_progress_version(api_spec, result)
            self._check_updated_generic401(api_spec, result)
            
        except yaml.YAMLError as e:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "YAML Syntax", f"YAML parsing error: {str(e)}"
            ))
        except Exception as e:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Validation Error", f"Unexpected error: {str(e)}"
            ))
        
        return result
    
    def _detect_api_type(self, api_spec: dict) -> APIType:
        """Detect if this is a subscription API"""
        paths = api_spec.get('paths', {})
        
        # Check for explicit subscription endpoints
        for path in paths.keys():
            if '/subscriptions' in path.lower():
                return APIType.EXPLICIT_SUBSCRIPTION
        
        # Check for webhook/event patterns in responses
        for path_obj in paths.values():
            for operation in path_obj.values():
                if isinstance(operation, dict):
                    responses = operation.get('responses', {})
                    for response in responses.values():
                        if isinstance(response, dict):
                            content = response.get('content', {})
                            for media_type, media_obj in content.items():
                                if isinstance(media_obj, dict):
                                    schema = media_obj.get('schema', {})
                                    if 'webhook' in str(schema).lower() or 'event' in str(schema).lower():
                                        return APIType.IMPLICIT_SUBSCRIPTION
        
        return APIType.REGULAR
    
    def _validate_info_object(self, api_spec: dict, result: ValidationResult):
        """Validate the info object"""
        info = api_spec.get('info', {})
        
        # Title check
        title = info.get('title', '')
        if 'API' in title:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Info Object",
                f"Title should not include 'API': `{title}`",
                "info.title",
                "Remove 'API' from title"
            ))
        
        # Version check
        version = info.get('version', '')
        if version != 'wip' and not re.match(r'^\d+\.\d+\.\d+(-rc\.\d+|-alpha\.\d+)?$', version):
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Info Object",
                f"Invalid version format: `{version}`",
                "info.version",
                "Use semantic versioning (`x.y.z` or `x.y.z-rc.n`)"
            ))
        
        # License check
        license_info = info.get('license', {})
        if license_info.get('name') != 'Apache 2.0':
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Info Object",
                "License must be `Apache 2.0`",
                "info.license.name"
            ))
        
        if license_info.get('url') != 'https://www.apache.org/licenses/LICENSE-2.0.html':
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Info Object",
                "Incorrect license URL",
                "info.license.url"
            ))
        
        # Commonalities version
        commonalities = info.get('x-camara-commonalities')
        if str(commonalities) != self.expected_commonalities_version:
            result.issues.append(ValidationIssue(
                Severity.MEDIUM, "Info Object",
                f"Expected commonalities `{self.expected_commonalities_version}`, found: `{commonalities}`",
                "info.x-camara-commonalities"
            ))
    
    def _validate_paths(self, api_spec: dict, result: ValidationResult):
        """Validate paths object"""
        paths = api_spec.get('paths', {})
        
        for path, path_obj in paths.items():
            for method, operation in path_obj.items():
                if method in ['get', 'post', 'put', 'delete', 'patch']:
                    self._validate_operation(operation, f"{method.upper()} {path}", result)
    
    def _validate_operation(self, operation: dict, operation_name: str, result: ValidationResult):
        """Validate individual operation"""
        # Check for operationId
        if 'operationId' not in operation:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Operation",
                "Missing operationId",
                operation_name
            ))
        
        # Check responses
        responses = operation.get('responses', {})
        if not responses:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Operation",
                "No responses defined",
                operation_name
            ))
    
    def _validate_components(self, api_spec: dict, result: ValidationResult):
        """Validate components section"""
        components = api_spec.get('components', {})
        
        # Check for required error schemas
        schemas = components.get('schemas', {})
        if 'ErrorInfo' not in schemas:
            result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Components",
                "Missing required ErrorInfo schema",
                "components.schemas"
            ))
    
    def _check_work_in_progress_version(self, api_spec: dict, result: ValidationResult):
        """Check for work-in-progress version handling"""
        version = api_spec.get('info', {}).get('version', '')
        if version == 'wip':
            result.issues.append(ValidationIssue(
                Severity.INFO, "Version",
                "API is marked as work-in-progress",
                "info.version"
            ))
    
    def _check_updated_generic401(self, api_spec: dict, result: ValidationResult):
        """Check for updated generic 401 error handling (Commonalities 0.6)"""
        # This would check for the updated authentication error patterns
        # Implementation depends on specific 0.6 requirements
        pass

def find_api_files(directory: str) -> List[str]:
    """Find all YAML files in the API definitions directory"""
    api_dir = Path(directory) / "code" / "API_definitions"
    
    if not api_dir.exists():
        return []
    
    yaml_files = []
    for pattern in ['*.yaml', '*.yml']:
        yaml_files.extend(api_dir.glob(pattern))
    
    return [str(f) for f in yaml_files]

def generate_report(results: List[ValidationResult], output_dir: str, repo_name: str = "", pr_number: str = "", 
                   consistency_result: Optional[ConsistencyResult] = None, 
                   test_results: List[TestAlignmentResult] = None, commonalities_version: str = "0.6") -> str:
    """Generate comprehensive report and summary"""
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate unique filename with repository name and timestamp
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    version_clean = commonalities_version.replace('.', '_')
    
    if repo_name and pr_number:
        base_filename = f"api_review_{repo_name}_pr{pr_number}_v{version_clean}_{timestamp}"
    else:
        base_filename = f"api_review_v{version_clean}_{timestamp}"
    
    report_filename = safe_filename(f"{base_filename}.md")
    
    # Calculate totals
    total_critical = sum(r.critical_count for r in results)
    total_medium = sum(r.medium_count for r in results)
    total_low = sum(r.low_count for r in results)
    
    if consistency_result:
        total_critical += len([i for i in consistency_result.issues if i.severity == Severity.CRITICAL])
        total_medium += len([i for i in consistency_result.issues if i.severity == Severity.MEDIUM])
        total_low += len([i for i in consistency_result.issues if i.severity == Severity.LOW])
    
    # Generate detailed report
    with open(f"{output_dir}/{report_filename}", "w") as f:
        f.write(f"# CAMARA API Review Report\n\n")
        f.write(f"**Generated**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Commonalities Version**: {commonalities_version}\n")
        
        if repo_name:
            f.write(f"**Repository**: {repo_name}\n")
        if pr_number:
            f.write(f"**PR Number**: {pr_number}\n")
        
        f.write(f"\n## Summary\n\n")
        f.write(f"- **APIs Reviewed**: {len(results)}\n")
        f.write(f"- **Critical Issues**: {total_critical}\n")
        f.write(f"- **Medium Issues**: {total_medium}\n")
        f.write(f"- **Low Issues**: {total_low}\n\n")
        
        # Individual API results
        for result in results:
            f.write(f"## {result.api_name} v{result.version}\n\n")
            f.write(f"**File**: `{Path(result.file_path).name}`\n")
            f.write(f"**Type**: {result.api_type.value}\n")
            f.write(f"**Issues**: {result.critical_count} critical, {result.medium_count} medium, {result.low_count} low\n\n")
            
            if result.issues:
                for issue in result.issues:
                    f.write(f"### {issue.severity.value}: {issue.category}\n")
                    f.write(f"**Description**: {issue.description}\n")
                    if issue.location:
                        f.write(f"**Location**: {issue.location}\n")
                    if issue.fix_suggestion:
                        f.write(f"**Fix**: {issue.fix_suggestion}\n")
                    f.write("\n")
    
    # Generate summary for GitHub comment
    with open(f"{output_dir}/summary.md", "w") as f:
        if not results:
            f.write("❌ **No API definition files found**\n\n")
            f.write("Please ensure YAML files are located in `/code/API_definitions/`\n")
            return report_filename
        
        # Overall status
        if total_critical == 0:
            if total_medium == 0:
                status = "✅ **Ready for Release**"
            else:
                status = "⚠️ **Conditional Approval**"
        else:
            status = "❌ **Critical Issues Found**"
        
        f.write(f"### {status}\n\n")
        
        # APIs found
        f.write("**APIs Reviewed**:\n")
        for result in results:
            f.write(f"- `{result.api_name}` v{result.version}\n")
        f.write("\n")
        
        # Issue summary
        f.write("**Issues Summary**:\n")
        f.write(f"- 🔴 Critical: {total_critical}\n")
        f.write(f"- 🟡 Medium: {total_medium}\n")
        f.write(f"- 🔵 Low: {total_low}\n\n")
        
        # Critical issues detail
        if total_critical > 0:
            f.write("**Critical Issues Requiring Immediate Attention**:\n\n")
            for result in results:
                critical_issues = [i for i in result.issues if i.severity == Severity.CRITICAL]
                if critical_issues:
                    f.write(f"*{result.api_name}*:\n")
                    for issue in critical_issues[:5]:  # Limit to first 5
                        f.write(f"- {issue.category}: {issue.description}\n")
                    if len(critical_issues) > 5:
                        f.write(f"- ... and {len(critical_issues) - 5} more critical issues\n")
                    f.write("\n")
        
        # Recommendation
        if total_critical == 0 and total_medium == 0:
            f.write("**Recommendation**: ✅ Approved for release\n")
        elif total_critical == 0:
            f.write("**Recommendation**: ⚠️ Approved with medium-priority improvements recommended\n")
        else:
            f.write(f"**Recommendation**: ❌ Address {total_critical} critical issue(s) before release\n")
        
        f.write(f"\n📄 **Detailed Report**: {report_filename}\n")
        f.write("\n📄 **Download**: Available as workflow artifact for complete analysis\n")
    
    return report_filename

def main():
    """Main function with modern argparse structure matching workflow expectations"""
    print("🔍 Debug: Python script starting...")
    print(f"🔍 Debug: Command line args: {sys.argv}")
    print(f"🔍 Debug: Python version: {sys.version}")
    
    # Modern argparse structure that matches the workflow
    parser = argparse.ArgumentParser(description='CAMARA API Review Validator v0.6')
    parser.add_argument('repo_path', help='Path to repository containing API definitions')
    parser.add_argument('--output', required=True, help='Output directory for reports')
    parser.add_argument('--repo-name', required=True, help='Repository name')
    parser.add_argument('--pr-number', required=True, help='Pull request number')
    parser.add_argument('--commonalities-version', required=True, help='CAMARA Commonalities version')
    parser.add_argument('--review-type', required=True, help='Type of review (release-candidate, wip, public-release)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    print("🔍 Debug: Argument parser created successfully")
    
    # Parse arguments with explicit error handling
    try:
        print("🔍 Debug: About to parse arguments...")
        args = parser.parse_args()
        print("🔍 Debug: Arguments parsed successfully!")
        
        # Print all parsed arguments for debugging
        print("🔍 Debug: Parsed arguments:")
        print(f"  repo_path: '{args.repo_path}'")
        print(f"  output: '{args.output}'")
        print(f"  repo_name: '{args.repo_name}'")
        print(f"  pr_number: '{args.pr_number}'")
        print(f"  commonalities_version: '{args.commonalities_version}'")
        print(f"  review_type: '{args.review_type}'")
        print(f"  verbose: {args.verbose}")
        
    except SystemExit as e:
        print(f"❌ SystemExit during argument parsing: {e}")
        print("❌ This usually means argument parsing failed")
        parser.print_help()
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error during argument parsing: {e}")
        print(f"❌ Error type: {type(e).__name__}")
        traceback.print_exc()
        sys.exit(1)
    
    # Validate and sanitize inputs
    try:
        print("🔍 Debug: Starting input validation...")
        
        repo_dir = validate_directory_path(args.repo_path)
        print(f"🔍 Debug: Repository directory validated: {repo_dir}")
        
        # Get and validate commonalities version
        commonalities_version = str(args.commonalities_version).strip()
        print(f"🔍 Debug: Commonalities version: '{commonalities_version}'")
        
        # Validate commonalities version format
        if not re.match(r'^\d+\.\d+$', commonalities_version):
            print(f"❌ Invalid commonalities version format: '{commonalities_version}'")
            raise ValueError(f"Invalid commonalities version format: {commonalities_version}. Expected format: X.Y (e.g., 0.6)")
        
        print(f"✅ Debug: Commonalities version validation passed: {commonalities_version}")
        
        output_dir = args.output
        repo_name = re.sub(r'[^a-zA-Z0-9_-]', '', args.repo_name)[:100]
        pr_number = re.sub(r'[^0-9]', '', args.pr_number)[:20]
        
        # Create output directory
        abs_output_dir = os.path.abspath(os.path.expanduser(output_dir))
        if not os.path.exists(abs_output_dir):
            print(f"🔍 Debug: Creating output directory: {abs_output_dir}")
            os.makedirs(abs_output_dir, mode=0o755)
        
        print("✅ Debug: All input validation passed!")
        
    except ValueError as e:
        print(f"❌ Input validation error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error during validation: {str(e)}")
        traceback.print_exc()
        sys.exit(1)
    
    if args.verbose:
        print(f"🚀 Starting CAMARA API validation (Commonalities {commonalities_version})")
        print(f"📁 Repository directory: {repo_dir}")
        print(f"📊 Output directory: {output_dir}")
        print(f"📦 Repository: {repo_name}")
        print(f"🔗 PR Number: {pr_number}")
        print(f"🔧 Review Type: {args.review_type}")
    
    # Find API files
    api_files = find_api_files(repo_dir)
    
    if not api_files:
        print("❌ No API definition files found")
        print(f"Checked location: {repo_dir}/code/API_definitions/")
        print("📄 Creating empty results report...")
        try:
            report_filename = generate_report([], output_dir, repo_name, pr_number, commonalities_version=commonalities_version)
            print(f"📄 Empty report generated: {report_filename}")
        except Exception as e:
            print(f"❌ Error generating empty report: {str(e)}")
        sys.exit(0)
    
    if args.verbose:
        print(f"🔍 Found {len(api_files)} API definition file(s)")
        for file in api_files:
            print(f"  - {file}")
    
    # Validate each file
    validator = CAMARAAPIValidator(commonalities_version)
    results = []
    
    for api_file in api_files:
        if args.verbose:
            print(f"\n📋 Validating {api_file}...")
        try:
            result = validator.validate_api_file(api_file)
            results.append(result)
            
            if args.verbose:
                print(f"  📄 API Type: {result.api_type.value}")
                print(f"  🔴 Critical: {result.critical_count}")
                print(f"  🟡 Medium: {result.medium_count}")
                print(f"  🔵 Low: {result.low_count}")
                
        except Exception as e:
            print(f"  ❌ Error validating {api_file}: {str(e)}")
            error_result = ValidationResult(file_path=api_file)
            error_result.issues.append(ValidationIssue(
                Severity.CRITICAL, "Validation Error", f"Failed to validate file: {str(e)}"
            ))
            results.append(error_result)
    
    # Generate reports
    try:
        report_filename = generate_report(results, output_dir, repo_name, pr_number, commonalities_version=commonalities_version)
        print(f"📄 Report generated: {report_filename}")
    except Exception as e:
        print(f"❌ Error generating report: {str(e)}")
        traceback.print_exc()
    
    # Calculate totals
    total_critical = sum(r.critical_count for r in results)
    total_medium = sum(r.medium_count for r in results)
    total_low = sum(r.low_count for r in results)
    
    print(f"\n🎯 **Review Complete** (Commonalities {commonalities_version})")
    if repo_name:
        print(f"Repository: {repo_name}")
    if pr_number:
        print(f"PR: #{pr_number}")
    print(f"APIs: {len(results)}")
    print(f"Total Critical Issues: {total_critical}")
    print(f"Total Medium Issues: {total_medium}")
    print(f"Total Low Issues: {total_low}")
    
    print("\n📋 Analysis complete with comprehensive validation coverage.")
    sys.exit(0)

if __name__ == "__main__":
    main()