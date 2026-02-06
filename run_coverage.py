#!/usr/bin/env python3
"""
Coverage Analysis Runner for foundry_agent_a2a.py

This script runs existing tests while measuring code coverage for the
foundry_agent_a2a module.

Usage:
    python run_coverage.py              # Run all tests with coverage
    python run_coverage.py --html       # Generate HTML report
    python run_coverage.py --report     # Show coverage report
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description):
    """Run a shell command and print status"""
    print(f"\n{'='*70}")
    print(f"🔍 {description}")
    print(f"{'='*70}")
    result = subprocess.run(cmd, shell=True)
    return result.returncode

def main():
    # Change to project root
    project_root = Path(__file__).parent
    os.chdir(project_root)
    
    print("🎯 Coverage Analysis for foundry_agent_a2a.py")
    print("=" * 70)
    
    # Check if backend tests exist
    tests_dir = project_root / "backend" / "tests"
    if not tests_dir.exists():
        print(f"❌ Tests directory not found: {tests_dir}")
        sys.exit(1)
    
    # Step 1: Clear any previous coverage data
    run_command("coverage erase", "Clearing previous coverage data")
    
    # Step 2: Run tests with coverage
    # Note: You'll need to run actual tests that exercise foundry_agent_a2a.py
    # For now, let's just measure what's imported
    test_files = [
        "backend/tests/test_workflow_execution.py",
        "backend/tests/test_multiagent_flows.py",
        "backend/tests/test_workflow_parallel_execution.py",
    ]
    
    print("\n📊 Running tests with coverage measurement...")
    print("Note: Make sure backend services are running for integration tests")
    print("\nPress Ctrl+C if services aren't running, or wait to continue...")
    
    try:
        import time
        time.sleep(3)
    except KeyboardInterrupt:
        print("\n\n⚠️  Coverage analysis cancelled")
        print("\nTo run coverage properly:")
        print("  1. Start backend: cd backend && python backend_production.py")
        print("  2. Start websocket: cd backend && python start_websocket.py")
        print("  3. Run this script again")
        sys.exit(0)
    
    # Run coverage on test files
    for test_file in test_files:
        if Path(test_file).exists():
            returncode = run_command(
                f"coverage run --append -m pytest {test_file} -v || true",
                f"Running {test_file}"
            )
    
    # Step 3: Generate reports
    print("\n" + "="*70)
    print("📈 Generating Coverage Reports")
    print("="*70)
    
    # Terminal report
    run_command("coverage report", "Coverage Summary Report")
    
    # HTML report
    run_command("coverage html", "Generating HTML Report")
    
    print("\n" + "="*70)
    print("✅ Coverage Analysis Complete!")
    print("="*70)
    print(f"\n📁 HTML Report: file://{project_root}/htmlcov/index.html")
    print(f"📊 Coverage Report: Run 'coverage report' to see again")
    print("\nTo view detailed HTML report:")
    print("    open htmlcov/index.html")

if __name__ == "__main__":
    main()
