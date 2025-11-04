#!/usr/bin/env python3
"""
Migrate Correction Data Format

Converts human-readable explanations to structured machine-readable format.

BEFORE:
{
  "trust_cash": "<= $345.3M (15.1% above IPO: 15% overallotment + 0.1% interest)"
}

AFTER:
{
  "trust_cash": {
    "value": 345300000,
    "metadata": {
      "note": "15.1% above IPO: 15% overallotment + 0.1% interest",
      "validation": "acceptable_range",
      "max_value": 345300000
    }
  }
}
"""

import sys
import re
import json
from typing import Dict, Any, Optional
from datetime import datetime

sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal
from sqlalchemy import text


class CorrectionMigrator:
    """Migrate corrections to structured format"""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.db = SessionLocal()
        self.migrations_applied = 0
        self.migrations_skipped = 0
        self.errors = []

    def parse_trust_cash_string(self, value_str: str) -> Optional[Dict]:
        """
        Parse trust_cash string like "<= $345.3M (15.1% above IPO...)"

        Returns:
            {
                "value": 345300000,
                "metadata": {
                    "note": "15.1% above IPO: 15% overallotment + 0.1% interest",
                    "validation": "acceptable_range",
                    "max_value": 345300000
                }
            }
        """
        if not isinstance(value_str, str):
            return None

        # Pattern: "<= $XXX.XM (note...)"
        pattern = r'<=?\s*\$?(\d+\.?\d*)[M]?\s*\((.+?)\)'
        match = re.search(pattern, value_str)

        if match:
            value_str_num = match.group(1)
            note = match.group(2).strip()

            # Convert to numeric (millions to actual number)
            value_millions = float(value_str_num)
            value_numeric = int(value_millions * 1_000_000)

            return {
                "value": value_numeric,
                "metadata": {
                    "note": note,
                    "validation": "acceptable_range",
                    "max_value": value_numeric,
                    "original_string": value_str
                }
            }

        return None

    def parse_announced_date_string(self, value_str: str) -> Optional[Dict]:
        """
        Parse announced_date string like "Date deal was announced"

        Returns:
            {
                "value": null,
                "metadata": {
                    "note": "Date deal was announced",
                    "data_type": "date",
                    "status": "needs_extraction"
                }
            }
        """
        if not isinstance(value_str, str):
            return None

        if "date" in value_str.lower():
            return {
                "value": None,
                "metadata": {
                    "note": value_str,
                    "data_type": "date",
                    "status": "needs_extraction"
                }
            }

        return None

    def migrate_field_value(self, field: str, value: Any) -> Any:
        """
        Migrate a single field value to structured format.

        Args:
            field: Field name (e.g., 'trust_cash')
            value: Current value (could be string, number, null, etc.)

        Returns:
            Migrated value (structured dict or original value if no migration needed)
        """
        # Skip if already structured (has 'value' and 'metadata' keys)
        if isinstance(value, dict) and 'value' in value and 'metadata' in value:
            return value  # Already migrated

        # Handle trust_cash strings
        if field == 'trust_cash' and isinstance(value, str):
            parsed = self.parse_trust_cash_string(value)
            if parsed:
                return parsed

        # Handle announced_date strings
        if field == 'announced_date' and isinstance(value, str):
            parsed = self.parse_announced_date_string(value)
            if parsed:
                return parsed

        # Handle simple numeric values (wrap with metadata)
        if isinstance(value, (int, float)) and value is not None:
            return {
                "value": value,
                "metadata": {
                    "data_type": "number",
                    "original_format": "simple_numeric"
                }
            }

        # Handle null/None (wrap with metadata)
        if value is None:
            return {
                "value": None,
                "metadata": {
                    "data_type": "null",
                    "note": "No data available"
                }
            }

        # Handle booleans (wrap with metadata)
        if isinstance(value, bool):
            return {
                "value": value,
                "metadata": {
                    "data_type": "boolean"
                }
            }

        # Handle simple strings (wrap with metadata)
        if isinstance(value, str):
            return {
                "value": value,
                "metadata": {
                    "data_type": "string",
                    "original_format": "simple_string"
                }
            }

        # Unknown format, return as-is
        return value

    def migrate_final_fix(self, final_fix: Dict) -> Dict:
        """
        Migrate entire final_fix dict to structured format.

        Args:
            final_fix: Current final_fix dict

        Returns:
            Migrated final_fix dict
        """
        if not final_fix:
            return final_fix

        migrated = {}
        for field, value in final_fix.items():
            migrated[field] = self.migrate_field_value(field, value)

        return migrated

    def migrate_all_corrections(self):
        """Migrate all corrections in database"""
        print("="*60)
        print("CORRECTION DATA FORMAT MIGRATION")
        print("="*60)
        print(f"\nMode: {'DRY RUN (no changes)' if self.dry_run else 'LIVE (will update database)'}")

        # Get all corrections with final_fix
        query = """
            SELECT id, ticker, issue_type, final_fix
            FROM data_quality_conversations
            WHERE final_fix IS NOT NULL
            ORDER BY created_at DESC
        """

        result = self.db.execute(text(query))
        corrections = result.fetchall()

        print(f"\n📊 Found {len(corrections)} corrections to migrate")

        # Migrate each
        for i, row in enumerate(corrections, 1):
            correction_id = row[0]
            ticker = row[1]
            issue_type = row[2]
            final_fix = row[3]

            try:
                # Migrate
                migrated_fix = self.migrate_final_fix(final_fix)

                # Check if changed
                if migrated_fix != final_fix:
                    self.migrations_applied += 1

                    print(f"\n{'='*60}")
                    print(f"Migration {self.migrations_applied}: {ticker} ({issue_type})")
                    print(f"{'='*60}")

                    # Show changes for first few
                    if self.migrations_applied <= 5:
                        print("\nBEFORE:")
                        print(json.dumps(final_fix, indent=2))
                        print("\nAFTER:")
                        print(json.dumps(migrated_fix, indent=2))

                    # Update database (if not dry run)
                    if not self.dry_run:
                        update_query = """
                            UPDATE data_quality_conversations
                            SET final_fix = :migrated_fix
                            WHERE id = :id
                        """
                        self.db.execute(
                            text(update_query),
                            {'migrated_fix': json.dumps(migrated_fix), 'id': correction_id}
                        )

                else:
                    self.migrations_skipped += 1

            except Exception as e:
                self.errors.append({
                    'id': correction_id,
                    'ticker': ticker,
                    'error': str(e)
                })
                print(f"\n❌ Error migrating {ticker}: {e}")

        # Commit changes (if not dry run)
        if not self.dry_run:
            self.db.commit()
            print(f"\n✅ Committed {self.migrations_applied} migrations to database")
        else:
            print(f"\n⚠️  DRY RUN: No changes committed to database")

        # Summary
        self.print_summary()

    def print_summary(self):
        """Print migration summary"""
        print(f"\n{'='*60}")
        print("MIGRATION SUMMARY")
        print(f"{'='*60}")
        print(f"\n✅ Migrations applied: {self.migrations_applied}")
        print(f"⏭️  Skipped (already migrated): {self.migrations_skipped}")
        print(f"❌ Errors: {len(self.errors)}")

        if self.errors:
            print(f"\n❌ Errors:")
            for error in self.errors[:5]:
                print(f"   {error['ticker']}: {error['error']}")
            if len(self.errors) > 5:
                print(f"   ... and {len(self.errors) - 5} more errors")

    def test_migration(self):
        """Test migration on a few examples"""
        print("="*60)
        print("TESTING MIGRATION LOGIC")
        print("="*60)

        test_cases = [
            {
                'name': 'trust_cash explanatory string',
                'field': 'trust_cash',
                'value': '<= $345.3M (15.1% above IPO: 15% overallotment + 0.1% interest)',
                'expected_value': 345300000
            },
            {
                'name': 'trust_value numeric',
                'field': 'trust_value',
                'value': 9.8,
                'expected_value': 9.8
            },
            {
                'name': 'announced_date string',
                'field': 'announced_date',
                'value': 'Date deal was announced',
                'expected_value': None
            },
            {
                'name': 'None value',
                'field': 'trust_value',
                'value': None,
                'expected_value': None
            }
        ]

        for test in test_cases:
            print(f"\n{'='*60}")
            print(f"Test: {test['name']}")
            print(f"{'='*60}")
            print(f"Field: {test['field']}")
            print(f"Input: {test['value']}")

            migrated = self.migrate_field_value(test['field'], test['value'])

            print(f"\nMigrated:")
            print(json.dumps(migrated, indent=2))

            # Check value
            if isinstance(migrated, dict) and 'value' in migrated:
                actual_value = migrated['value']
                expected_value = test['expected_value']

                if actual_value == expected_value:
                    print(f"\n✅ PASS: Value matches expected ({expected_value})")
                else:
                    print(f"\n❌ FAIL: Expected {expected_value}, got {actual_value}")
            else:
                print(f"\n⚠️  WARNING: Migrated value is not structured dict")

    def close(self):
        """Close database connection"""
        self.db.close()


def main():
    """Main migration script"""
    import argparse

    parser = argparse.ArgumentParser(description='Migrate correction data format')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Dry run (no database changes). Default: True')
    parser.add_argument('--live', action='store_true',
                        help='Run live migration (will update database)')
    parser.add_argument('--test', action='store_true',
                        help='Just test migration logic (don\'t touch database)')

    args = parser.parse_args()

    # Test mode
    if args.test:
        migrator = CorrectionMigrator(dry_run=True)
        migrator.test_migration()
        migrator.close()
        return

    # Determine dry run mode
    dry_run = not args.live

    if dry_run:
        print("\n⚠️  DRY RUN MODE: No changes will be made to database")
        print("   To run live migration, use: --live\n")
    else:
        print("\n🚨 LIVE MODE: Database will be updated!")
        response = input("   Are you sure? (yes/no): ")
        if response.lower() != 'yes':
            print("   Aborted.")
            return

    # Run migration
    migrator = CorrectionMigrator(dry_run=dry_run)
    migrator.migrate_all_corrections()
    migrator.close()


if __name__ == '__main__':
    main()
