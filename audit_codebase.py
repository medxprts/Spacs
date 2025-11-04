#!/usr/bin/env python3
"""
Codebase Audit Tool - Identify unused, deprecated, and duplicate code

Usage:
    python3 audit_codebase.py --report all
    python3 audit_codebase.py --report unused
    python3 audit_codebase.py --report duplicates
"""

import os
import ast
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import argparse

# Directories to exclude from audit
EXCLUDE_DIRS = {
    'venv', '.venv', '__pycache__', '.git', 'archive', 'archives',
    'deprecated', 'node_modules', '.pytest_cache', 'htmlcov'
}

# Known entry points (scripts that are run directly)
ENTRY_POINTS = {
    'agent_orchestrator.py',
    'price_updater.py',
    'streamlit_app.py',
    'main.py',  # FastAPI
    'sec_data_scraper.py',
    'deal_monitor_enhanced.py',
    'price_spike_monitor.py',
    'reddit_sentiment_tracker.py',
    'telegram_approval_listener.py',
    'warrant_price_fetcher.py',
}

class CodebaseAuditor:
    def __init__(self, root_dir='.'):
        self.root_dir = Path(root_dir)
        self.python_files = []
        self.imports_map = defaultdict(set)  # file -> set of imported modules
        self.imported_by = defaultdict(set)  # module -> set of files that import it
        self.file_info = {}  # file -> {size, lines, last_modified}

    def scan_files(self):
        """Scan all Python files in the codebase"""
        print("🔍 Scanning Python files...")

        for path in self.root_dir.rglob('*.py'):
            # Skip excluded directories
            if any(excl in path.parts for excl in EXCLUDE_DIRS):
                continue

            rel_path = path.relative_to(self.root_dir)
            self.python_files.append(rel_path)

            # Get file info
            stats = path.stat()
            self.file_info[str(rel_path)] = {
                'size': stats.st_size,
                'last_modified': datetime.fromtimestamp(stats.st_mtime),
                'lines': sum(1 for _ in open(path, 'r', encoding='utf-8', errors='ignore'))
            }

        print(f"   Found {len(self.python_files)} Python files")

    def analyze_imports(self):
        """Analyze import relationships"""
        print("🔍 Analyzing imports...")

        for file_path in self.python_files:
            full_path = self.root_dir / file_path

            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    tree = ast.parse(f.read(), filename=str(file_path))

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            module = alias.name.split('.')[0]
                            self.imports_map[str(file_path)].add(module)

                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            module = node.module.split('.')[0]
                            self.imports_map[str(file_path)].add(module)

            except SyntaxError:
                pass  # Skip files with syntax errors

        # Build reverse mapping
        for file_path in self.python_files:
            module_name = str(file_path).replace('/', '.').replace('.py', '')
            # Also check short name
            short_name = file_path.stem

            for importer, imports in self.imports_map.items():
                if module_name in imports or short_name in imports:
                    self.imported_by[str(file_path)].add(importer)

    def find_unused_files(self):
        """Find files that are never imported and not entry points"""
        print("\n📊 UNUSED FILES (never imported, not entry points)")
        print("=" * 80)

        unused = []
        for file_path in self.python_files:
            file_name = Path(file_path).name

            # Skip entry points
            if file_name in ENTRY_POINTS:
                continue

            # Skip test files (they're not imported)
            if file_name.startswith('test_') or 'test' in str(file_path):
                continue

            # Skip __init__.py files
            if file_name == '__init__.py':
                continue

            # Check if imported by anything
            if str(file_path) not in self.imported_by or len(self.imported_by[str(file_path)]) == 0:
                info = self.file_info[str(file_path)]
                unused.append((file_path, info))

        # Sort by last modified (oldest first)
        unused.sort(key=lambda x: x[1]['last_modified'])

        for file_path, info in unused:
            days_old = (datetime.now() - info['last_modified']).days
            print(f"\n   {file_path}")
            print(f"      Lines: {info['lines']:,} | Size: {info['size']:,} bytes | Last modified: {days_old} days ago")

        print(f"\n   Total: {len(unused)} potentially unused files")
        return unused

    def find_old_files(self, days=90):
        """Find files not modified in X days"""
        print(f"\n📊 OLD FILES (not modified in {days} days)")
        print("=" * 80)

        cutoff = datetime.now() - timedelta(days=days)
        old_files = []

        for file_path in self.python_files:
            info = self.file_info[str(file_path)]

            if info['last_modified'] < cutoff:
                days_old = (datetime.now() - info['last_modified']).days
                old_files.append((file_path, info, days_old))

        # Sort by age
        old_files.sort(key=lambda x: x[2], reverse=True)

        for file_path, info, days_old in old_files[:20]:  # Show top 20
            print(f"\n   {file_path}")
            print(f"      Last modified: {days_old} days ago ({info['last_modified'].strftime('%Y-%m-%d')})")
            print(f"      Lines: {info['lines']:,} | Size: {info['size']:,} bytes")

        print(f"\n   Total: {len(old_files)} files not modified in {days}+ days")
        return old_files

    def find_duplicate_names(self):
        """Find files with similar names (might indicate duplication)"""
        print("\n📊 DUPLICATE/SIMILAR FILE NAMES")
        print("=" * 80)

        name_groups = defaultdict(list)

        for file_path in self.python_files:
            # Group by stem (filename without extension)
            stem = Path(file_path).stem
            # Normalize: remove test_, _test, _old, _new, _v2, etc
            normalized = stem.lower()
            for suffix in ['_test', 'test_', '_old', '_new', '_v2', '_backup', '_copy']:
                normalized = normalized.replace(suffix, '')

            if normalized:
                name_groups[normalized].append(file_path)

        # Show groups with multiple files
        duplicates = {k: v for k, v in name_groups.items() if len(v) > 1}

        for normalized_name, files in sorted(duplicates.items()):
            print(f"\n   '{normalized_name}' variations:")
            for f in files:
                info = self.file_info[str(f)]
                print(f"      - {f} ({info['lines']:,} lines)")

        print(f"\n   Total: {len(duplicates)} groups of similar filenames")
        return duplicates

    def find_large_files(self, min_lines=500):
        """Find very large files (might need refactoring)"""
        print(f"\n📊 LARGE FILES (>{min_lines} lines)")
        print("=" * 80)

        large = []
        for file_path in self.python_files:
            info = self.file_info[str(file_path)]
            if info['lines'] > min_lines:
                large.append((file_path, info))

        # Sort by size
        large.sort(key=lambda x: x[1]['lines'], reverse=True)

        for file_path, info in large[:20]:  # Top 20
            print(f"\n   {file_path}")
            print(f"      Lines: {info['lines']:,} | Size: {info['size']:,} bytes")

        print(f"\n   Total: {len(large)} files with >{min_lines} lines")
        return large

    def find_entry_point_coverage(self):
        """Check which files are reachable from entry points"""
        print("\n📊 ENTRY POINT COVERAGE")
        print("=" * 80)

        reachable = set()

        def traverse(file_path, visited=None):
            if visited is None:
                visited = set()

            if file_path in visited:
                return

            visited.add(file_path)
            reachable.add(file_path)

            # Find what this file imports
            for imported in self.imports_map.get(file_path, []):
                # Find matching file
                for py_file in self.python_files:
                    if imported in str(py_file):
                        traverse(str(py_file), visited)

        # Start from each entry point
        for entry in ENTRY_POINTS:
            for file_path in self.python_files:
                if file_path.name == entry:
                    traverse(str(file_path))

        unreachable = set(str(f) for f in self.python_files) - reachable

        # Filter out tests and __init__
        unreachable = {f for f in unreachable if not Path(f).name.startswith('test_')
                       and Path(f).name != '__init__.py'}

        print(f"\n   Entry points: {len(ENTRY_POINTS)}")
        print(f"   Reachable files: {len(reachable)}")
        print(f"   Unreachable files: {len(unreachable)}")

        if unreachable:
            print("\n   Unreachable files:")
            for f in sorted(unreachable)[:20]:  # Show first 20
                print(f"      - {f}")

        return unreachable

    def generate_summary(self):
        """Generate overall summary"""
        print("\n" + "=" * 80)
        print("📊 CODEBASE SUMMARY")
        print("=" * 80)

        total_lines = sum(info['lines'] for info in self.file_info.values())
        total_size = sum(info['size'] for info in self.file_info.values())

        print(f"\n   Total Python files: {len(self.python_files):,}")
        print(f"   Total lines of code: {total_lines:,}")
        print(f"   Total size: {total_size / 1024 / 1024:.2f} MB")
        print(f"   Average file size: {total_lines / len(self.python_files):.0f} lines")

        # Files by directory
        dir_counts = defaultdict(int)
        for f in self.python_files:
            if f.parent == Path('.'):
                dir_counts['root'] += 1
            else:
                dir_counts[str(f.parts[0])] += 1

        print("\n   Files by directory:")
        for dir_name, count in sorted(dir_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"      {dir_name}: {count} files")

def main():
    parser = argparse.ArgumentParser(description='Audit codebase for unused/deprecated code')
    parser.add_argument('--report', choices=['all', 'unused', 'old', 'duplicates', 'large', 'coverage', 'summary'],
                        default='all', help='Type of report to generate')
    parser.add_argument('--days', type=int, default=90, help='Days threshold for old files')
    parser.add_argument('--lines', type=int, default=500, help='Line threshold for large files')

    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("🔍 CODEBASE AUDIT TOOL")
    print("=" * 80)

    auditor = CodebaseAuditor()
    auditor.scan_files()
    auditor.analyze_imports()

    if args.report == 'all':
        auditor.find_unused_files()
        auditor.find_old_files(args.days)
        auditor.find_duplicate_names()
        auditor.find_large_files(args.lines)
        auditor.find_entry_point_coverage()
        auditor.generate_summary()
    elif args.report == 'unused':
        auditor.find_unused_files()
    elif args.report == 'old':
        auditor.find_old_files(args.days)
    elif args.report == 'duplicates':
        auditor.find_duplicate_names()
    elif args.report == 'large':
        auditor.find_large_files(args.lines)
    elif args.report == 'coverage':
        auditor.find_entry_point_coverage()
    elif args.report == 'summary':
        auditor.generate_summary()

    print("\n" + "=" * 80)
    print("✅ Audit complete!")
    print("=" * 80 + "\n")

if __name__ == '__main__':
    main()
