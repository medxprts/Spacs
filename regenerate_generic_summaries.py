#!/usr/bin/env python3
"""
Regenerate Generic Filing Summaries

Finds filing_events with generic summaries and regenerates them using AI.
Run this after fixing filing_logger.py to clean up old generic summaries.
"""

import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, FilingEvent
from utils.filing_logger import _generate_summary
from sec_text_extractor import extract_filing_text

def is_generic_summary(summary: str) -> bool:
    """Check if summary is generic (needs regeneration)"""
    if not summary:
        return True

    generic_patterns = [
        "This is a Rule 425 filing",
        "business combination or acquisition activities",
        "filed an 8-K to report",
        "filed a Form 8-K",
        "filed Form 425"
    ]

    for pattern in generic_patterns:
        if pattern in summary:
            return True

    return False


def regenerate_summaries(limit: int = 100, dry_run: bool = False):
    """Regenerate generic summaries"""
    db = SessionLocal()
    try:
        # Find filings with generic summaries
        filings = db.query(FilingEvent).order_by(FilingEvent.filing_date.desc()).limit(limit).all()

        generic_count = 0
        updated_count = 0

        for filing in filings:
            if is_generic_summary(filing.summary):
                generic_count += 1
                print(f"\n{'[DRY RUN] ' if dry_run else ''}📄 {filing.ticker} - {filing.filing_type} ({filing.filing_date})")
                print(f"   Old: {filing.summary[:100]}...")

                # Regenerate summary
                try:
                    # Fetch filing content
                    content = extract_filing_text(filing.filing_url)

                    # Build filing dict for summary generation
                    filing_dict = {
                        'ticker': filing.ticker,
                        'type': filing.filing_type,
                        'date': filing.filing_date,
                        'url': filing.filing_url,
                        'title': filing.filing_title,
                        'item_number': filing.item_number,
                        'content': content,
                        'classification': {
                            'priority': filing.priority,
                            'reason': ''  # No classification context available
                        }
                    }

                    new_summary = _generate_summary(filing_dict)

                    if new_summary and not is_generic_summary(new_summary):
                        print(f"   New: {new_summary[:100]}{'...' if len(new_summary) > 100 else ''}")

                        if not dry_run:
                            filing.summary = new_summary
                            db.commit()
                            updated_count += 1
                            print("   ✅ Updated")
                        else:
                            print("   ✓ Would update (dry run)")
                    else:
                        print("   ⚠️  New summary still generic or None")

                except Exception as e:
                    print(f"   ❌ Error: {e}")
                    continue

        print(f"\n{'[DRY RUN] ' if dry_run else ''}Summary:")
        print(f"  Generic summaries found: {generic_count}")
        if not dry_run:
            print(f"  Successfully updated: {updated_count}")

    finally:
        db.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Regenerate generic filing summaries')
    parser.add_argument('--limit', type=int, default=100, help='Max filings to check')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without making changes')
    parser.add_argument('--run', action='store_true', help='Actually update summaries (required to execute)')

    args = parser.parse_args()

    if not args.run and not args.dry_run:
        print("❗ Please specify --dry-run to preview or --run to execute")
        sys.exit(1)

    regenerate_summaries(limit=args.limit, dry_run=args.dry_run)
