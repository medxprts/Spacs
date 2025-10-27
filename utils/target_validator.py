#!/usr/bin/env python3
"""
Target Company Validator

Validates that extracted target company names are legitimate companies,
not sponsor entities, trustees, or parsing errors.

Prevents data quality issues like:
- VACH: "Voyager Acquisition Sponsor Holdco LLC" (sponsor entity)
- LCCC: "Wilmington Trust, National Association..." (trustee)
- HSPT: "HSPT. A copy of the Company" (parsing error)
"""

import re
from typing import Optional, Tuple


# Red flag keywords that indicate NOT a real target
SPONSOR_KEYWORDS = [
    'sponsor',
    'holdco',
    'sponsor holdco',
    'acquisition sponsor',
    'founder',
]

TRUSTEE_KEYWORDS = [
    'trustee',
    'trust company',
    'trust, national association',
    'acting as trustee',
    'wilmington trust',
    'continental stock',
]

PARSING_ERROR_PATTERNS = [
    r'^[A-Z]{2,6}\.\s+',  # "HSPT. A copy of..."
    r'a copy of',
    r'pursuant to',
    r'exhibit',
    r'schedule',
    r'form [0-9]',
]


def validate_target(target_name: str, spac_ticker: str = None) -> Tuple[bool, Optional[str]]:
    """
    Validate that a target company name is legitimate

    Args:
        target_name: Extracted target company name
        spac_ticker: SPAC ticker (to check if target == ticker, which is wrong)

    Returns:
        (is_valid, reason_if_invalid)

    Examples:
        >>> validate_target("Voyager Acquisition Sponsor Holdco LLC")
        (False, "Contains sponsor keyword: 'sponsor'")

        >>> validate_target("Wilmington Trust, National Association acting as trustee")
        (False, "Contains trustee keyword: 'trustee'")

        >>> validate_target("Acme Technology Inc.")
        (True, None)
    """
    if not target_name or not target_name.strip():
        return False, "Target name is empty"

    target_lower = target_name.lower().strip()

    # Rule 1: Check for sponsor keywords
    for keyword in SPONSOR_KEYWORDS:
        if keyword in target_lower:
            return False, f"Contains sponsor keyword: '{keyword}'"

    # Rule 2: Check for trustee keywords
    for keyword in TRUSTEE_KEYWORDS:
        if keyword in target_lower:
            return False, f"Contains trustee keyword: '{keyword}'"

    # Rule 3: Check for parsing error patterns
    for pattern in PARSING_ERROR_PATTERNS:
        if re.search(pattern, target_name, re.IGNORECASE):
            return False, f"Matches parsing error pattern: '{pattern}'"

    # Rule 4: Target should not be the same as SPAC ticker
    if spac_ticker and target_lower == spac_ticker.lower():
        return False, "Target name matches SPAC ticker (self-reference)"

    # Rule 5: Should not start with common filing phrases
    filing_phrases = [
        'item ',
        'section ',
        'page ',
        'see ',
        'refer to',
        'as described in',
    ]

    for phrase in filing_phrases:
        if target_lower.startswith(phrase):
            return False, f"Starts with filing phrase: '{phrase}'"

    # Rule 6: Should contain at least one alphabetic character
    if not re.search(r'[a-zA-Z]', target_name):
        return False, "Contains no alphabetic characters"

    # Rule 7: Should not be too short (likely parsing error)
    if len(target_name.strip()) < 3:
        return False, f"Too short ({len(target_name)} chars) - likely parsing error"

    # Rule 8: Check for common trustee/custodian entities
    common_trustees = [
        'continental stock transfer',
        'american stock transfer',
        'computershare',
    ]

    for trustee in common_trustees:
        if trustee in target_lower:
            return False, f"Known trustee/transfer agent: '{trustee}'"

    # Passed all validation rules
    return True, None


def sanitize_target(target_name: str) -> str:
    """
    Clean up target name (remove trailing punctuation, normalize spaces)

    This does NOT validate - just cleans up the string
    """
    if not target_name:
        return ""

    # Remove trailing punctuation
    cleaned = target_name.strip().rstrip('.,;:')

    # Normalize whitespace
    cleaned = ' '.join(cleaned.split())

    return cleaned


# Unit tests
if __name__ == "__main__":
    print("Target Validator Tests\n" + "="*60 + "\n")

    test_cases = [
        # Invalid cases (sponsor entities)
        ("Voyager Acquisition Sponsor Holdco LLC", "VACH", False),
        ("Sponsor Entity LLC", None, False),

        # Invalid cases (trustees)
        ("Wilmington Trust, National Association acting as trustee", "LCCC", False),
        ("Continental Stock Transfer & Trust Company", None, False),

        # Invalid cases (parsing errors)
        ("HSPT. A copy of the Company", "HSPT", False),
        ("Item 1.01 - Entry into Agreement", None, False),
        ("See Exhibit 10.1", None, False),

        # Invalid cases (self-reference)
        ("AEXA", "AEXA", False),

        # Valid cases
        ("Acme Technology Inc.", "TECH", True),
        ("United Manufacturing Corp", "MANU", True),
        ("Global Solutions LLC", "GSOL", True),
    ]

    for target, ticker, should_be_valid in test_cases:
        is_valid, reason = validate_target(target, ticker)

        status = "✅" if is_valid == should_be_valid else "❌"
        print(f"{status} '{target}'")
        print(f"   Valid: {is_valid}, Reason: {reason}")
        print()
