#!/usr/bin/env python3
"""Benchmark script to compare legacy vs new validator performance"""

import subprocess
import sys
import time
from pathlib import Path


def run_legacy_validator(api_dir: Path, output_dir: Path) -> float:
    """Run legacy validator and return execution time"""
    start = time.time()

    cmd = [
        sys.executable,
        "scripts/api_review_validator_v0_6.py",
        str(api_dir),
        "--output",
        str(output_dir),
        "--repo-name",
        "TestRepo",
        "--commonalities-version",
        "0.6",
        "--review-type",
        "release-candidate",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode not in [0, 1]:  # 0 = no issues, 1 = critical issues
        print(f"Legacy validator failed: {result.stderr}")
        return -1

    return time.time() - start


def run_new_validator(api_dir: Path, output_dir: Path) -> float:
    """Run new validator and return execution time"""
    start = time.time()

    cmd = [
        "camara-validate",
        str(api_dir),
        "--version",
        "0.6",
        "--output",
        str(output_dir),
        "--repo-name",
        "TestRepo",
        "--pr-number",
        "0",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode not in [0, 1]:  # 0 = no issues, 1 = critical issues
        print(f"New validator failed: {result.stderr}")
        return -1

    return time.time() - start


def main():
    """Run benchmark comparison"""
    test_api_dir = Path("scripts/camara-validator/tests/fixtures/valid")
    output_dir = Path("benchmark-output")

    output_dir.mkdir(exist_ok=True)

    print("🏃 Running validator benchmark...")
    print(f"📁 Test directory: {test_api_dir}")

    # Run legacy validator
    print("\n📜 Running legacy validator...")
    legacy_time = run_legacy_validator(test_api_dir, output_dir / "legacy")

    if legacy_time < 0:
        print("❌ Legacy validator failed")
        return 1

    print(f"⏱️  Legacy validator: {legacy_time:.2f} seconds")

    # Run new validator (when implemented)
    try:
        print("\n🆕 Running new validator...")
        new_time = run_new_validator(test_api_dir, output_dir / "new")

        if new_time < 0:
            print("❌ New validator failed")
            return 1

        print(f"⏱️  New validator: {new_time:.2f} seconds")

        # Compare results
        print(f"\n📊 Performance comparison:")
        print(f"   Legacy: {legacy_time:.2f}s")
        print(f"   New:    {new_time:.2f}s")

        if new_time < legacy_time:
            speedup = legacy_time / new_time
            print(f"   🚀 Speedup: {speedup:.2f}x faster")
        else:
            slowdown = new_time / legacy_time
            print(f"   🐌 Slowdown: {slowdown:.2f}x slower")

    except FileNotFoundError:
        print("ℹ️  New validator not yet implemented")

    return 0


if __name__ == "__main__":
    sys.exit(main())
