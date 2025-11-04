#!/usr/bin/env python3
"""
Show Learning Stats

Quick script to see what correction data is available for self-learning.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from agents.self_learning_mixin import SelfLearningMixin


class StatsViewer(SelfLearningMixin):
    """Simple viewer for learning stats"""
    pass


def main():
    viewer = StatsViewer()

    print("="*60)
    print("SELF-LEARNING DATA AVAILABLE")
    print("="*60)

    stats = viewer.get_learning_stats()

    print(f"\n📊 Total corrections with learning notes: {stats.get('total_corrections', 0)}")

    print(f"\n📋 Corrections by issue type:")
    for issue_type, count in stats.get('corrections_by_issue', {}).items():
        print(f"   {issue_type:30s}: {count:3d}")

    print(f"\n🎯 Most corrected fields:")
    for field, count in stats.get('top_corrected_fields', {}).items():
        print(f"   {field:30s}: {count:3d}")

    # Show sample corrections for each field
    print(f"\n📝 Sample corrections available:")
    top_fields = list(stats.get('top_corrected_fields', {}).keys())[:3]

    for field in top_fields:
        examples = viewer.get_relevant_corrections(field, limit=1)
        if examples:
            ex = examples[0]
            print(f"\n   Field: {field}")
            print(f"   Example from {ex['ticker']}: {ex['learning_notes'][:80]}...")


if __name__ == '__main__':
    main()
