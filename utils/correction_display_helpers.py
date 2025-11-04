"""
Correction Display Helpers

Helper functions to display structured correction data in human-readable format.
Works with both old format (strings) and new format (structured dicts).
"""

from typing import Any, Dict
import json


def format_value_for_display(field: str, value: Any) -> str:
    """
    Format a correction value for human-readable display.

    Handles both formats:
    - Old: "<= $345.3M (15.1% above IPO...)"
    - New: {"value": 345300000, "metadata": {...}}

    Args:
        field: Field name (e.g., 'trust_cash')
        value: Field value (old or new format)

    Returns:
        Human-readable string
    """
    # Handle None/null
    if value is None:
        return "None"

    # Handle new structured format
    if isinstance(value, dict) and 'value' in value:
        actual_value = value['value']
        metadata = value.get('metadata', {})

        # Format based on data type
        if actual_value is None:
            note = metadata.get('note', 'No data available')
            return f"None ({note})"

        # Format numbers
        if isinstance(actual_value, (int, float)):
            formatted = format_number_value(field, actual_value)

            # Add note if available
            note = metadata.get('note')
            if note:
                return f"{formatted} ({note})"

            return formatted

        # Format strings
        if isinstance(actual_value, str):
            return actual_value

        # Format booleans
        if isinstance(actual_value, bool):
            return "Yes" if actual_value else "No"

        # Fallback
        return str(actual_value)

    # Handle old format (simple values)
    if isinstance(value, str):
        return value

    if isinstance(value, (int, float)):
        return format_number_value(field, value)

    if isinstance(value, bool):
        return "Yes" if value else "No"

    # Fallback
    return str(value)


def format_number_value(field: str, value: float) -> str:
    """
    Format numeric value based on field type.

    Args:
        field: Field name
        value: Numeric value

    Returns:
        Formatted string
    """
    # Money fields (trust_cash, deal_value, etc.)
    if any(x in field for x in ['cash', 'value', 'proceeds', 'price', 'size']):
        if value >= 1_000_000:
            return f"${value/1_000_000:.1f}M"
        elif value >= 1_000:
            return f"${value/1_000:.1f}K"
        else:
            return f"${value:.2f}"

    # Percentage fields
    if 'percent' in field or 'premium' in field or 'ratio' in field:
        return f"{value:.2f}%"

    # Share counts
    if 'shares' in field:
        if value >= 1_000_000:
            return f"{value/1_000_000:.1f}M shares"
        else:
            return f"{int(value):,} shares"

    # Default: number with commas
    if value == int(value):
        return f"{int(value):,}"
    else:
        return f"{value:,.2f}"


def format_correction_for_telegram(ticker: str, final_fix: Dict) -> str:
    """
    Format correction for Telegram display.

    Args:
        ticker: SPAC ticker
        final_fix: Final fix dict (old or new format)

    Returns:
        Formatted message for Telegram
    """
    lines = [f"✅ <b>Fix Applied: {ticker}</b>\n"]

    for field, value in final_fix.items():
        formatted_value = format_value_for_display(field, value)
        lines.append(f"   <b>{field}:</b> {formatted_value}")

    return "\n".join(lines)


def format_correction_comparison(field: str, old_value: Any, new_value: Any) -> str:
    """
    Format before/after comparison for Telegram.

    Args:
        field: Field name
        old_value: Old value
        new_value: New value (new format)

    Returns:
        Formatted comparison string
    """
    old_display = format_value_for_display(field, old_value) if old_value is not None else "None"
    new_display = format_value_for_display(field, new_value)

    return f"<b>{field}:</b>\n   Before: {old_display}\n   After:  {new_display}"


def get_value_from_correction(correction_value: Any) -> Any:
    """
    Extract the actual value from a correction (handles both formats).

    Args:
        correction_value: Correction value (old or new format)

    Returns:
        Actual value (for comparisons, calculations, etc.)
    """
    # New format
    if isinstance(correction_value, dict) and 'value' in correction_value:
        return correction_value['value']

    # Old format
    return correction_value


def get_metadata_from_correction(correction_value: Any) -> Dict:
    """
    Extract metadata from a correction.

    Args:
        correction_value: Correction value (old or new format)

    Returns:
        Metadata dict (empty if old format)
    """
    if isinstance(correction_value, dict) and 'metadata' in correction_value:
        return correction_value['metadata']

    return {}


# Examples for testing
if __name__ == '__main__':
    print("="*60)
    print("TESTING DISPLAY HELPERS")
    print("="*60)

    # Test old format
    print("\n1. Old format (string):")
    old_value = "<= $345.3M (15.1% above IPO: 15% overallotment + 0.1% interest)"
    print(f"   Input: {old_value}")
    print(f"   Display: {format_value_for_display('trust_cash', old_value)}")

    # Test new format
    print("\n2. New format (structured):")
    new_value = {
        "value": 345300000,
        "metadata": {
            "note": "15.1% above IPO: 15% overallotment + 0.1% interest",
            "validation": "acceptable_range"
        }
    }
    print(f"   Input: {json.dumps(new_value, indent=2)}")
    print(f"   Display: {format_value_for_display('trust_cash', new_value)}")

    # Test None
    print("\n3. None value (new format):")
    none_value = {
        "value": None,
        "metadata": {
            "note": "No data available"
        }
    }
    print(f"   Input: {json.dumps(none_value, indent=2)}")
    print(f"   Display: {format_value_for_display('trust_value', none_value)}")

    # Test Telegram format
    print("\n4. Telegram message format:")
    final_fix = {
        "trust_cash": {
            "value": 345300000,
            "metadata": {
                "note": "15.1% above IPO: 15% overallotment + 0.1% interest"
            }
        },
        "trust_value": {
            "value": None,
            "metadata": {
                "note": "No data available"
            }
        }
    }
    message = format_correction_for_telegram("CEP", final_fix)
    print(message)

    # Test comparison
    print("\n5. Before/After comparison:")
    old = "<= $345.3M (15.1% above IPO...)"
    new = {
        "value": 345300000,
        "metadata": {
            "note": "15.1% above IPO: 15% overallotment + 0.1% interest"
        }
    }
    comparison = format_correction_comparison("trust_cash", old, new)
    print(comparison)
