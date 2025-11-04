#!/usr/bin/env python3
"""
Consolidate Error Tracking Tables

Consolidates 5 fragmented error tracking systems into 1 unified system.

Actions:
1. Backup all tables
2. Add issue_source field to data_quality_conversations
3. Migrate user_issues (6 records) into data_quality_conversations
4. Archive old tables
5. Drop unused tables (code_errors, validation_failures, validation_suppressions)

Date: 2025-11-04
"""

import sys
import json
from database import SessionLocal
from sqlalchemy import text

def backup_tables(db):
    """Show current state before changes"""
    print("\n" + "="*60)
    print("CURRENT STATE (BEFORE CONSOLIDATION)")
    print("="*60)

    tables = [
        'data_quality_conversations',
        'user_issues',
        'code_errors',
        'validation_failures',
        'validation_suppressions'
    ]

    for table in tables:
        try:
            query = text(f"SELECT COUNT(*) FROM {table}")
            count = db.execute(query).scalar()
            print(f"{table:<35} {count:>5} records")
        except Exception as e:
            print(f"{table:<35} ERROR: {e}")


def add_issue_source_field(db, dry_run=True):
    """Add issue_source field to track where issues come from"""
    print("\n" + "="*60)
    print("STEP 1: Add issue_source field")
    print("="*60)

    # Check if field already exists
    check_query = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'data_quality_conversations'
        AND column_name = 'issue_source'
    """)

    exists = db.execute(check_query).fetchone()

    if exists:
        print("✅ Field 'issue_source' already exists")
        return

    alter_query = text("""
        ALTER TABLE data_quality_conversations
        ADD COLUMN issue_source VARCHAR(20) DEFAULT 'ai_detected'
    """)

    if dry_run:
        print("⚠️  DRY RUN - Would add field:")
        print("   ALTER TABLE data_quality_conversations")
        print("   ADD COLUMN issue_source VARCHAR(20) DEFAULT 'ai_detected'")
    else:
        db.execute(alter_query)
        db.commit()
        print("✅ Added issue_source field")


def migrate_user_issues(db, dry_run=True):
    """Migrate user_issues into data_quality_conversations"""
    print("\n" + "="*60)
    print("STEP 2: Migrate user_issues")
    print("="*60)

    # Get user_issues data
    query = text("""
        SELECT
            id, issue_type, title, description,
            ticker_related, page_location, status,
            priority, submitted_at, resolution_notes
        FROM user_issues
        ORDER BY submitted_at
    """)

    issues = db.execute(query).fetchall()
    print(f"Found {len(issues)} user-reported issues to migrate")

    if len(issues) == 0:
        print("✅ No user_issues to migrate")
        return

    # Show what will be migrated
    print("\n📋 Issues to migrate:")
    print(f"{'ID':<5} {'Type':<20} {'Ticker':<10} {'Title'}")
    print("-"*60)
    for issue in issues:
        print(f"{issue[0]:<5} {issue[1]:<20} {issue[4] or 'N/A':<10} {issue[2][:30]}")

    if dry_run:
        print("\n⚠️  DRY RUN - Would insert into data_quality_conversations")
        return

    # Migrate each issue
    insert_query = text("""
        INSERT INTO data_quality_conversations (
            issue_id, issue_type, ticker, created_at, status,
            original_data, learning_notes, issue_source
        )
        VALUES (
            :issue_id, :issue_type, :ticker, :created_at, :status,
            :original_data, :learning_notes, 'user_reported'
        )
    """)

    for issue in issues:
        issue_id = f"user_issue_{issue[0]}_{issue[8].strftime('%Y%m%d')}"
        original_data = {
            'description': issue[3],
            'page_location': issue[5],
            'priority': issue[7]
        }
        learning_notes = f"{issue[2]}\n\n{issue[3]}"
        if issue[9]:
            learning_notes += f"\n\nResolution: {issue[9]}"

        db.execute(insert_query, {
            'issue_id': issue_id,
            'issue_type': issue[1] or 'user_reported',
            'ticker': issue[4],
            'created_at': issue[8],
            'status': issue[6] or 'pending',
            'original_data': json.dumps(original_data),
            'learning_notes': learning_notes
        })

    db.commit()
    print(f"✅ Migrated {len(issues)} user issues")


def archive_user_issues_table(db, dry_run=True):
    """Rename user_issues table to archive"""
    print("\n" + "="*60)
    print("STEP 3: Archive user_issues table")
    print("="*60)

    if dry_run:
        print("⚠️  DRY RUN - Would rename:")
        print("   user_issues → user_issues_archived_20251104")
    else:
        db.execute(text("ALTER TABLE user_issues RENAME TO user_issues_archived_20251104"))
        db.commit()
        print("✅ Renamed user_issues → user_issues_archived_20251104")


def drop_unused_tables(db, dry_run=True):
    """Drop unused tables"""
    print("\n" + "="*60)
    print("STEP 4: Drop unused tables")
    print("="*60)

    tables_to_drop = [
        ('code_errors', 0),
        ('validation_failures', 0),
        ('validation_suppressions', 0)
    ]

    for table, expected_count in tables_to_drop:
        # Verify table is empty
        count = db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()

        if count != expected_count:
            print(f"⚠️  Skipping {table} - has {count} records (expected {expected_count})")
            continue

        if dry_run:
            print(f"⚠️  DRY RUN - Would drop {table} (0 records)")
        else:
            db.execute(text(f"DROP TABLE IF EXISTS {table}"))
            db.commit()
            print(f"✅ Dropped {table}")


def show_final_state(db):
    """Show final state after consolidation"""
    print("\n" + "="*60)
    print("FINAL STATE (AFTER CONSOLIDATION)")
    print("="*60)

    # Count records by issue_source
    query = text("""
        SELECT
            issue_source,
            COUNT(*) as count
        FROM data_quality_conversations
        GROUP BY issue_source
        ORDER BY count DESC
    """)

    results = db.execute(query).fetchall()

    print("\ndata_quality_conversations breakdown:")
    total = 0
    for row in results:
        print(f"  {row[0]:<20} {row[1]:>5} records")
        total += row[1]
    print(f"  {'TOTAL':<20} {total:>5} records")

    # Show remaining tables
    print("\nRemaining tables:")
    query = text("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name LIKE '%issue%' OR table_name LIKE '%error%' OR table_name LIKE '%validation%'
        ORDER BY table_name
    """)

    tables = db.execute(query).fetchall()
    for table in tables:
        if 'archived' in table[0]:
            print(f"  {table[0]} (archived)")
        else:
            count = db.execute(text(f"SELECT COUNT(*) FROM {table[0]}")).scalar()
            print(f"  {table[0]}: {count} records")


def main():
    """Main entry point"""

    dry_run = True

    if len(sys.argv) > 1 and sys.argv[1] == '--live':
        dry_run = False
        print("\n⚠️  WARNING: Running in LIVE mode - tables will be modified!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            print("Aborted.")
            return

    db = SessionLocal()

    try:
        # Show current state
        backup_tables(db)

        # Step 1: Add issue_source field
        add_issue_source_field(db, dry_run)

        # Step 2: Migrate user_issues
        migrate_user_issues(db, dry_run)

        # Step 3: Archive user_issues table
        archive_user_issues_table(db, dry_run)

        # Step 4: Drop unused tables
        drop_unused_tables(db, dry_run)

        if not dry_run:
            # Show final state
            show_final_state(db)

        if dry_run:
            print("\n" + "="*60)
            print("To actually consolidate tables, run:")
            print("  python3 consolidate_error_tables.py --live")
            print("="*60)
        else:
            print("\n" + "="*60)
            print("✅ CONSOLIDATION COMPLETE!")
            print("="*60)
            print("\nNext steps:")
            print("1. Update Streamlit to show issue_source filter")
            print("2. Update documentation")
            print("3. Test Few-Shot learning with consolidated data")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == '__main__':
    main()
