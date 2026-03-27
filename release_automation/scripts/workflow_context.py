#!/usr/bin/env python3
"""
Script to assemble the "Golden Context" for the release automation workflow.

This script aggregates data from various workflow steps (trigger, derive-state)
and constructs a unified BotContext JSON object. This object is then used
by all downstream jobs for templating and logic, ensuring consistency.

Usage:
    python workflow_context.py --output json
"""

import argparse
import json
import os
import sys

# Ensure we can import from local modules
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

from release_automation.scripts.context_builder import build_context

def main():
    parser = argparse.ArgumentParser(description="Assemble workflow context")
    parser.add_argument("--output-file", help="Path to write output JSON to", default=None)
    args = parser.parse_args()

    # Read inputs from environment variables (populated by workflow inputs)
    # We use environment variables to avoid massive CLI argument lists
    
    # helper to parse JSON list safely
    def parse_json_list(json_str):
        if not json_str:
            return []
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            print(f"::warning::Failed to parse JSON list: {json_str}", file=sys.stderr)
            return []

    context_data = {
        # Trigger metadata
        "command": os.environ.get("CTX_COMMAND", ""),
        "command_args": os.environ.get("CTX_COMMAND_ARGS", ""),
        "user": os.environ.get("CTX_USER", ""),
        "trigger_type": os.environ.get("CTX_TRIGGER_TYPE", ""),

        # Release identity (from derive-state)
        "release_tag": os.environ.get("CTX_RELEASE_TAG", ""),
        "state": os.environ.get("CTX_STATE", ""),
        "release_type": os.environ.get("CTX_RELEASE_TYPE", ""),
        "meta_release": os.environ.get("CTX_META_RELEASE", ""),

        # Snapshot details
        "snapshot_id": os.environ.get("CTX_SNAPSHOT_ID", ""),
        "snapshot_branch": os.environ.get("CTX_SNAPSHOT_BRANCH", ""),
        "release_review_branch": os.environ.get("CTX_RELEASE_REVIEW_BRANCH", ""),
        "release_pr_number": os.environ.get("CTX_RELEASE_PR_NUMBER", ""),
        "release_pr_url": f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}/pull/{os.environ.get('CTX_RELEASE_PR_NUMBER', '')}" if os.environ.get("CTX_RELEASE_PR_NUMBER") else "",
        "src_commit_sha": os.environ.get("CTX_SRC_COMMIT_SHA", ""), # Not in BotContext directly? Check.
        
        # Trigger PR (for push events — PR that triggered the release-plan.yaml change)
        "trigger_pr_number": os.environ.get("CTX_TRIGGER_PR_NUMBER", ""),
        "trigger_pr_url": os.environ.get("CTX_TRIGGER_PR_URL", ""),

        # Dependencies
        "commonalities_release": os.environ.get("CTX_COMMONALITIES_RELEASE", ""),
        "identity_consent_management_release": os.environ.get("CTX_IDENTITY_CONSENT_MANAGEMENT_RELEASE", ""),

        # Lists
        "apis": parse_json_list(os.environ.get("CTX_APIS_JSON", "[]")),
        
        # Derived/Extra
        "workflow_run_url": f"{os.environ.get('GITHUB_SERVER_URL', '')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}",
        "repository": os.environ.get("GITHUB_REPOSITORY", ""),
    }
    
    # Log inputs for debugging
    print("Building context with inputs:", file=sys.stderr)
    for k, v in context_data.items():
        if k != "apis":
            print(f"  {k}: {v}", file=sys.stderr)

    # Build the context using the shared builder
    # build_context handles deriving flags like is_snapshot_active, etc.
    full_context = build_context(**context_data)
    
    # Output
    json_output = json.dumps(full_context, indent=2)
    
    if args.output_file:
        with open(args.output_file, "w") as f:
            f.write(json_output)
    else:
        print(json_output)

    # Also write to GITHUB_OUTPUT if available
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            # We output the whole context as a single JSON string
            # This allows downstream jobs to use ${{ fromJson(needs.ctx.outputs.json) }}
            # Use distinct delimiter to handle potential multiline JSON
            import uuid
            delimiter = f"EOF-{uuid.uuid4()}"
            f.write(f"base_context<<{delimiter}\n")
            f.write(json_output)
            f.write(f"\n{delimiter}\n")

if __name__ == "__main__":
    main()
