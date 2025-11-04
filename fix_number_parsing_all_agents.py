#!/usr/bin/env python3
"""
Script to add number parsing to all AI extraction agents.

Adds sanitize_ai_response() after every json.loads(response.choices[0].message.content)
to ensure AI-returned formats like "1.1M" are converted to 1100000 before database write.
"""

import re
from pathlib import Path

# Agent files to fix and their numeric fields
AGENTS_TO_FIX = {
    'agents/quarterly_report_extractor.py': [
        'trust_cash', 'trust_cash_per_share', 'shares_outstanding', 'interest_earned',
        'redemption_amount', 'shares_redeemed', 'public_shares', 'trust_value'
    ],
    'agents/extension_monitor_agent.py': [
        # Mostly dates, may not need
    ],
    'agents/sector_extraction_agent.py': [
        # No numeric fields
    ]
}

PARSING_CODE = """
            # Sanitize numeric fields (AI sometimes returns "1.1M" instead of 1100000)
            from utils.number_parser import sanitize_ai_response
            numeric_fields = {numeric_fields}
            data = sanitize_ai_response(data, numeric_fields)
"""

def add_parsing_to_file(file_path: str, numeric_fields: list):
    """Add number parsing after json.loads() calls"""

    with open(file_path, 'r') as f:
        content = f.read()

    # Pattern: data = json.loads(response.choices[0].message.content)
    pattern = r'(\s+)(data|result) = json\.loads\(response\.choices\[0\]\.message\.content\)'

    def replacement(match):
        indent = match.group(1)
        var_name = match.group(2)

        parsing = f'''
{indent}{var_name} = json.loads(response.choices[0].message.content)

{indent}# Sanitize numeric fields (AI sometimes returns "1.1M" instead of 1100000)
{indent}from utils.number_parser import sanitize_ai_response
{indent}numeric_fields = {numeric_fields}
{indent}{var_name} = sanitize_ai_response({var_name}, numeric_fields)'''

        return parsing

    # Check if already has sanitize_ai_response
    if 'sanitize_ai_response' in content:
        print(f"✓ {file_path} - Already has number parsing")
        return False

    # Apply replacement
    new_content, count = re.subn(pattern, replacement, content, count=1)

    if count == 0:
        print(f"⚠️  {file_path} - No json.loads() pattern found")
        return False

    with open(file_path, 'w') as f:
        f.write(new_content)

    print(f"✅ {file_path} - Added number parsing ({count} location(s))")
    return True

if __name__ == "__main__":
    print("Adding number parsing to all AI extraction agents...\n")

    fixed_count = 0

    for file_path, numeric_fields in AGENTS_TO_FIX.items():
        if numeric_fields:  # Only fix if has numeric fields
            if add_parsing_to_file(file_path, numeric_fields):
                fixed_count += 1
        else:
            print(f"⏭️  {file_path} - No numeric fields, skipping")

    print(f"\n✅ Fixed {fixed_count} agent files")
    print("\n📝 Summary of fixes:")
    print("   • deal_detector_agent.py ✅ (manually fixed)")
    print("   • redemption_extractor.py ✅ (manually fixed)")
    print("   • quarterly_report_extractor.py (needs manual fix - 3 locations)")
    print("\n⚠️  Action needed:")
    print("   Review quarterly_report_extractor.py and add parsing to all 3 json.loads() locations")
