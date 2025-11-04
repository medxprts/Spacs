"""
Extraction Learner - Centralized Few-Shot Learning for Extraction Agents

Provides query interface to learning database for proactive error prevention.

Key Functions:
- get_extraction_lessons() - Get past format errors and filing hints for a field
- get_filing_search_strategy() - Get where to search based on past successes
- log_extraction_success() - Log successful extraction for future learning
- log_format_prevention() - Log when past learnings prevented an error

Architecture:
- Centralized database (data_quality_conversations)
- Field-based queries (not agent-specific)
- Cross-agent learning (all agents benefit from each other's discoveries)

Example:
    # Before extracting earnout_shares
    lessons = get_extraction_lessons(field='earnout_shares')

    # Use lessons in AI prompt
    prompt = f'''
    Extract earnout_shares.

    **Past Errors to Avoid**:
    {format_warnings(lessons['format_warnings'])}
    '''

    # After successful extraction
    log_extraction_success(
        agent_name='deal_detector',
        field='earnout_shares',
        value=1100000,
        filing_type='8-K',
        filing_section='EX-2.1'
    )
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import json


def get_extraction_lessons(
    field: str,
    issue_types: List[str] = None,
    limit: int = 10
) -> Dict:
    """
    Query centralized learning database for field-specific lessons

    Returns lessons from ALL agents who have extracted this field,
    including format errors, filing hints, and success patterns.

    Args:
        field: Database field name ('earnout_shares', 'trust_value', etc.)
        issue_types: Types of issues to learn from (default: ['format_error', 'extraction_success'])
        limit: Maximum number of past cases to retrieve (default: 10)

    Returns:
        {
            'format_warnings': [
                "AI returned '1.1M' instead of 1100000 (CHAC, deal_detector, Nov 4)",
                "AI returned '$275M' instead of 275000000 (BLUW, pipe_extractor, Oct 28)"
            ],
            'filing_hints': [
                "Found in 10-Q Item 1 - Financial Statements (5 successes)",
                "Found in S-1 Part II - Financial Data (2 successes)"
            ],
            'common_mistakes': [
                "Don't extract sponsor entities as target (3 occurrences)",
                "Check if value is 'TBD' or 'N/A' before returning (2 occurrences)"
            ],
            'success_patterns': [
                "Look for '$X.XX per share' in trust account section",
                "Check EX-2.1 Business Combination Agreement for earnouts"
            ],
            'contributing_agents': ['deal_detector', 'redemption_extractor']
        }

    Example:
        # Get lessons before extracting earnout_shares
        lessons = get_extraction_lessons('earnout_shares')

        # Include in AI prompt
        if lessons['format_warnings']:
            prompt += "\\n**Past Format Errors**:\\n"
            for warning in lessons['format_warnings']:
                prompt += f"- {warning}\\n"
    """
    from sqlalchemy import text
    from database import SessionLocal

    if issue_types is None:
        issue_types = ['format_error', 'extraction_success', 'validation_error']

    db = SessionLocal()
    try:
        # Query all learnings for this field
        query = text("""
            SELECT
                issue_type,
                ticker,
                original_data,
                final_fix,
                learning_notes,
                created_at,
                messages
            FROM data_quality_conversations
            WHERE field = :field
              AND issue_type = ANY(:issue_types)
              AND learning_notes IS NOT NULL
              AND created_at >= NOW() - INTERVAL '90 days'
            ORDER BY created_at DESC
            LIMIT :limit
        """)

        results = db.execute(query, {
            'field': field,
            'issue_types': issue_types,
            'limit': limit
        }).fetchall()

        # Aggregate learnings
        format_warnings = []
        filing_hints = []
        common_mistakes = []
        success_patterns = []
        contributing_agents = set()

        for row in results:
            notes = row.learning_notes or ''
            ticker = row.ticker or 'Unknown'
            date = row.created_at.strftime('%b %d') if row.created_at else ''

            # Extract agent name from notes or original_data
            agent_name = 'unknown'
            if row.original_data:
                try:
                    original = json.loads(row.original_data) if isinstance(row.original_data, str) else row.original_data
                    agent_name = original.get('agent_name', 'unknown')
                except:
                    pass

            contributing_agents.add(agent_name)

            # Categorize learnings
            if row.issue_type == 'format_error':
                # Format error warning
                if 'AI returned' in notes or 'returned' in notes.lower():
                    # Extract the key lesson
                    format_warnings.append(f"{notes.split('.')[0]} ({ticker}, {agent_name}, {date})")
                else:
                    format_warnings.append(f"{notes} ({ticker}, {date})")

            elif row.issue_type == 'extraction_success':
                # Filing hint or success pattern
                if 'found in' in notes.lower():
                    filing_hints.append(notes)
                elif 'look for' in notes.lower() or 'pattern' in notes.lower():
                    success_patterns.append(notes)

            elif row.issue_type == 'validation_error':
                # Common mistake to avoid
                common_mistakes.append(notes)

        return {
            'format_warnings': format_warnings[:5],  # Top 5 most recent
            'filing_hints': filing_hints[:3],        # Top 3 most successful
            'common_mistakes': common_mistakes[:3],  # Top 3 mistakes
            'success_patterns': success_patterns[:3], # Top 3 patterns
            'contributing_agents': list(contributing_agents),
            'total_learnings': len(results)
        }

    except Exception as e:
        print(f"   ⚠️  Error querying extraction lessons: {e}")
        return {
            'format_warnings': [],
            'filing_hints': [],
            'common_mistakes': [],
            'success_patterns': [],
            'contributing_agents': [],
            'total_learnings': 0
        }
    finally:
        db.close()


def get_filing_search_strategy(field: str, ticker: str = None) -> Dict:
    """
    Get smart filing search strategy based on past successful extractions

    Analyzes past successes to determine:
    - Which filing type most frequently contains this field
    - Which sections to check first
    - Fallback sources if primary fails
    - How far back to search

    Args:
        field: Database field name
        ticker: Optional ticker to prioritize similar SPACs

    Returns:
        {
            'primary_source': '10-Q',
            'section_hints': ['Item 1', 'Financial Statements', 'Balance Sheet'],
            'fallback_sources': ['S-1', '8-K'],
            'lookback_days': 90,
            'confidence': 0.85,  # Based on past success rate
            'past_successes': 12  # Number of times this strategy worked
        }

    Example:
        # Get strategy for finding trust_value
        strategy = get_filing_search_strategy('trust_value')

        # Search in priority order
        for filing_type in [strategy['primary_source']] + strategy['fallback_sources']:
            filings = fetch_filings(ticker, filing_type)
            for filing in filings:
                value = extract_from_filing(filing)
                if value:
                    return value
    """
    from sqlalchemy import text
    from database import SessionLocal

    db = SessionLocal()
    try:
        # Query successful extractions for this field
        query = text("""
            SELECT
                original_data,
                final_fix,
                COUNT(*) as success_count
            FROM data_quality_conversations
            WHERE field = :field
              AND issue_type = 'extraction_success'
              AND final_fix IS NOT NULL
              AND created_at >= NOW() - INTERVAL '180 days'
            GROUP BY original_data, final_fix
            ORDER BY success_count DESC
            LIMIT 10
        """)

        results = db.execute(query, {'field': field}).fetchall()

        if not results:
            # No past data, return default strategy based on field type
            return _get_default_strategy(field)

        # Analyze successful extractions
        filing_type_counts = {}
        section_mentions = []
        total_successes = 0

        for row in results:
            try:
                original = json.loads(row.original_data) if isinstance(row.original_data, str) else row.original_data
                filing_type = original.get('filing_type', 'Unknown')
                filing_section = original.get('filing_section', '')

                filing_type_counts[filing_type] = filing_type_counts.get(filing_type, 0) + row.success_count

                if filing_section:
                    section_mentions.append(filing_section)

                total_successes += row.success_count
            except:
                continue

        # Determine primary source (most successful filing type)
        if filing_type_counts:
            primary_source = max(filing_type_counts, key=filing_type_counts.get)
            primary_successes = filing_type_counts[primary_source]
            confidence = primary_successes / total_successes if total_successes > 0 else 0

            # Fallback sources (other successful types)
            fallback_sources = [ft for ft in filing_type_counts.keys() if ft != primary_source]
        else:
            return _get_default_strategy(field)

        # Extract section hints (most common sections)
        section_hints = list(set(section_mentions))[:3]

        # Determine lookback period (default 90 days)
        lookback_days = 90

        return {
            'primary_source': primary_source,
            'section_hints': section_hints,
            'fallback_sources': fallback_sources[:2],  # Top 2 fallbacks
            'lookback_days': lookback_days,
            'confidence': round(confidence, 2),
            'past_successes': total_successes
        }

    except Exception as e:
        print(f"   ⚠️  Error getting filing search strategy: {e}")
        return _get_default_strategy(field)
    finally:
        db.close()


def _get_default_strategy(field: str) -> Dict:
    """
    Return default filing search strategy based on field type

    Used when no past extraction data is available.
    """
    # Trust account data (periodic)
    if field in ['trust_value', 'trust_cash', 'shares_outstanding']:
        return {
            'primary_source': '10-Q',
            'section_hints': ['Item 1', 'Financial Statements', 'Balance Sheet'],
            'fallback_sources': ['10-K', 'S-1'],
            'lookback_days': 90,
            'confidence': 0.5,
            'past_successes': 0
        }

    # Deal data (event-based)
    elif field in ['target', 'deal_value', 'announced_date', 'earnout_shares', 'pipe_size']:
        return {
            'primary_source': '8-K',
            'section_hints': ['Item 1.01', 'Item 8.01', 'EX-2.1', 'EX-99.1'],
            'fallback_sources': ['DEFM14A', '425'],
            'lookback_days': 180,
            'confidence': 0.5,
            'past_successes': 0
        }

    # IPO data (one-time)
    elif field in ['ipo_date', 'ipo_price', 'ipo_proceeds', 'unit_structure']:
        return {
            'primary_source': 'S-1',
            'section_hints': ['Prospectus', 'Part I'],
            'fallback_sources': ['424B4', '8-K'],
            'lookback_days': 365,
            'confidence': 0.5,
            'past_successes': 0
        }

    # Generic fallback
    else:
        return {
            'primary_source': '8-K',
            'section_hints': [],
            'fallback_sources': ['10-Q', 'S-1'],
            'lookback_days': 90,
            'confidence': 0.3,
            'past_successes': 0
        }


def log_extraction_success(
    agent_name: str,
    field: str,
    value: Any,
    ticker: str,
    filing_type: str,
    filing_section: str = None,
    extraction_method: str = 'AI with learnings'
):
    """
    Log successful extraction to build filing search hints

    Creates positive examples in learning database that inform future
    extraction strategies. Each success strengthens the filing hint.

    Args:
        agent_name: Agent that performed extraction
        field: Database field extracted
        value: Extracted value
        ticker: SPAC ticker
        filing_type: Type of filing ('8-K', '10-Q', etc.)
        filing_section: Section where found (optional)
        extraction_method: How extracted (default: 'AI with learnings')

    Example:
        # After successfully extracting earnout_shares
        log_extraction_success(
            agent_name='deal_detector',
            field='earnout_shares',
            value=1100000,
            ticker='CHAC',
            filing_type='8-K',
            filing_section='EX-2.1 Business Combination Agreement'
        )

        # This builds the filing hint:
        # "Found earnout_shares in 8-K EX-2.1 (5 successes)"
    """
    from sqlalchemy import text
    from database import SessionLocal
    import hashlib

    db = SessionLocal()
    try:
        # Create unique issue ID
        issue_id = hashlib.md5(
            f"{field}_{ticker}_{filing_type}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        # Build learning note
        section_text = f" {filing_section}" if filing_section else ""
        learning_note = f"Successfully extracted {field} from {filing_type}{section_text}"

        # Original data (extraction context)
        original_data = {
            'agent_name': agent_name,
            'filing_type': filing_type,
            'filing_section': filing_section,
            'extraction_method': extraction_method,
            'timestamp': datetime.now().isoformat()
        }

        # Final fix (extracted value)
        final_fix = {
            'field': field,
            'value': value,
            'source': filing_type,
            'confidence': 'high'
        }

        # Insert into learning database
        query = text("""
            INSERT INTO data_quality_conversations (
                issue_id, issue_type, issue_source, field, ticker,
                original_data, final_fix, learning_notes,
                status, completed_at, created_at
            ) VALUES (
                :issue_id, 'extraction_success', 'agent_learning', :field, :ticker,
                :original_data, :final_fix, :learning_notes,
                'completed', NOW(), NOW()
            )
            ON CONFLICT (issue_id) DO NOTHING
        """)

        db.execute(query, {
            'issue_id': issue_id,
            'field': field,
            'ticker': ticker,
            'original_data': json.dumps(original_data),
            'final_fix': json.dumps(final_fix),
            'learning_notes': learning_note
        })

        db.commit()
        print(f"   📚 Logged extraction success: {field} from {filing_type}")

    except Exception as e:
        db.rollback()
        print(f"   ⚠️  Could not log extraction success: {e}")
    finally:
        db.close()


def log_format_prevention(
    agent_name: str,
    field: str,
    ticker: str,
    prevented_value: str,
    correct_value: Any,
    lesson_applied: str
):
    """
    Log when past learnings prevented a format error

    This tracks the effectiveness of Few-Shot learning by recording
    when a past lesson successfully prevented an error.

    Args:
        agent_name: Agent that used the learning
        field: Field being extracted
        ticker: SPAC ticker
        prevented_value: What AI would have returned without learning
        correct_value: Correct value after applying lesson
        lesson_applied: Which lesson was used

    Example:
        # AI almost returned "1.1M" but lesson prevented it
        log_format_prevention(
            agent_name='deal_detector',
            field='earnout_shares',
            ticker='NEWSPAC',
            prevented_value='1.1M',
            correct_value=1100000,
            lesson_applied='AI returned "1.1M" instead of 1100000 (CHAC, Nov 4)'
        )

        # This proves the learning system is working!
    """
    from sqlalchemy import text
    from database import SessionLocal
    import hashlib

    db = SessionLocal()
    try:
        issue_id = hashlib.md5(
            f"prevented_{field}_{ticker}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        learning_note = f"Prevented format error: AI would have returned '{prevented_value}', corrected to {correct_value} using past lesson"

        original_data = {
            'agent_name': agent_name,
            'would_have_returned': prevented_value,
            'lesson_applied': lesson_applied,
            'prevention_method': 'few_shot_learning'
        }

        final_fix = {
            'field': field,
            'correct_value': correct_value,
            'error_prevented': True
        }

        query = text("""
            INSERT INTO data_quality_conversations (
                issue_id, issue_type, issue_source, field, ticker,
                original_data, final_fix, learning_notes,
                status, completed_at, created_at
            ) VALUES (
                :issue_id, 'format_prevention', 'agent_learning', :field, :ticker,
                :original_data, :final_fix, :learning_notes,
                'completed', NOW(), NOW()
            )
        """)

        db.execute(query, {
            'issue_id': issue_id,
            'field': field,
            'ticker': ticker,
            'original_data': json.dumps(original_data),
            'final_fix': json.dumps(final_fix),
            'learning_notes': learning_note
        })

        db.commit()
        print(f"   ✅ Logged format prevention: {field} ({prevented_value} → {correct_value})")

    except Exception as e:
        db.rollback()
        print(f"   ⚠️  Could not log format prevention: {e}")
    finally:
        db.close()


def format_lessons_for_prompt(lessons: Dict) -> str:
    """
    Format lessons dictionary into prompt-ready text

    Args:
        lessons: Output from get_extraction_lessons()

    Returns:
        Formatted text to include in AI prompts

    Example:
        lessons = get_extraction_lessons('earnout_shares')
        prompt_text = format_lessons_for_prompt(lessons)

        # Returns:
        # **PAST FORMAT ERRORS TO AVOID**:
        # - AI returned '1.1M' instead of 1100000 (CHAC, deal_detector, Nov 4)
        # - AI returned '$275M' instead of 275000000 (BLUW, pipe_extractor, Oct 28)
        #
        # **WHERE TO LOOK** (from past successes):
        # - Found in 8-K EX-2.1 Business Combination Agreement (5 successes)
    """
    sections = []

    if lessons.get('format_warnings'):
        sections.append("**PAST FORMAT ERRORS TO AVOID**:")
        for warning in lessons['format_warnings']:
            sections.append(f"- {warning}")
        sections.append("")  # Blank line

    if lessons.get('filing_hints'):
        sections.append("**WHERE TO LOOK** (from past successes):")
        for hint in lessons['filing_hints']:
            sections.append(f"- {hint}")
        sections.append("")

    if lessons.get('common_mistakes'):
        sections.append("**COMMON MISTAKES TO AVOID**:")
        for mistake in lessons['common_mistakes']:
            sections.append(f"- {mistake}")
        sections.append("")

    if lessons.get('success_patterns'):
        sections.append("**SUCCESS PATTERNS**:")
        for pattern in lessons['success_patterns']:
            sections.append(f"- {pattern}")
        sections.append("")

    return "\n".join(sections) if sections else ""
