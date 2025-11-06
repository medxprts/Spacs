#!/usr/bin/env python3
"""
Apply Sponsor Family Mapping

Uses seed file of known sponsor families to improve sponsor grouping.
Maps database sponsors to canonical family names.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
import json
from typing import Dict, List, Optional


class SponsorFamilyMapper:
    """Map database sponsors to known sponsor families"""

    def __init__(self):
        self.db = SessionLocal()
        self.families = self._load_seed_file()

    def close(self):
        self.db.close()

    def _load_seed_file(self) -> List[Dict]:
        """Load sponsor families seed file"""
        with open('data/sponsor_families_seed.json', 'r') as f:
            return json.load(f)

    def find_family(self, sponsor_name: str) -> Optional[Dict]:
        """Find which family a sponsor belongs to"""
        if not sponsor_name:
            return None

        sponsor_lower = sponsor_name.lower()

        # Check each family
        for family in self.families:
            # Check sponsor_variations
            for variation in family['sponsor_variations']:
                if variation.lower() in sponsor_lower:
                    return family

            # Check principals (for cases like "Michael Klein" in sponsor name)
            for principal in family['principals']:
                if principal.lower() in sponsor_lower:
                    return family

            # Check family name itself
            family_name_lower = family['family_name'].lower()
            # Remove common words for matching
            family_core = family_name_lower.replace('the ', '').replace(' group', '').replace(' capital', '')
            if family_core in sponsor_lower:
                return family

        return None

    def apply_to_database(self, commit: bool = False) -> Dict:
        """Apply family mapping to all SPACs in database"""

        spacs = self.db.query(SPAC).filter(SPAC.sponsor != None).all()

        stats = {
            'total': len(spacs),
            'mapped': 0,
            'unmapped': 0,
            'families_found': set(),
            'mappings': []
        }

        print(f"Processing {len(spacs)} SPACs with sponsors...")
        print("=" * 80)

        for spac in spacs:
            family = self.find_family(spac.sponsor)

            if family:
                old_normalized = spac.sponsor_normalized
                new_normalized = family['family_name']

                # Update sponsor_normalized to family name
                spac.sponsor_normalized = new_normalized

                stats['mapped'] += 1
                stats['families_found'].add(new_normalized)
                stats['mappings'].append({
                    'ticker': spac.ticker,
                    'sponsor': spac.sponsor,
                    'old_normalized': old_normalized,
                    'new_normalized': new_normalized,
                    'principals': family['principals']
                })
            else:
                stats['unmapped'] += 1

        # Show summary
        print(f"\nResults:")
        print(f"  Total SPACs: {stats['total']}")
        print(f"  ✅ Mapped to families: {stats['mapped']}")
        print(f"  ⚠️  No family match: {stats['unmapped']}")
        print(f"  📊 Unique families: {len(stats['families_found'])}")

        # Show top families
        family_counts = {}
        for mapping in stats['mappings']:
            family = mapping['new_normalized']
            family_counts[family] = family_counts.get(family, 0) + 1

        print(f"\nTop 10 Families:")
        for family, count in sorted(family_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {count:2d} SPACs: {family}")

        # Show sample mappings
        print(f"\nSample Mappings:")
        for mapping in stats['mappings'][:5]:
            print(f"  {mapping['ticker']}: '{mapping['sponsor']}' → '{mapping['new_normalized']}'")
            print(f"           Principals: {', '.join(mapping['principals'])}")

        if commit:
            self.db.commit()
            print(f"\n✅ Committed {stats['mapped']} sponsor family mappings to database")
        else:
            self.db.rollback()
            print(f"\nℹ️  DRY RUN - Use --commit to save changes")

        return stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Apply sponsor family mappings to database')
    parser.add_argument('--commit', action='store_true', help='Commit changes to database')
    args = parser.parse_args()

    mapper = SponsorFamilyMapper()

    try:
        stats = mapper.apply_to_database(commit=args.commit)

        # Save detailed mappings to JSON
        with open('sponsor_family_mappings.json', 'w') as f:
            json.dump(stats['mappings'], f, indent=2)
        print(f"\n💾 Saved detailed mappings to sponsor_family_mappings.json")

    finally:
        mapper.close()


if __name__ == '__main__':
    main()
