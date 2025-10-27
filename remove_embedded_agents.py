#!/usr/bin/env python3
"""
Remove embedded agent classes from agent_orchestrator.py
These agents now exist as separate modules in /agents/ folder
"""

import re

# List of agent classes to remove (now extracted to /agents/)
AGENTS_TO_REMOVE = [
    'DealHunterAgent',
    'VoteTrackerAgent',
    'RiskAnalysisAgent',
    'DeadlineExtensionAgent',
    'DataValidatorAgent',
    'PreIPODuplicateCheckerAgent',
    'PremiumAlertAgent',
    'DataQualityFixerAgent'
]

def find_class_range(lines, class_name, start_line):
    """Find the start and end line numbers for a class definition"""

    # Find the class declaration
    for i in range(start_line, len(lines)):
        if lines[i].strip().startswith(f'class {class_name}'):
            class_start = i
            break
    else:
        return None, None

    # Find where the class ends (next class or end of indented block)
    indent_level = len(lines[class_start]) - len(lines[class_start].lstrip())

    for i in range(class_start + 1, len(lines)):
        line = lines[i]

        # Skip blank lines and comments
        if not line.strip() or line.strip().startswith('#'):
            continue

        # Check if this is a new class at same or lower indentation
        current_indent = len(line) - len(line.lstrip())

        # If we find a line at the same or lower indentation level that's not part of the class
        if current_indent <= indent_level and line.strip():
            # This is the end of the class
            return class_start, i - 1

    # Class goes to end of file
    return class_start, len(lines) - 1


def remove_embedded_agents(input_file, output_file):
    """Remove embedded agent classes from orchestrator"""

    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    print(f"📄 Loaded {input_file}: {len(lines)} lines")

    # Track which lines to keep
    lines_to_remove = set()

    for agent_name in AGENTS_TO_REMOVE:
        start, end = find_class_range(lines, agent_name, 0)

        if start is None:
            print(f"   ⚠️  {agent_name}: not found (may already be removed)")
            continue

        # Mark these lines for removal
        for i in range(start, end + 1):
            lines_to_remove.add(i)

        print(f"   🗑️  {agent_name}: lines {start+1}-{end+1} ({end-start+1} lines)")

    # Create new file with only non-removed lines
    output_lines = [line for i, line in enumerate(lines) if i not in lines_to_remove]

    print(f"\n✂️  Removed {len(lines_to_remove)} lines")
    print(f"📝 New file: {len(output_lines)} lines")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(output_lines)

    print(f"✅ Saved to {output_file}")

    return len(lines_to_remove), len(output_lines)


if __name__ == '__main__':
    removed, remaining = remove_embedded_agents(
        'agent_orchestrator.py',
        'agent_orchestrator_cleaned.py'
    )

    print(f"\n🎯 SUMMARY")
    print(f"   Lines removed: {removed}")
    print(f"   Lines remaining: {remaining}")
    print(f"\n📋 Next steps:")
    print(f"   1. Review: agent_orchestrator_cleaned.py")
    print(f"   2. Test: python3 agent_orchestrator_cleaned.py --test")
    print(f"   3. Deploy: mv agent_orchestrator_cleaned.py agent_orchestrator.py")
