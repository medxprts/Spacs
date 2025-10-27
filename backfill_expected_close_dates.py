#!/usr/bin/env python3
"""
Backfill Expected Close Dates

Normalizes all expected_close values in database to proper dates:
- "H2 2025" → 2025-10-01
- "Q1 2026" → 2026-02-15
- Etc.
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from utils.expected_close_normalizer import normalize_expected_close


def backfill_expected_close_dates(dry_run=True):
    """Backfill all expected_close dates"""

    db = SessionLocal()

    try:
        # Get all SPACs with expected_close values
        spacs = db.query(SPAC).filter(
            SPAC.expected_close.isnot(None)
        ).all()

        print(f"📅 Expected Close Date Normalizer")
        print(f"=" * 70)
        print(f"Found {len(spacs)} SPACs with expected_close values\n")

        updates = 0
        unchanged = 0
        cleared = 0

        for spac in spacs:
            original = str(spac.expected_close) if spac.expected_close else None

            # Normalize
            normalized = normalize_expected_close(original)

            # Check if changed
            if normalized is None and original in ['-', 'TBD', 'N/A']:
                # Clear placeholder values
                if not dry_run:
                    spac.expected_close = None
                print(f"  {spac.ticker:6s} | '{original:20s}' → NULL (cleared placeholder)")
                cleared += 1

            elif normalized is not None:
                # Convert to string for comparison
                original_date = str(spac.expected_close).split()[0] if spac.expected_close else None
                normalized_str = str(normalized)

                if original_date != normalized_str:
                    if not dry_run:
                        spac.expected_close = normalized
                    print(f"  {spac.ticker:6s} | '{original:20s}' → {normalized}")
                    updates += 1
                else:
                    unchanged += 1
            else:
                # Could not normalize
                print(f"  {spac.ticker:6s} | '{original:20s}' → ⚠️  Could not normalize")
                unchanged += 1

        if not dry_run:
            db.commit()
            print(f"\n✅ Database updated")
        else:
            print(f"\n💡 DRY RUN - No changes made")

        print(f"\n" + "=" * 70)
        print(f"📊 SUMMARY")
        print(f"=" * 70)
        print(f"Total SPACs:        {len(spacs)}")
        print(f"✅ Updated:          {updates}")
        print(f"🗑️  Cleared:          {cleared}")
        print(f"⏭️  Unchanged:        {unchanged}")

        return updates + cleared

    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Backfill expected close dates')
    parser.add_argument('--commit', action='store_true', help='Actually update database (default is dry-run)')
    args = parser.parse_args()

    backfill_expected_close_dates(dry_run=not args.commit)
