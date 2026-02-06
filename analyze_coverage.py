#!/usr/bin/env python3
"""
Coverage-based code cleanup analyzer.

After running comprehensive coverage tests, this script helps identify
potentially deletable code by analyzing uncovered lines.
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Set, Tuple


def parse_coverage_json(coverage_file: str = ".coverage") -> Dict:
    """Parse coverage data from .coverage file."""
    try:
        import coverage
        cov = coverage.Coverage(data_file=coverage_file)
        cov.load()
        return cov.get_data()
    except ImportError:
        print("❌ Please install coverage: pip install coverage")
        return None


def get_uncovered_ranges(file_path: str) -> List[Tuple[int, int]]:
    """Get ranges of uncovered lines from coverage report."""
    import subprocess
    
    result = subprocess.run(
        ["coverage", "report", "-m", "--include", file_path],
        capture_output=True,
        text=True
    )
    
    output = result.stdout
    for line in output.split('\n'):
        if file_path in line:
            # Extract the "Missing" column
            parts = line.split()
            if len(parts) > 3:
                missing_str = parts[-1]
                return parse_missing_lines(missing_str)
    return []


def parse_missing_lines(missing_str: str) -> List[Tuple[int, int]]:
    """Parse missing line ranges like '136, 196-198, 205-210' into list of tuples."""
    ranges = []
    for part in missing_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-')
            ranges.append((int(start), int(end)))
        else:
            try:
                num = int(part)
                ranges.append((num, num))
            except ValueError:
                pass
    return ranges


def analyze_code_block(file_path: str, start_line: int, end_line: int) -> Dict:
    """Analyze a block of uncovered code to determine its purpose."""
    with open(file_path, 'r') as f:
        lines = f.readlines()
    
    # Get the block
    block = lines[start_line-1:end_line]
    block_text = ''.join(block)
    
    # Analyze patterns
    analysis = {
        'start': start_line,
        'end': end_line,
        'size': end_line - start_line + 1,
        'category': 'unknown',
        'confidence': 'low',
        'reason': ''
    }
    
    # Pattern detection
    if 'except' in block_text or 'raise' in block_text:
        analysis['category'] = 'error_handling'
        analysis['confidence'] = 'high'
        analysis['reason'] = 'Contains exception handling - likely needed for error cases'
    
    elif 'TODO' in block_text or 'FIXME' in block_text or 'XXX' in block_text:
        analysis['category'] = 'todo'
        analysis['confidence'] = 'medium'
        analysis['reason'] = 'Contains TODO/FIXME comment - possibly unfinished'
    
    elif 'deprecated' in block_text.lower() or 'legacy' in block_text.lower():
        analysis['category'] = 'deprecated'
        analysis['confidence'] = 'high'
        analysis['reason'] = 'Marked as deprecated/legacy - candidate for removal'
    
    elif re.search(r'def\s+_\w+', block_text):  # private methods
        analysis['category'] = 'private_unused'
        analysis['confidence'] = 'medium'
        analysis['reason'] = 'Private method never called - check if used elsewhere'
    
    elif 'if __name__' in block_text:
        analysis['category'] = 'main_block'
        analysis['confidence'] = 'low'
        analysis['reason'] = 'Main block - only runs when file executed directly'
    
    elif block_text.strip().startswith('#'):
        analysis['category'] = 'comment_only'
        analysis['confidence'] = 'high'
        analysis['reason'] = 'Comment-only block'
    
    elif 'logger' in block_text.lower() or 'debug' in block_text.lower():
        analysis['category'] = 'debug_logging'
        analysis['confidence'] = 'medium'
        analysis['reason'] = 'Debug/logging code - may only run in debug mode'
    
    return analysis


def generate_cleanup_report(file_path: str):
    """Generate a cleanup report for a file based on coverage."""
    
    print(f"\n{'='*70}")
    print(f"📊 COVERAGE-BASED CLEANUP ANALYSIS")
    print(f"{'='*70}")
    print(f"File: {file_path}\n")
    
    # Get uncovered ranges
    ranges = get_uncovered_ranges(file_path)
    
    if not ranges:
        print("✅ No coverage data found or file fully covered!")
        return
    
    # Categorize blocks
    categories = {
        'deprecated': [],
        'todo': [],
        'error_handling': [],
        'private_unused': [],
        'debug_logging': [],
        'unknown': []
    }
    
    total_uncovered = 0
    
    for start, end in ranges:
        if end - start > 5:  # Only analyze blocks larger than 5 lines
            analysis = analyze_code_block(file_path, start, end)
            category = analysis['category']
            categories[category].append(analysis)
            total_uncovered += analysis['size']
    
    # Print results
    print(f"📈 Total uncovered line ranges: {len(ranges)}")
    print(f"📦 Large blocks analyzed: {sum(len(v) for v in categories.values())}\n")
    
    # Deprecated/Legacy code (HIGH PRIORITY)
    if categories['deprecated']:
        print("🔴 HIGH PRIORITY - Deprecated/Legacy Code (Safe to Remove)")
        print("-" * 70)
        for block in categories['deprecated']:
            print(f"  Lines {block['start']}-{block['end']} ({block['size']} lines)")
            print(f"    → {block['reason']}\n")
    
    # TODO/Unfinished code
    if categories['todo']:
        print("🟡 MEDIUM PRIORITY - Unfinished Code (Review & Complete or Remove)")
        print("-" * 70)
        for block in categories['todo']:
            print(f"  Lines {block['start']}-{block['end']} ({block['size']} lines)")
            print(f"    → {block['reason']}\n")
    
    # Unused private methods
    if categories['private_unused']:
        print("🟡 MEDIUM PRIORITY - Unused Private Methods (Verify & Remove)")
        print("-" * 70)
        for block in categories['private_unused']:
            print(f"  Lines {block['start']}-{block['end']} ({block['size']} lines)")
            print(f"    → {block['reason']}\n")
    
    # Error handling (KEEP)
    if categories['error_handling']:
        print("🟢 LOW PRIORITY - Error Handling (Keep)")
        print("-" * 70)
        print(f"  Found {len(categories['error_handling'])} error handling blocks")
        print("  → These are needed for production resilience\n")
    
    # Debug/Logging (REVIEW)
    if categories['debug_logging']:
        print("🔵 LOW PRIORITY - Debug/Logging Code (Review)")
        print("-" * 70)
        for block in categories['debug_logging']:
            print(f"  Lines {block['start']}-{block['end']} ({block['size']} lines)")
            print(f"    → {block['reason']}\n")
    
    # Unknown
    if categories['unknown']:
        print("⚪ UNKNOWN - Manual Review Required")
        print("-" * 70)
        for block in categories['unknown']:
            print(f"  Lines {block['start']}-{block['end']} ({block['size']} lines)")
            print(f"    → Requires manual inspection\n")
    
    print("="*70)
    print("\n💡 Next Steps:")
    print("  1. Review HIGH PRIORITY items first (deprecated code)")
    print("  2. Check MEDIUM PRIORITY items (TODOs, unused methods)")
    print("  3. Keep LOW PRIORITY items (error handling)")
    print("  4. Manually inspect UNKNOWN blocks")
    print("\n⚠️  Always verify before deleting:")
    print("  - Search for function/class references across codebase")
    print("  - Check if used by other services/APIs")
    print("  - Review git history for context")
    print()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = "hosts/multiagent/foundry_agent_a2a.py"
    
    generate_cleanup_report(file_path)
