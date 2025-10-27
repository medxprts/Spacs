#!/usr/bin/env python3
"""
Expected Close Date Normalizer

Converts various text formats to proper dates with quarter/half-year midpoints:
- "1Q 2026" → 2026-02-15 (Q1 midpoint)
- "Q2 2025" → 2025-05-15 (Q2 midpoint)
- "H1 2026" → 2026-04-01 (H1 midpoint)
- "H2 2025" → 2025-10-01 (H2 midpoint)
- "Early 2026" → 2026-02-01
- "Mid-2025" → 2025-07-01
- "Late 2025" → 2025-11-01
"""

from datetime import datetime, date
from typing import Optional
import re


def normalize_expected_close(text: Optional[str]) -> Optional[str]:
    """
    Normalize expected_close text to a date string (YYYY-MM-DD format)

    Args:
        text: Expected close text (e.g., "Q1 2026", "H2 2025", "2025-12-31")

    Returns:
        Normalized date string (YYYY-MM-DD) or None if unparseable
    """
    if not text or text in ['-', 'TBD', 'N/A', 'Unknown']:
        return None

    text = text.strip()

    # Already a date/datetime - convert to string
    if isinstance(text, date):
        return text.strftime('%Y-%m-%d')
    if isinstance(text, datetime):
        return text.date().strftime('%Y-%m-%d')

    # Try parsing as date - return string format
    for fmt in ['%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%m/%d/%Y', '%Y/%m/%d']:
        try:
            parsed_date = datetime.strptime(text, fmt).date()
            return parsed_date.strftime('%Y-%m-%d')
        except ValueError:
            continue

    # Half-year formats: "H1 2026", "H2 2025", "first half of 2025", "second half of 2026"
    half_match = re.search(r'(?:H|h)([12])\s+(\d{4})', text)
    if not half_match:
        # Try written format
        half_match = re.search(r'(first|second)\s+half\s+of\s+(\d{4})', text, re.IGNORECASE)
        if half_match:
            half = 1 if half_match.group(1).lower() == 'first' else 2
            year = int(half_match.group(2))
        else:
            half = None
            year = None
    else:
        half = int(half_match.group(1))
        year = int(half_match.group(2))

    if half is not None and year is not None:
        # Half-year midpoints - return as string
        if half == 1:
            return f"{year}-04-01"   # H1: Jan 1 - Jun 30 → Apr 1
        else:
            return f"{year}-10-01"  # H2: Jul 1 - Dec 31 → Oct 1

    # Quarter formats: "Q1 2026", "1Q 2026", "Q2 2025"
    quarter_match = re.search(r'(?:Q|q)?([1-4])(?:Q|q)?\s+(\d{4})', text)
    if quarter_match:
        quarter = int(quarter_match.group(1))
        year = int(quarter_match.group(2))

        # Quarter midpoints (middle of quarter)
        quarter_midpoints = {
            1: (2, 15),   # Q1: Jan 1 - Mar 31 → Feb 15
            2: (5, 15),   # Q2: Apr 1 - Jun 30 → May 15
            3: (8, 15),   # Q3: Jul 1 - Sep 30 → Aug 15
            4: (11, 15)   # Q4: Oct 1 - Dec 31 → Nov 15
        }

        month, day = quarter_midpoints[quarter]
        return f"{year}-{month:02d}-{day:02d}"

    # Relative time formats: "Early 2026", "Mid-2025", "Late 2025"
    early_match = re.search(r'(?:early|beginning)\s+(\d{4})', text, re.IGNORECASE)
    if early_match:
        year = int(early_match.group(1))
        return f"{year}-02-01"  # Early → Feb 1

    mid_match = re.search(r'mid(?:dle)?[- ](\d{4})', text, re.IGNORECASE)
    if mid_match:
        year = int(mid_match.group(1))
        return f"{year}-07-01"  # Mid → July 1

    late_match = re.search(r'(?:late|end)\s+(\d{4})', text, re.IGNORECASE)
    if late_match:
        year = int(late_match.group(1))
        return f"{year}-11-01"  # Late → Nov 1

    # Year only: "2026" → midpoint of year
    year_only_match = re.search(r'^(\d{4})$', text)
    if year_only_match:
        year = int(year_only_match.group(1))
        return f"{year}-07-01"  # Year midpoint → July 1

    # Couldn't parse
    return None


def test_normalizer():
    """Test the normalizer with various formats"""

    test_cases = [
        # Quarter formats
        ("Q1 2026", date(2026, 2, 15)),
        ("1Q 2026", date(2026, 2, 15)),
        ("Q2 2025", date(2025, 5, 15)),
        ("q3 2025", date(2025, 8, 15)),
        ("Q4 2024", date(2024, 11, 15)),

        # Half-year formats
        ("H1 2026", date(2026, 4, 1)),
        ("H2 2025", date(2025, 10, 1)),
        ("h1 2024", date(2024, 4, 1)),

        # Relative time
        ("Early 2026", date(2026, 2, 1)),
        ("Mid-2025", date(2025, 7, 1)),
        ("Late 2025", date(2025, 11, 1)),

        # Already dates
        ("2025-12-31", date(2025, 12, 31)),
        ("2024-06-15", date(2024, 6, 15)),

        # Invalid/placeholder
        ("-", None),
        ("TBD", None),
        ("N/A", None),
    ]

    print("Testing Expected Close Normalizer\n" + "="*50)

    passed = 0
    failed = 0

    for text, expected in test_cases:
        result = normalize_expected_close(text)
        status = "✅" if result == expected else "❌"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} '{text}' → {result} (expected: {expected})")

    print(f"\n{passed} passed, {failed} failed")


if __name__ == "__main__":
    test_normalizer()
