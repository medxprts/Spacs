#!/usr/bin/env python3
"""
Bulk Update Sponsor Aliases from Existing Mappings
===================================================
Uses sponsor_family_mappings.json to add comprehensive aliases to sponsor_performance table.

Much faster than AI approach - directly uses existing manual mappings.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, engine
from sqlalchemy import text
import json

def load_family_mappings():
    """Load existing sponsor family mappings"""
    with open('/home/ubuntu/spac-research/sponsor_family_mappings.json', 'r') as f:
        mappings = json.load(f)

    # Group by family
    families = {}
    for entry in mappings:
        family = entry['new_normalized']
        sponsor = entry['sponsor']

        if family not in families:
            families[family] = set()

        families[family].add(sponsor)

    return families


def add_aliases_to_performance_table(family_name, aliases):
    """Add aliases to sponsor_performance table"""
    with engine.connect() as conn:
        # Try to find matching sponsor by name or fuzzy match
        result = conn.execute(
            text("SELECT sponsor_name, sponsor_aliases FROM sponsor_performance WHERE LOWER(sponsor_name) LIKE :pattern LIMIT 1"),
            {'pattern': f'%{family_name.lower()}%'}
        ).fetchone()

        if result:
            perf_sponsor_name, current_aliases = result
            current_aliases = current_aliases or []

            # Merge aliases
            all_aliases = list(set(current_aliases + list(aliases)))

            conn.execute(text("""
                UPDATE sponsor_performance
                SET sponsor_aliases = :aliases
                WHERE sponsor_name = :name
            """), {
                'aliases': all_aliases,
                'name': perf_sponsor_name
            })
            conn.commit()

            return perf_sponsor_name, len(all_aliases) - len(current_aliases)
        else:
            return None, 0


def main():
    print("="*80)
    print("BULK UPDATE SPONSOR ALIASES FROM EXISTING MAPPINGS")
    print("="*80)

    # Load family mappings
    print("\n📁 Loading sponsor family mappings...")
    families = load_family_mappings()
    print(f"   Found {len(families)} sponsor families")

    # Update each family
    print("\n🔄 Updating sponsor_performance table...\n")

    updated_count = 0
    total_aliases_added = 0
    not_found = []

    for family_name, sponsors in sorted(families.items()):
        perf_name, aliases_added = add_aliases_to_performance_table(family_name, sponsors)

        if perf_name:
            print(f"✅ {family_name:40s} → {perf_name:30s} (+{aliases_added} aliases)")
            updated_count += 1
            total_aliases_added += aliases_added
        else:
            print(f"⚠️  {family_name:40s} → Not found in performance table")
            not_found.append(family_name)

    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"  Total families: {len(families)}")
    print(f"  Updated: {updated_count}")
    print(f"  Not found: {len(not_found)}")
    print(f"  Total aliases added: {total_aliases_added}")
    print(f"{'='*80}")

    if not_found:
        print(f"\n⚠️  Families not found in performance table:")
        for family in not_found[:10]:
            print(f"   - {family}")
        if len(not_found) > 10:
            print(f"   ... and {len(not_found) - 10} more")

    # Show top families by alias count
    print("\n🏆 TOP SPONSOR FAMILIES BY ALIAS COUNT:")
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT sponsor_name,
                   array_length(sponsor_aliases, 1) as alias_count,
                   sponsor_score,
                   performance_tier
            FROM sponsor_performance
            WHERE sponsor_aliases IS NOT NULL
            ORDER BY array_length(sponsor_aliases, 1) DESC
            LIMIT 15
        """))

        for row in result:
            name, count, score, tier = row
            print(f"  {name[:35]:35s} | {count:3d} aliases | {score:2d}/15 ({tier})")


if __name__ == '__main__':
    main()
