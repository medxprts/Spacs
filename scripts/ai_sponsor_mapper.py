#!/usr/bin/env python3
"""
AI-Powered Sponsor Family Mapper
=================================
Uses AI + existing mappings to automatically map sponsor variations to performance families.

Instead of manual pattern matching, this:
1. Queries all sponsors from database
2. Loads existing family mappings
3. Uses AI to identify which sponsors belong to same family
4. Updates sponsor_performance table with comprehensive aliases

Example:
    "Cantor Equity Partners V, Inc." → "Cantor Fitzgerald" family
    "Klein Sponsor LLC" → "Churchill Capital" family
    "Gores Sponsor X LLC" → "The Gores Group" family
"""

import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, engine
from sqlalchemy import text
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# AI Setup
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
AI_CLIENT = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)


def load_existing_mappings():
    """Load existing sponsor family mappings from JSON"""
    try:
        with open('/home/ubuntu/spac-research/sponsor_family_mappings.json', 'r') as f:
            mappings = json.load(f)

        # Convert to family → variations dict
        family_map = {}
        for entry in mappings:
            family = entry.get('new_normalized')
            sponsor = entry.get('sponsor')

            if family not in family_map:
                family_map[family] = {
                    'variations': set(),
                    'principals': entry.get('principals', [])
                }

            family_map[family]['variations'].add(sponsor)

        return family_map
    except Exception as e:
        print(f"Warning: Could not load existing mappings: {e}")
        return {}


def get_all_database_sponsors():
    """Get all unique sponsors from database"""
    db = SessionLocal()
    try:
        result = db.execute(text("""
            SELECT DISTINCT sponsor
            FROM spacs
            WHERE sponsor IS NOT NULL
            ORDER BY sponsor
        """))

        sponsors = [row[0] for row in result]
        return sponsors
    finally:
        db.close()


def get_performance_sponsors():
    """Get all sponsors from performance database"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT sponsor_name, sponsor_aliases
            FROM sponsor_performance
            ORDER BY sponsor_name
        """))

        return [(row[0], row[1] or []) for row in result]


def map_sponsor_with_ai(sponsor_name, performance_sponsors, existing_families):
    """Use AI to map sponsor to performance family"""

    # Build context from performance sponsors and existing families
    perf_list = "\n".join([f"- {name}" for name, _ in performance_sponsors])

    family_context = []
    for family, data in existing_families.items():
        variations = ", ".join(list(data['variations'])[:5])  # Sample 5
        family_context.append(f"- {family}: {variations}")

    family_context_str = "\n".join(family_context[:20])

    prompt = f"""Given this sponsor name from our SPAC database:
"{sponsor_name}"

And these existing sponsor performance families:
{perf_list}

And these known sponsor family patterns:
{family_context_str}

Determine which performance sponsor family this belongs to. Return ONLY a JSON object:

{{
  "performance_family": "<exact match from performance list or null>",
  "confidence": <0-100>,
  "reasoning": "<1 sentence why>"
}}

Examples:
- "Cantor Equity Partners V, Inc." → {{"performance_family": "Cantor Fitzgerald", "confidence": 95, "reasoning": "Cantor Equity Partners is the SPAC series from Cantor Fitzgerald"}}
- "Klein Sponsor LLC" → {{"performance_family": "Churchill Capital", "confidence": 90, "reasoning": "Klein Sponsor is Michael Klein's vehicle for Churchill Capital SPACs"}}
- "First SPAC LLC" → {{"performance_family": null, "confidence": 80, "reasoning": "No clear match to existing performance families"}}

Return ONLY valid JSON, no markdown."""

    try:
        response = AI_CLIENT.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )

        content = response.choices[0].message.content.strip()

        # Remove markdown if present
        if content.startswith('```'):
            content = content.split('```')[1]
            if content.startswith('json'):
                content = content[4:]
            content = content.strip()

        data = json.loads(content)
        return data

    except Exception as e:
        print(f"  ❌ AI error for '{sponsor_name}': {e}")
        return None


def update_sponsor_aliases(performance_family, new_alias):
    """Add new alias to sponsor performance table"""
    with engine.connect() as conn:
        # Get current aliases
        result = conn.execute(
            text("SELECT sponsor_aliases FROM sponsor_performance WHERE sponsor_name = :name"),
            {'name': performance_family}
        ).fetchone()

        if not result:
            print(f"  ⚠️  Performance family '{performance_family}' not found in database")
            return False

        current_aliases = result[0] or []

        # Add new alias if not already present
        if new_alias not in current_aliases and new_alias != performance_family:
            current_aliases.append(new_alias)

            conn.execute(text("""
                UPDATE sponsor_performance
                SET sponsor_aliases = :aliases
                WHERE sponsor_name = :name
            """), {
                'aliases': current_aliases,
                'name': performance_family
            })

            conn.commit()
            return True

        return False


def main():
    print("="*80)
    print("AI-POWERED SPONSOR FAMILY MAPPER")
    print("="*80)

    # Load existing mappings
    print("\n📁 Loading existing family mappings...")
    existing_families = load_existing_mappings()
    print(f"   Found {len(existing_families)} existing families")

    # Get all sponsors
    print("\n📊 Querying database sponsors...")
    db_sponsors = get_all_database_sponsors()
    print(f"   Found {len(db_sponsors)} unique sponsors in database")

    # Get performance sponsors
    print("\n🎯 Loading performance sponsors...")
    perf_sponsors = get_performance_sponsors()
    print(f"   Found {len(perf_sponsors)} performance families")

    # Map each sponsor
    print(f"\n🤖 Mapping {len(db_sponsors)} sponsors with AI...\n")

    mapped_count = 0
    alias_added_count = 0
    no_match_count = 0

    # Track results for summary
    mappings = []

    for i, sponsor in enumerate(db_sponsors, 1):
        print(f"[{i:3d}/{len(db_sponsors)}] {sponsor[:50]:50s} ", end="")

        # Map with AI
        result = map_sponsor_with_ai(sponsor, perf_sponsors, existing_families)

        if not result:
            print("❌ AI error")
            continue

        if result['performance_family'] and result['confidence'] >= 70:
            # Add alias
            added = update_sponsor_aliases(result['performance_family'], sponsor)

            if added:
                print(f"✅ → {result['performance_family'][:30]:30s} ({result['confidence']}%)")
                alias_added_count += 1
            else:
                print(f"ℹ️  Already mapped to {result['performance_family'][:30]:30s}")

            mapped_count += 1
            mappings.append({
                'sponsor': sponsor,
                'family': result['performance_family'],
                'confidence': result['confidence'],
                'reasoning': result['reasoning']
            })
        else:
            print(f"⚠️  No match (confidence: {result.get('confidence', 0)}%)")
            no_match_count += 1
            mappings.append({
                'sponsor': sponsor,
                'family': None,
                'confidence': result.get('confidence', 0),
                'reasoning': result.get('reasoning', 'Unknown')
            })

    print(f"\n{'='*80}")
    print(f"SUMMARY:")
    print(f"  Total sponsors: {len(db_sponsors)}")
    print(f"  Mapped to families: {mapped_count}")
    print(f"  New aliases added: {alias_added_count}")
    print(f"  No match: {no_match_count}")
    print(f"{'='*80}")

    # Save detailed mappings
    output_file = '/home/ubuntu/spac-research/ai_sponsor_mappings.json'
    with open(output_file, 'w') as f:
        json.dump(mappings, f, indent=2)

    print(f"\n💾 Detailed mappings saved to: {output_file}")

    # Show top families by alias count
    print("\n🏆 TOP SPONSOR FAMILIES BY ALIAS COUNT:")
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT sponsor_name,
                   array_length(sponsor_aliases, 1) as alias_count,
                   sponsor_aliases[1:3] as sample_aliases
            FROM sponsor_performance
            WHERE sponsor_aliases IS NOT NULL
            ORDER BY array_length(sponsor_aliases, 1) DESC
            LIMIT 10
        """))

        for row in result:
            name, count, sample = row
            print(f"  {name[:40]:40s} | {count:2d} aliases | Sample: {sample}")


if __name__ == '__main__':
    main()
