#!/usr/bin/env python3
"""
Update Sponsor Aliases from Known Deal History
===============================================
Uses repeat_sponsor_deals.csv to add comprehensive aliases to sponsor_performance table.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import engine
from sqlalchemy import text
import csv

# Manual mapping of sponsor families to their performance database names
FAMILY_TO_PERFORMANCE = {
    "Churchill Capital": "Churchill Capital",
    "Gores (Holdings)": "The Gores Group",
    "Eagle (Sloan & Sagansky)": "Eagle (Jeff Sagansky)",
    "dMY Technology Group": "dMY Technology Group",
    "Reinvent Technology Partners": "Reinvent Technology Partners",
    "Oaktree Capital": "Oaktree Capital",
    "NGP / Switchback": "NGP Energy Capital",
    "TortoiseEcofin": "TortoiseEcofin",
    "Horizon (Boehly)": "Horizon (Boehly)",
    "Rice Acquisition (Rice Brothers)": "Rice Acquisition",
    "Social Capital Hedosophia": "Social Capital Hedosophia",
    "Cantor / CF Acquisition": "Cantor Fitzgerald",
    "Dragoneer": "Dragoneer",
    "Khosla Ventures": "Khosla Ventures",
    "JAWS (Sternlicht)": "JAWS",
    "CC Neuberger / CC Capital": "CC Neuberger / CC Capital",
    "Hennessy Capital": "Hennessy Capital",
    "GigCapital": "GigCapital",
    "Horizon Space Acquisition": "Horizon Space",
    "Live Oak": "Live Oak",
    "Lionheart": "Lionheart",
    "Andretti": "Andretti",
    "Aldel": "Aldel",
    "Perceptive / Arya": "Perceptive",
    "Oyster": "Oyster",
    "ST Sponsor": "ST Sponsor",
    "AA Mission": "AA Mission",
    "Republic Capital": "Republic Capital",
    "Archimedes": "Archimedes",
    "DT Cloud": "DT Cloud",
    "TV Partners": "TV Partners",
    "RJ Healthcare": "RJ Healthcare",
    "Trailblazer": "Trailblazer"
}

def load_repeat_sponsors():
    """Load repeat sponsor deals from CSV"""
    deals_by_family = {}

    with open('/home/ubuntu/spac-research/data/repeat_sponsor_deals.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            family = row['Sponsor Family']
            spac_name = row['SPAC']

            if family not in deals_by_family:
                deals_by_family[family] = set()

            deals_by_family[family].add(spac_name)

    return deals_by_family


def update_aliases(performance_name, aliases):
    """Add aliases to sponsor_performance table"""
    with engine.connect() as conn:
        # Check if sponsor exists
        result = conn.execute(
            text("SELECT sponsor_name, sponsor_aliases FROM sponsor_performance WHERE sponsor_name = :name"),
            {'name': performance_name}
        ).fetchone()

        if result:
            current_aliases = result[1] or []

            # Merge with new aliases
            all_aliases = list(set(current_aliases + list(aliases)))

            conn.execute(text("""
                UPDATE sponsor_performance
                SET sponsor_aliases = :aliases
                WHERE sponsor_name = :name
            """), {
                'aliases': all_aliases,
                'name': performance_name
            })
            conn.commit()

            return len(all_aliases) - len(current_aliases)
        else:
            # Try fuzzy match
            result = conn.execute(
                text("SELECT sponsor_name, sponsor_aliases FROM sponsor_performance WHERE LOWER(sponsor_name) LIKE :pattern LIMIT 1"),
                {'pattern': f'%{performance_name.lower()}%'}
            ).fetchone()

            if result:
                perf_name, current_aliases = result
                current_aliases = current_aliases or []

                all_aliases = list(set(current_aliases + list(aliases)))

                conn.execute(text("""
                    UPDATE sponsor_performance
                    SET sponsor_aliases = :aliases
                    WHERE sponsor_name = :name
                """), {
                    'aliases': all_aliases,
                    'name': perf_name
                })
                conn.commit()

                return len(all_aliases) - len(current_aliases)
            else:
                return -1


def main():
    print("="*80)
    print("UPDATE SPONSOR ALIASES FROM KNOWN DEAL HISTORY")
    print("="*80)

    # Load repeat sponsors
    print("\n📁 Loading repeat sponsor deals...")
    deals_by_family = load_repeat_sponsors()
    print(f"   Found {len(deals_by_family)} sponsor families")

    # Update each family
    print("\n🔄 Updating sponsor_performance aliases...\n")

    updated_count = 0
    total_aliases = 0
    not_found = []

    for family, spac_names in sorted(deals_by_family.items()):
        # Get performance database name
        perf_name = FAMILY_TO_PERFORMANCE.get(family, family)

        # Add aliases
        aliases_added = update_aliases(perf_name, spac_names)

        if aliases_added >= 0:
            print(f"✅ {family:40s} → {perf_name:30s} (+{aliases_added} aliases)")
            updated_count += 1
            total_aliases += aliases_added
        else:
            print(f"⚠️  {family:40s} → Not in performance DB")
            not_found.append(family)

    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"  Families processed: {len(deals_by_family)}")
    print(f"  Updated: {updated_count}")
    print(f"  Not found: {len(not_found)}")
    print(f"  Total aliases added: {total_aliases}")
    print(f"{'='*80}")

    if not_found:
        print(f"\n⚠️  Families not in performance database:")
        for family in not_found:
            print(f"   - {family}")

    # Show updated sponsor families
    print("\n🏆 UPDATED SPONSOR FAMILIES (with alias counts):\n")
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT sponsor_name,
                   array_length(sponsor_aliases, 1) as alias_count,
                   sponsor_score,
                   performance_tier
            FROM sponsor_performance
            WHERE sponsor_aliases IS NOT NULL
              AND array_length(sponsor_aliases, 1) > 2
            ORDER BY array_length(sponsor_aliases, 1) DESC
            LIMIT 20
        """))

        for row in result:
            name, count, score, tier = row
            print(f"  {name[:35]:35s} | {count:3d} aliases | {score:2d}/15 ({tier})")


if __name__ == '__main__':
    main()
