#!/usr/bin/env python3
"""
Clean up duplicate corrections in data_quality_conversations table.

Keeps only the most recent correction for each (ticker, issue_type) combination.
"""

import sys
from database import SessionLocal
from sqlalchemy import text

def analyze_duplicates(db):
    """Analyze duplicate corrections"""

    query = """
        SELECT
            ticker,
            issue_type,
            COUNT(*) as correction_count,
            MIN(created_at) as first_correction,
            MAX(created_at) as last_correction
        FROM data_quality_conversations
        WHERE final_fix IS NOT NULL
        GROUP BY ticker, issue_type
        HAVING COUNT(*) > 1
        ORDER BY correction_count DESC
    """

    result = db.execute(text(query))
    duplicates = result.fetchall()

    return duplicates


def show_duplicate_stats(db):
    """Show statistics about duplicates"""

    # Total corrections
    total_query = "SELECT COUNT(*) FROM data_quality_conversations WHERE final_fix IS NOT NULL"
    total = db.execute(text(total_query)).scalar()

    # Unique combinations
    unique_query = """
        SELECT COUNT(DISTINCT (ticker, issue_type))
        FROM data_quality_conversations
        WHERE final_fix IS NOT NULL
    """
    unique = db.execute(text(unique_query)).scalar()

    # Duplicates to delete
    to_delete = total - unique

    print("\n" + "="*60)
    print("DUPLICATE CORRECTION ANALYSIS")
    print("="*60)
    print(f"Total corrections: {total}")
    print(f"Unique (ticker, issue_type) combinations: {unique}")
    print(f"Duplicates to be removed: {to_delete}")
    print(f"Percentage duplicates: {(to_delete/total*100):.1f}%")

    # Show top duplicates
    duplicates = analyze_duplicates(db)

    if duplicates:
        print("\n" + "="*60)
        print("TOP DUPLICATE OFFENDERS:")
        print("="*60)
        print(f"{'Ticker':<10} {'Issue Type':<25} {'Count':<8} {'Date Range'}")
        print("-"*60)

        for dup in duplicates[:10]:
            ticker, issue_type, count, first, last = dup
            date_range = f"{first.strftime('%Y-%m-%d')} to {last.strftime('%Y-%m-%d')}"
            print(f"{ticker:<10} {issue_type:<25} {count:<8} {date_range}")

    return to_delete


def cleanup_duplicates(db, dry_run=True):
    """
    Clean up duplicate corrections, keeping only the most recent for each (ticker, issue_type).

    Args:
        db: Database session
        dry_run: If True, only show what would be deleted without actually deleting
    """

    # Show stats before
    to_delete = show_duplicate_stats(db)

    if to_delete == 0:
        print("\n✅ No duplicates found!")
        return

    print("\n" + "="*60)
    print("CLEANUP STRATEGY:")
    print("="*60)
    print("For each (ticker, issue_type) combination:")
    print("  - Keep: Most recent correction (MAX id)")
    print("  - Delete: All older corrections")
    print("="*60)

    if dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made")
        print("Run with --live to actually delete duplicates")

        # Show sample of what would be deleted
        sample_query = """
            SELECT
                id,
                ticker,
                issue_type,
                created_at
            FROM data_quality_conversations
            WHERE final_fix IS NOT NULL
            AND id NOT IN (
                SELECT MAX(id)
                FROM data_quality_conversations
                WHERE final_fix IS NOT NULL
                GROUP BY ticker, issue_type
            )
            ORDER BY ticker, issue_type, created_at DESC
            LIMIT 10
        """

        result = db.execute(text(sample_query))
        samples = result.fetchall()

        if samples:
            print("\n📋 SAMPLE OF CORRECTIONS TO BE DELETED:")
            print(f"{'ID':<8} {'Ticker':<10} {'Issue Type':<25} {'Created At'}")
            print("-"*60)
            for sample in samples:
                print(f"{sample[0]:<8} {sample[1]:<10} {sample[2]:<25} {sample[3]}")
            print(f"... and {to_delete - len(samples)} more")

        return to_delete

    else:
        print("\n🚀 LIVE MODE - Deleting duplicates...")

        # Delete duplicates, keeping only the most recent
        delete_query = """
            DELETE FROM data_quality_conversations
            WHERE id IN (
                SELECT id
                FROM data_quality_conversations
                WHERE final_fix IS NOT NULL
                AND id NOT IN (
                    SELECT MAX(id)
                    FROM data_quality_conversations
                    WHERE final_fix IS NOT NULL
                    GROUP BY ticker, issue_type
                )
            )
        """

        result = db.execute(text(delete_query))
        deleted_count = result.rowcount
        db.commit()

        print(f"\n✅ Deleted {deleted_count} duplicate corrections")

        # Show stats after
        print("\n" + "="*60)
        print("AFTER CLEANUP:")
        print("="*60)
        show_duplicate_stats(db)

        return deleted_count


def main():
    """Main entry point"""

    dry_run = True

    if len(sys.argv) > 1 and sys.argv[1] == '--live':
        dry_run = False
        print("\n⚠️  WARNING: Running in LIVE mode - duplicates will be deleted!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return

    db = SessionLocal()

    try:
        cleanup_duplicates(db, dry_run=dry_run)

        if dry_run:
            print("\n" + "="*60)
            print("To actually delete duplicates, run:")
            print("  python3 cleanup_duplicate_corrections.py --live")
            print("="*60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == '__main__':
    main()
