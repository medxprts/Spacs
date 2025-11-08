"""
Deal Detector Agent

Detects and extracts business combination announcements from:
- 8-K Item 1.01 (Entry into Material Definitive Agreement)
- Form 425 (Communications about business combinations)
"""

import os
import sys
import json
import requests
from typing import Dict, Optional
from bs4 import BeautifulSoup
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from database import SessionLocal, SPAC
from utils.deal_value_tracker import update_deal_value
from utils.deal_structure_tracker import update_deal_structure
from utils.target_validator import validate_target, sanitize_target
from utils.expected_close_normalizer import normalize_expected_close

# AI for extraction
try:
    from openai import OpenAI
    AI_CLIENT = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com"
    )
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False


class DealDetectorAgent(BaseAgent):
    """Detects deal announcements from 8-K and Form 425 filings"""

    def __init__(self):
        super().__init__("DealDetector")
        self.headers = {
            'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'
        }

    async def can_process(self, filing: Dict) -> bool:
        """Check if this is a deal-related filing"""
        filing_type = filing.get('type', '')

        # Can process 8-K and Form 425
        return filing_type in ['8-K', '425']

    async def process(self, filing: Dict) -> Optional[Dict]:
        """Extract deal announcement from filing"""

        print(f"\n   🔍 {self.name}: Analyzing {filing['type']} from {filing['date'].strftime('%Y-%m-%d')}")

        # Use pre-fetched content if available (from SEC monitor), otherwise fetch
        content = filing.get('content')
        if not content:
            print(f"      📥 Fetching filing content...")
            content = self._fetch_filing_content(filing['url'])
        else:
            print(f"      ✓ Using pre-fetched content ({len(content):,} chars)")

        if not content:
            return None

        # Check for deal keywords
        if not self._has_deal_keywords(content):
            print(f"      ℹ️  No deal keywords found")
            return None

        # Extract deal details with AI
        deal_data = self._extract_deal_with_ai(content, filing)

        if not deal_data or not deal_data.get('target'):
            print(f"      ⚠️  Could not extract deal details from current filing")

            # ===== FEW-SHOT LEARNING: Try searching other filings for missing target =====
            if deal_data and not deal_data.get('target'):
                print(f"      🔍 Attempting to find target in other filings...")
                from database import SessionLocal

                db = SessionLocal()
                try:
                    # Get ticker from CIK
                    from database import SPAC
                    spac = db.query(SPAC).filter(SPAC.cik == filing['cik']).first()

                    if spac:
                        target = self.search_for_missing_data(
                            ticker=spac.ticker,
                            field='target',
                            db_session=db
                        )

                        if target:
                            print(f"      ✅ Found target in other filings: {target}")
                            deal_data['target'] = target
                finally:
                    db.close()

            # If still no deal data or target, give up
            if not deal_data or not deal_data.get('target'):
                return None

        # Update database
        updated = self._update_database(filing['cik'], deal_data, filing)

        if updated:
            print(f"      ✅ Deal detected: {deal_data['target']}")
            return {
                **deal_data,
                'filing_url': filing['url'],
                'filing_date': filing['date']
            }

        return None

    def _fetch_filing_content(self, url: str) -> Optional[str]:
        """Fetch and parse filing content"""
        try:
            # Get filing page
            response = requests.get(url, headers=self.headers, timeout=30)

            if response.status_code != 200:
                return None

            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Try to find the main document link
            # SEC filing pages have a table with document links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.htm' in href and 'd8k' in href.lower():
                    # This is the main 8-K document
                    doc_url = f"https://www.sec.gov{href}" if href.startswith('/') else href
                    doc_response = requests.get(doc_url, headers=self.headers, timeout=30)
                    doc_soup = BeautifulSoup(doc_response.text, 'html.parser')
                    return doc_soup.get_text()

            # Fallback: use the page we already have
            return soup.get_text()

        except Exception as e:
            print(f"      ⚠️  Error fetching content: {e}")
            return None

    def _has_deal_keywords(self, content: str) -> bool:
        """Check if content contains deal-related keywords"""
        content_lower = content.lower()

        deal_keywords = [
            'definitive agreement',
            'business combination agreement',
            'merger agreement',
            'announce the proposed business combination',
            'entered into a business combination'
        ]

        return any(keyword in content_lower for keyword in deal_keywords)

    def _extract_deal_with_ai(self, content: str, filing: Dict) -> Optional[Dict]:
        """Use AI to extract deal details with Few-Shot learning"""

        if not AI_AVAILABLE:
            return None

        try:
            # Limit content to relevant section (first 50k chars)
            excerpt = content[:50000]

            # ===== FEW-SHOT LEARNING: Query past lessons =====
            from utils.extraction_learner import format_lessons_for_prompt

            # Get lessons for numeric fields (most prone to format errors)
            key_fields = ['earnout_shares', 'pipe_size', 'deal_value', 'target']
            lessons_text = ""

            for field in key_fields:
                field_lessons = self.get_lessons_for_field(field)
                if field_lessons.get('format_warnings') or field_lessons.get('common_mistakes'):
                    lessons_text += format_lessons_for_prompt(field_lessons)

            if lessons_text:
                print(f"      📚 Applying {len(lessons_text.split(chr(10)))} past learnings to extraction")

            # Build enhanced prompt with learnings
            prompt = f"""
Extract business combination deal details from this SEC filing:

Filing Type: {filing['type']}
Filing Date: {filing['date'].strftime('%Y-%m-%d')}

{lessons_text}

Extract:
1. **target** - Target company name
2. **deal_value** - Enterprise or equity value as numeric dollars (e.g., 500000000 for "$500M")
3. **expected_close** - Expected closing date or quarter (e.g., "Q4 2025", "2026-06-30")
4. **target_sector** - Target company's industry/sector. Classify as: "AI & Machine Learning", "Healthcare Technology", "Electric Vehicles", "FinTech", "Cybersecurity", "Space Technology", "Clean Energy", "Blockchain & Crypto", "Technology", "Healthcare", "Financial Services", "Consumer", "Industrial", "Media & Entertainment", "Real Estate", or "Other"

Deal Structure (if mentioned):
5. **min_cash** - Minimum cash condition as numeric dollars (e.g., 200000000 for "$200M")
6. **min_cash_percentage** - Minimum cash as percentage (e.g., 25.0 for "25%")
7. **pipe_size** - PIPE investment amount as numeric dollars (e.g., 100000000 for "$100M")
8. **pipe_price** - PIPE share price as numeric dollars (e.g., 10.0 for "$10.00")
9. **earnout_shares** - Earnout/contingent shares as numeric count (e.g., 5000000 for "5M shares")
10. **forward_purchase** - Forward purchase agreement amount as numeric dollars (e.g., 50000000 for "$50M")

IMPORTANT: Return all dollar amounts and share counts as NUMERIC VALUES (not formatted strings).
- Convert "$275M" to 275000000
- Convert "$1.2B" to 1200000000
- Convert "5M shares" to 5000000
- Convert "$10.00" to 10.0

Return JSON:
{{
    "target": "Target Company Inc.",
    "deal_value": 500000000,
    "expected_close": "Q4 2025",
    "target_sector": "Technology",
    "min_cash": 200000000,
    "min_cash_percentage": 25.0,
    "pipe_size": 100000000,
    "pipe_price": 10.0,
    "earnout_shares": 5000000,
    "forward_purchase": 50000000
}}

If any field is not found, return null for that field.

Text:
{excerpt}
"""

            response = AI_CLIENT.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are an SEC filing extraction expert. Extract deal announcement data precisely."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )

            data = json.loads(response.choices[0].message.content)

            # Sanitize numeric fields (AI sometimes returns "1.1M" instead of 1100000)
            from utils.number_parser import sanitize_ai_response, MONEY_FIELDS, SHARE_FIELDS
            numeric_fields = ['deal_value', 'pipe_size', 'pipe_price', 'earnout_shares',
                            'forward_purchase', 'min_cash', 'min_cash_percentage']
            data = sanitize_ai_response(data, numeric_fields)

            return data

        except Exception as e:
            print(f"      ⚠️  AI extraction failed: {e}")
            return None

    def _update_database(self, cik: str, deal_data: Dict, filing: Dict) -> bool:
        """Update SPAC database with deal announcement"""

        db = SessionLocal()
        try:
            # Find SPAC by CIK
            spac = db.query(SPAC).filter(SPAC.cik == cik).first()

            if not spac:
                print(f"      ⚠️  SPAC not found for CIK {cik}")
                return False

            # Skip if already has a deal
            if spac.deal_status == 'ANNOUNCED' and spac.announced_date:
                print(f"      ℹ️  {spac.ticker} already has a deal ({spac.target})")
                return False

            # Validate target name before setting
            target_name = deal_data.get('target')
            if target_name:
                target_name = sanitize_target(target_name)
                is_valid, reason = validate_target(target_name, spac.ticker)

                if not is_valid:
                    print(f"      ⚠️  Invalid target rejected: '{target_name}'")
                    print(f"      ⚠️  Reason: {reason}")
                    print(f"      ⚠️  Skipping deal update - target appears to be sponsor/trustee entity")
                    # Log this as an anomaly for Investigation Agent
                    from utils.error_detector import log_manual_error
                    log_manual_error(
                        error_type='InvalidTargetExtraction',
                        error_message=f"AI extracted invalid target: '{target_name}' - {reason}",
                        script='deal_detector_agent.py',
                        function='_update_database',
                        ticker=spac.ticker,
                        context={
                            'extracted_target': target_name,
                            'validation_failure': reason,
                            'filing_url': filing['url'],
                            'filing_date': filing['date'].strftime('%Y-%m-%d')
                        }
                    )
                    return False

            # Update deal fields
            spac.deal_status = 'ANNOUNCED'
            spac.target = target_name  # Use validated/sanitized target

            # Normalize expected_close to proper date (Q1 2026 → 2026-02-15, etc.)
            expected_close_text = deal_data.get('expected_close')
            spac.expected_close = normalize_expected_close(expected_close_text)

            spac.announced_date = filing['date'].date()
            spac.deal_filing_url = filing['url']

            # Use date-based precedence for deal_value
            if deal_data.get('deal_value'):
                # Convert numeric value to formatted string
                deal_value_num = deal_data.get('deal_value')
                if isinstance(deal_value_num, (int, float)):
                    # Format as $XXM or $X.XB
                    if deal_value_num >= 1_000_000_000:
                        deal_value_str = f"${deal_value_num / 1_000_000_000:.2f}B"
                    else:
                        deal_value_str = f"${deal_value_num / 1_000_000:.0f}M"
                else:
                    deal_value_str = str(deal_value_num)

                update_deal_value(
                    db_session=db,
                    ticker=spac.ticker,
                    new_value=deal_value_str,
                    source='8-K',
                    filing_date=filing['date'].date(),
                    reason='Deal detected by orchestrator'
                )

            # Use tracker for deal structure fields
            structure_fields = {
                'min_cash': deal_data.get('min_cash'),
                'min_cash_percentage': deal_data.get('min_cash_percentage'),
                'pipe_size': deal_data.get('pipe_size'),
                'pipe_price': deal_data.get('pipe_price'),
                'earnout_shares': deal_data.get('earnout_shares'),
                'forward_purchase': deal_data.get('forward_purchase')
            }

            # Filter out None values
            structure_fields = {k: v for k, v in structure_fields.items() if v is not None}

            if structure_fields:
                update_deal_structure(
                    db_session=db,
                    ticker=spac.ticker,
                    structure_data=structure_fields,
                    source='8-K',
                    filing_date=filing['date'].date(),
                    reason='Deal structure from announcement'
                )

            # Store current price at announcement (if available)
            if spac.price:
                spac.price_at_announcement = spac.price

            # Store target sector if provided by AI extraction
            if deal_data.get('target_sector'):
                spac.sector_classified = deal_data['target_sector']

            # If no sector from filing, classify based on target name
            elif target_name and not spac.sector_classified:
                try:
                    from utils.target_sector_classifier import classify_target_sector
                    sector = classify_target_sector(target_name)
                    if sector:
                        spac.sector_classified = sector
                        print(f"      ✓ Classified target sector: {sector}")
                except Exception as e:
                    print(f"      ⚠️  Could not classify target sector: {e}")

            db.commit()

            # ===== FEW-SHOT LEARNING: Log successful extractions =====
            from utils.extraction_learner import log_extraction_success

            # Log each successfully extracted field for future learning
            extracted_fields = {
                'target': target_name,
                'deal_value': deal_data.get('deal_value'),
                'pipe_size': deal_data.get('pipe_size'),
                'earnout_shares': deal_data.get('earnout_shares'),
                'min_cash': deal_data.get('min_cash'),
                'forward_purchase': deal_data.get('forward_purchase')
            }

            for field_name, field_value in extracted_fields.items():
                if field_value is not None:
                    try:
                        log_extraction_success(
                            agent_name='deal_detector',
                            field=field_name,
                            value=field_value,
                            ticker=spac.ticker,
                            filing_type=filing['type'],
                            filing_section='Main document'
                        )
                    except Exception as log_err:
                        # Don't let logging failure block execution
                        print(f"      ⚠️  Could not log learning for {field_name}: {log_err}")

            print(f"      ✓ Updated {spac.ticker}: deal_status=ANNOUNCED")
            return True

        except Exception as e:
            db.rollback()
            print(f"      ❌ Database update failed: {e}")

            # Log failure and send alert
            try:
                from utils.database_monitor import log_write_failure
                log_write_failure(
                    operation='deal_update',
                    ticker=spac.ticker,
                    error=e,
                    context={
                        'target': deal_data.get('target'),
                        'deal_value': deal_data.get('deal_value'),
                        'announced_date': deal_data.get('announced_date')
                    }
                )
            except:
                pass  # Don't let monitoring failure block execution

            return False

        finally:
            db.close()
