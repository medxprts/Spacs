"""
Number Parser Utility
Converts human-readable number formats to numeric values

Handles formats like:
- "$275M" → 275000000
- "1.2B" → 1200000000
- "5M shares" → 5000000
- "$10.00" → 10.0
- "1,234,567" → 1234567

Used across all AI extraction agents to ensure database compatibility.
"""

import re
from typing import Union, Optional


def parse_numeric_value(value: Union[str, int, float, None]) -> Optional[float]:
    """
    Parse any value into a numeric float.

    Args:
        value: Input value (string, number, or None)

    Returns:
        Float value or None if cannot parse

    Examples:
        >>> parse_numeric_value("$275M")
        275000000.0
        >>> parse_numeric_value("1.2B")
        1200000000.0
        >>> parse_numeric_value("5M shares")
        5000000.0
        >>> parse_numeric_value("$10.00")
        10.0
        >>> parse_numeric_value(100)
        100.0
        >>> parse_numeric_value("N/A")
        None
    """
    # Handle None or empty
    if value is None or value == '':
        return None

    # Already numeric
    if isinstance(value, (int, float)):
        return float(value)

    # Must be string at this point
    if not isinstance(value, str):
        return None

    # Clean the string
    value = value.strip().upper()

    # Handle common "N/A" cases
    if value in ['N/A', 'NA', 'TBD', 'TBA', '-', 'NONE', 'NULL']:
        return None

    # Remove currency symbols and commas
    value = value.replace('$', '').replace(',', '').replace(' ', '')

    # Extract numeric part and multiplier
    # Matches patterns like: "275M", "1.2B", "5.5M", "10.0"
    match = re.match(r'^([0-9.]+)([KMBT]?)(?:SHARES|MILLION|BILLION|TRILLION)?$', value)

    if not match:
        # Try to parse as plain number
        try:
            return float(value)
        except (ValueError, AttributeError):
            return None

    number_str, multiplier = match.groups()

    try:
        number = float(number_str)
    except ValueError:
        return None

    # Apply multiplier
    multipliers = {
        'K': 1_000,
        'M': 1_000_000,
        'B': 1_000_000_000,
        'T': 1_000_000_000_000,
        '': 1  # No multiplier
    }

    return number * multipliers.get(multiplier, 1)


def parse_money_string(value: Union[str, int, float, None]) -> Optional[float]:
    """
    Alias for parse_numeric_value - specifically for money amounts.
    """
    return parse_numeric_value(value)


def parse_share_count(value: Union[str, int, float, None]) -> Optional[float]:
    """
    Alias for parse_numeric_value - specifically for share counts.
    """
    return parse_numeric_value(value)


def format_number_display(value: Optional[float], field_type: str = 'money') -> str:
    """
    Format a numeric value for display in UI.

    Args:
        value: Numeric value
        field_type: 'money', 'shares', 'percentage', 'volume', or 'number'

    Returns:
        Formatted string for display

    Examples:
        >>> format_number_display(275000000, 'money')
        '$275.0M'
        >>> format_number_display(5000000, 'shares')
        '5.0M shares'
        >>> format_number_display(10.5, 'percentage')
        '10.5%'
        >>> format_number_display(1234567, 'volume')
        '1,234,567'
    """
    if value is None:
        return '-'

    if field_type == 'percentage':
        return f"{value:.1f}%"

    # Volume: show with commas, no decimals
    if field_type == 'volume':
        if abs(value) >= 1_000_000:
            # For millions, show as "1.2M" instead of "1,234,567"
            return f"{value / 1_000_000:.1f}M"
        else:
            return f"{int(value):,}"

    # For large numbers, use M/B notation (consistent 1 decimal)
    if abs(value) >= 1_000_000_000:
        formatted = f"{value / 1_000_000_000:.1f}B"
    elif abs(value) >= 1_000_000:
        formatted = f"{value / 1_000_000:.1f}M"
    elif abs(value) >= 1_000:
        formatted = f"{value / 1_000:.1f}K"
    else:
        formatted = f"{value:.2f}"

    if field_type == 'money':
        return f"${formatted}"
    elif field_type == 'shares':
        return f"{formatted} shares"
    else:
        return formatted


def sanitize_ai_response(data: dict, numeric_fields: list) -> dict:
    """
    Clean AI response by parsing all numeric fields.

    Args:
        data: Dictionary from AI response
        numeric_fields: List of field names that should be numeric

    Returns:
        Cleaned dictionary with parsed numeric values

    Example:
        >>> data = {"target": "Company Inc", "pipe_size": "$275M", "earnout_shares": "1.1M"}
        >>> sanitize_ai_response(data, ['pipe_size', 'earnout_shares'])
        {"target": "Company Inc", "pipe_size": 275000000.0, "earnout_shares": 1100000.0}
    """
    cleaned = data.copy()

    for field in numeric_fields:
        if field in cleaned and cleaned[field] is not None:
            parsed = parse_numeric_value(cleaned[field])
            cleaned[field] = parsed

    return cleaned


# Constants for common field types
MONEY_FIELDS = [
    'deal_value', 'pipe_size', 'min_cash', 'forward_purchase',
    'trust_cash', 'trust_value', 'price', 'common_price',
    'warrant_price', 'unit_price', 'ipo_price', 'pipe_price',
    'tev', 'redemption_amount'
]

SHARE_FIELDS = [
    'earnout_shares', 'shares_outstanding', 'shares_redeemed',
    'initial_shares', 'founder_shares', 'sponsor_promote',
    'pipe_shares', 'public_shares'
]

PERCENTAGE_FIELDS = [
    'premium', 'warrant_premium', 'redemption_percentage',
    'min_cash_percentage', 'sponsor_ownership', 'pipe_ownership'
]


# Unit tests
if __name__ == "__main__":
    print("Testing number parser...\n")

    test_cases = [
        ("$275M", 275_000_000, "Money with M"),
        ("1.2B", 1_200_000_000, "Billions"),
        ("5M shares", 5_000_000, "Shares with M"),
        ("$10.00", 10.0, "Dollars"),
        ("1,234,567", 1_234_567, "Comma separated"),
        ("100", 100, "Plain number"),
        ("N/A", None, "N/A handling"),
        (None, None, "None handling"),
        (100, 100, "Already numeric"),
        ("1.1M", 1_100_000, "CHAC earnout case"),
    ]

    print("parse_numeric_value() tests:")
    for input_val, expected, description in test_cases:
        result = parse_numeric_value(input_val)
        status = "✅" if result == expected else "❌"
        print(f"{status} {description}: '{input_val}' → {result} (expected {expected})")

    print("\nsanitize_ai_response() test:")
    test_data = {
        "target": "Company Inc",
        "deal_value": "$500M",
        "pipe_size": "275M",
        "earnout_shares": "1.1M",
        "min_cash_percentage": 25.0
    }

    cleaned = sanitize_ai_response(test_data, MONEY_FIELDS + SHARE_FIELDS)
    print(f"Input:  {test_data}")
    print(f"Output: {cleaned}")

    print("\nformat_number_display() tests:")
    print(f"Money:   {format_number_display(275000000, 'money')}")
    print(f"Shares:  {format_number_display(5000000, 'shares')}")
    print(f"Percent: {format_number_display(10.5, 'percentage')}")
