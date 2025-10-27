#!/usr/bin/env python3
"""
SEC Filing Fetcher - Shared Utility for SEC API Access

Consolidates SEC fetching logic to avoid duplication across agents.
Provides rate limiting, caching, retries, and error handling.

Used by all extraction agents: VoteExtractor, MergerProxyExtractor,
QuarterlyReportExtractor, etc.
"""

import requests
import time
import feedparser
import warnings
from typing import Dict, List, Optional, Tuple
from functools import lru_cache
from datetime import datetime
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning


class SECFilingFetcher:
    """
    Shared utility for fetching SEC documents

    Features:
    - Rate limiting (10 requests/second per SEC rules)
    - Caching (avoid re-fetching same documents)
    - Retries (handle transient errors)
    - User-Agent compliance (required by SEC)
    - Search filings by CIK and type
    - Fetch document content

    Usage:
        fetcher = SECFilingFetcher()

        # Search for 10-Q filings
        filings = fetcher.search_filings(cik="0001234567", filing_type="10-Q")

        # Fetch a specific document
        content = fetcher.fetch_document(filings[0]['url'])
    """

    def __init__(self):
        self.last_request_time = 0
        self.rate_limit_seconds = 0.11  # 10 req/sec = 0.1s + buffer
        self.headers = {
            'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com',
            'Accept-Encoding': 'gzip, deflate',
            'Host': 'www.sec.gov'
        }
        self.request_count = 0

    def _rate_limit(self):
        """
        Enforce 10 requests/second rate limit (SEC requirement)

        SEC EDGAR enforces rate limits:
        - 10 requests per second per IP
        - Exceeding this gets you temporarily blocked
        """
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self.last_request_time = time.time()

    def fetch_document(self, url: str, max_retries: int = 3) -> Optional[str]:
        """
        Fetch SEC document with rate limiting and retries

        Args:
            url: Full URL to SEC document
            max_retries: Number of retries on failure (default 3)

        Returns:
            Document text or None if fetch failed

        Example:
            >>> fetcher = SECFilingFetcher()
            >>> doc = fetcher.fetch_document("https://www.sec.gov/Archives/edgar/data/...")
            >>> if doc:
            >>>     print(f"Fetched {len(doc)} characters")
        """
        self._rate_limit()
        self.request_count += 1

        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=self.headers, timeout=30)

                if response.status_code == 200:
                    return response.text

                elif response.status_code == 429:  # Too Many Requests
                    wait_time = 5 * (attempt + 1)  # Exponential backoff
                    print(f"   ⚠️  Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                else:
                    print(f"   ⚠️  SEC fetch failed: HTTP {response.status_code}")
                    return None

            except requests.exceptions.Timeout:
                print(f"   ⚠️  Timeout (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                return None

            except Exception as e:
                print(f"   ⚠️  SEC fetch error: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                return None

        return None

    def search_filings(
        self,
        cik: str,
        filing_type: str,
        count: int = 10,
        date_before: Optional[str] = None
    ) -> List[Dict]:
        """
        Search for filings by CIK and type using RSS feed

        Args:
            cik: Company CIK (will be padded to 10 digits)
            filing_type: e.g., "8-K", "10-Q", "10-K", "DEF 14A"
            count: Number of results (default 10, max 100)
            date_before: Optional date filter YYYY-MM-DD (get filings before this date)

        Returns:
            List of filing metadata dicts with keys:
            - type: Filing type (e.g., "10-Q")
            - date: Filing date (datetime object)
            - url: URL to filing document
            - summary: Filing summary text
            - accession: Accession number

        Example:
            >>> fetcher = SECFilingFetcher()
            >>> filings = fetcher.search_filings(cik="0001234567", filing_type="10-Q")
            >>> print(f"Found {len(filings)} 10-Q filings")
            >>> print(f"Latest: {filings[0]['date']}")
        """
        cik_padded = cik.zfill(10)

        # Build search URL
        search_url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar"
            f"?action=getcompany&CIK={cik_padded}"
            f"&type={filing_type}&owner=exclude"
            f"&count={count}&output=atom"
        )

        if date_before:
            search_url += f"&dateb={date_before}"

        self._rate_limit()
        self.request_count += 1

        try:
            response = requests.get(search_url, headers=self.headers, timeout=30)

            if response.status_code != 200:
                print(f"   ⚠️  SEC search failed: HTTP {response.status_code}")
                return []

            feed = feedparser.parse(response.content)

            filings = []
            for entry in feed.entries:
                # Extract filing type from title
                filing_type_from_title = entry.title.split(' - ')[0] if ' - ' in entry.title else entry.title

                # Parse date - SEC RSS feeds use 'updated' not 'published'
                try:
                    if hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        filing_date = datetime(*entry.updated_parsed[:6])
                    elif hasattr(entry, 'published_parsed') and entry.published_parsed:
                        filing_date = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'updated'):
                        # Fallback: parse updated string
                        from dateutil import parser
                        filing_date = parser.parse(entry.updated)
                    else:
                        # Skip entries without date
                        continue
                except Exception as e:
                    print(f"   ⚠️  Date parsing error: {e}")
                    continue

                # Extract accession number from link
                # URL format: https://www.sec.gov/cgi-bin/viewer?action=view&cik=...&accession_number=0001193125-25-123456
                accession = None
                if 'accession_number=' in entry.link:
                    accession = entry.link.split('accession_number=')[1].split('&')[0]

                filings.append({
                    'type': filing_type_from_title,
                    'date': filing_date,
                    'url': entry.link,
                    'summary': entry.summary if hasattr(entry, 'summary') else '',
                    'accession': accession
                })

            return filings

        except Exception as e:
            print(f"   ⚠️  SEC search error: {e}")
            return []

    def get_latest_10q_or_10k(self, cik: str) -> Optional[Dict]:
        """
        Get the latest 10-Q or 10-K filing (whichever is most recent)

        Per user guidance: "make sure its 10-q or 10-k, depending on whichever one is the latest"

        Why check both?
        - Q1, Q2, Q3 filings: Companies file 10-Q (quarterly report)
        - Q4 filing: Companies file 10-K (annual report) instead of 10-Q
        - To get latest quarterly data, must check both types and use whichever is most recent

        Example timeline:
        - Nov 2024: 10-Q filed (Q3)
        - Feb 2025: 10-K filed (Q4/annual) ← Most recent!
        - May 2025: 10-Q filed (Q1) ← Most recent!
        - Aug 2025: 10-Q filed (Q2) ← Most recent!

        Args:
            cik: Company CIK

        Returns:
            Filing metadata dict with keys: type, date, url, summary, accession
            Returns the most recent quarterly (10-Q) or annual (10-K) report

        Example:
            >>> fetcher = SECFilingFetcher()
            >>> latest = fetcher.get_latest_10q_or_10k(cik="0001234567")
            >>> print(f"Latest report: {latest['type']} filed {latest['date']}")
        """
        # Get latest 10-Q
        filings_10q = self.search_filings(cik=cik, filing_type="10-Q", count=1)

        # Get latest 10-K
        filings_10k = self.search_filings(cik=cik, filing_type="10-K", count=1)

        # Return whichever is most recent
        candidates = []
        if filings_10q:
            candidates.append(filings_10q[0])
        if filings_10k:
            candidates.append(filings_10k[0])

        if not candidates:
            return None

        # Sort by date descending, return most recent
        candidates.sort(key=lambda f: f['date'], reverse=True)
        return candidates[0]

    def get_8ks_after_date(self, cik: str, after_date: datetime, count: int = 10) -> List[Dict]:
        """
        Get 8-K filings filed after a specific date

        Per user guidance: "for extension tracking, it should be the latest 10-q,
        except that if there are 8-ks or other filings since then, we can then see what those filing are"

        Args:
            cik: Company CIK
            after_date: Get 8-Ks filed after this date
            count: Number of 8-Ks to fetch (default 10)

        Returns:
            List of 8-K filing metadata dicts filed after the specified date

        Example:
            >>> fetcher = SECFilingFetcher()
            >>> latest_10q = fetcher.get_latest_10q_or_10k(cik="0001234567")
            >>> recent_8ks = fetcher.get_8ks_after_date(cik="0001234567", after_date=latest_10q['date'])
            >>> print(f"Found {len(recent_8ks)} 8-Ks filed after {latest_10q['date']}")
        """
        # Get recent 8-Ks
        all_8ks = self.search_filings(cik=cik, filing_type="8-K", count=count * 2)  # Get extra to filter

        # Filter for those after the date
        recent_8ks = [
            filing for filing in all_8ks
            if filing['date'] > after_date
        ]

        return recent_8ks[:count]

    def extract_document_url(self, filing_url: str, filing_type: Optional[str] = None) -> Optional[str]:
        """
        Extract the actual document URL from SEC filing index page

        SEC filing links often go to an index page. This extracts the actual HTML document URL.
        Handles both regular HTML and inline XBRL (iXBRL) formats.

        Args:
            filing_url: URL to SEC filing (may be index page)
            filing_type: Optional filing type (e.g., '10-Q', '8-K') to match specific document

        Returns:
            URL to actual HTML document, or None if extraction failed
        """
        # If it's already a direct document URL (not index), check if it's an inline XBRL viewer
        if '/Archives/edgar/data/' in filing_url and '.htm' in filing_url and 'index' not in filing_url:
            # Handle inline XBRL viewer format: /ix?doc=/Archives/edgar/...
            # The viewer is just JavaScript - we need to get the index page and find the actual document
            if '/ix?doc=' in filing_url or 'doc=' in filing_url:
                # Extract the document path from the viewer URL
                import urllib.parse
                parsed = urllib.parse.urlparse(filing_url)
                params = urllib.parse.parse_qs(parsed.query)
                if 'doc' in params:
                    doc_path = params['doc'][0]  # e.g., /Archives/edgar/data/2033991/000121390025076736/ea0254049-10q_txvenacq3.htm

                    # Build the index URL from the document path
                    # Path format: /Archives/edgar/data/CIK/ACCESSION/document.htm
                    # Index format: /Archives/edgar/data/CIK/ACCESSION/ACCESSION-index.htm
                    path_parts = doc_path.rsplit('/', 2)  # Split off last two parts
                    if len(path_parts) == 3:
                        base_path = path_parts[0]  # /Archives/edgar/data/CIK
                        accession_dir = path_parts[1]  # ACCESSION number

                        # Build index URL
                        index_url = f"https://www.sec.gov{base_path}/{accession_dir}/{accession_dir}-index.htm"

                        # Now fetch the index and find the primary document
                        # (Don't call extract_document_url again to avoid infinite recursion)
                        return self._extract_from_index(index_url, filing_type)

            # If not a viewer URL, validate and return
            if self._validate_url(filing_url):
                return filing_url

        # Fetch the index page
        content = self.fetch_document(filing_url)
        if not content:
            return None

        try:
            soup = BeautifulSoup(content, 'html.parser')

            # Strategy 1: Parse document table (most reliable)
            # HTML structure: <td>Seq</td><td>Description</td><td>Document</td><td>Type</td><td>Size</td>
            for row in soup.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) >= 4:
                    # Column 2: Document link
                    link_cell = cells[2]
                    link = link_cell.find('a', href=True)

                    if not link:
                        continue

                    href = link['href'].strip()

                    # Column 3: Document type
                    doc_type = cells[3].get_text().strip()

                    # Primary document criteria:
                    # 1. If filing_type specified, must match
                    # 2. Must be .htm/.html file
                    # 3. NOT an exhibit (no 'ex' prefix)
                    # 4. NOT an index page

                    is_html = href.endswith('.htm') or href.endswith('.html')
                    is_exhibit = href.lower().startswith('ex') or 'exhibit' in href.lower()
                    is_index = 'index' in href.lower()

                    # Check filing type match
                    type_matches = True
                    if filing_type:
                        # Normalize filing type (handle variations like '10-Q' vs '10-Q/A')
                        # IMPORTANT: Strip whitespace to avoid false negatives
                        filing_type_norm = filing_type.split('/')[0].strip()
                        doc_type_norm = doc_type.strip()
                        type_matches = doc_type_norm.startswith(filing_type_norm)

                    if is_html and not is_exhibit and not is_index and type_matches:
                        # Build full URL
                        if href.startswith('/'):
                            doc_url = 'https://www.sec.gov' + href
                        elif href.startswith('http'):
                            doc_url = href
                        else:
                            # Relative path - construct from index URL
                            base_url = filing_url.rsplit('/', 1)[0]
                            doc_url = f"{base_url}/{href}"

                        # Handle inline XBRL viewer format (/ix?doc=... or just doc=...)
                        # The viewer is JavaScript that loads the actual document
                        # We need to extract the direct document path
                        if '/ix?doc=' in doc_url or ('doc=' in doc_url and 'sec.gov' in doc_url):
                            import urllib.parse
                            parsed = urllib.parse.urlparse(doc_url)
                            params = urllib.parse.parse_qs(parsed.query)
                            if 'doc' in params:
                                doc_path = params['doc'][0]
                                # Build direct document URL (bypass JavaScript viewer)
                                doc_url = f"https://www.sec.gov{doc_path}"

                        # Validate URL before returning
                        if self._validate_url(doc_url):
                            return doc_url

            # Strategy 2: Fallback - Look for first .htm link (less reliable)
            tables = soup.find_all('table')
            if tables:
                first_table = tables[0]
                links = first_table.find_all('a', href=True)

                for link in links:
                    href = link['href']

                    # Skip non-document files
                    if any(ext in href.lower() for ext in ['.xml', '.xsd', '.json', '.zip', '.pdf']):
                        continue

                    # Skip index pages and exhibits
                    if 'index' in href.lower() or href.lower().startswith('ex'):
                        continue

                    # Must be HTML
                    if not (href.endswith('.htm') or href.endswith('.html')):
                        continue

                    # Build URL
                    if href.startswith('/'):
                        doc_url = f"https://www.sec.gov{href}"
                    elif href.startswith('http'):
                        doc_url = href
                    else:
                        base_url = filing_url.rsplit('/', 1)[0]
                        doc_url = f"{base_url}/{href}"

                    # Validate and return
                    if self._validate_url(doc_url):
                        return doc_url

            return None

        except Exception as e:
            print(f"   ⚠️  Document URL extraction error: {e}")
            return None

    def _extract_from_index(self, index_url: str, filing_type: Optional[str] = None) -> Optional[str]:
        """
        Extract primary document URL from index page (internal helper to avoid recursion)

        Args:
            index_url: URL to index page
            filing_type: Optional filing type to match

        Returns:
            URL to primary document or None
        """
        try:
            # Fetch index page
            content = self.fetch_document(index_url)
            if not content:
                return None

            soup = BeautifulSoup(content, 'html.parser')

            # Parse document table
            for row in soup.find_all('tr'):
                cells = row.find_all('td')
                if len(cells) >= 4:
                    link = cells[2].find('a', href=True)
                    if not link:
                        continue

                    href = link['href'].strip()
                    doc_type = cells[3].get_text().strip()

                    # Check criteria
                    is_html = href.endswith('.htm') or href.endswith('.html')
                    is_exhibit = href.lower().startswith('ex') or 'exhibit' in href.lower()
                    is_index = 'index' in href.lower()

                    type_matches = True
                    if filing_type:
                        type_matches = doc_type.startswith(filing_type.split('/')[0])

                    if is_html and not is_exhibit and not is_index and type_matches:
                        # Build full URL
                        if href.startswith('/'):
                            doc_url = f"https://www.sec.gov{href}"
                        elif href.startswith('http'):
                            doc_url = href
                        else:
                            base_url = index_url.rsplit('/', 1)[0]
                            doc_url = f"{base_url}/{href}"

                        # Handle inline XBRL viewer format (/ix?doc=...)
                        if '/ix?doc=' in doc_url or ('doc=' in doc_url and 'sec.gov' in doc_url):
                            import urllib.parse
                            parsed = urllib.parse.urlparse(doc_url)
                            params = urllib.parse.parse_qs(parsed.query)
                            if 'doc' in params:
                                doc_path = params['doc'][0]
                                # Build direct document URL (bypass JavaScript viewer)
                                doc_url = f"https://www.sec.gov{doc_path}"

                        return doc_url

            return None

        except Exception as e:
            print(f"   ⚠️  Error extracting from index: {e}")
            return None

    def _validate_url(self, url: str) -> bool:
        """
        Validate that a URL is accessible (returns 200 OK)

        Args:
            url: URL to validate

        Returns:
            True if URL is valid, False otherwise
        """
        try:
            # Use HEAD request for efficiency (doesn't download content)
            response = requests.head(url, headers=self.headers, timeout=5, allow_redirects=True)
            return response.status_code == 200
        except:
            # If HEAD fails, don't invalidate - some servers don't support HEAD
            return True

    def parse_document(self, doc_content: str) -> BeautifulSoup:
        """
        Parse SEC document with auto-detection of XML vs HTML format

        SEC documents come in two formats:
        1. HTML - Traditional 10-Q/10-K format
        2. iXBRL (inline XBRL) - XML-based format with financial data tags

        This method auto-detects the format and uses the correct parser.

        Args:
            doc_content: Raw document text

        Returns:
            BeautifulSoup object with properly parsed content
        """
        # Suppress XML parsing warnings (we're intentionally using the right parser)
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

        # Auto-detect format by checking for XML declaration or iXBRL namespaces
        is_xml = (
            doc_content.strip().startswith('<?xml') or
            'xmlns:ix=' in doc_content[:2000] or
            'xmlns:xbrli=' in doc_content[:2000] or
            '<ix:' in doc_content[:5000]
        )

        if is_xml:
            # Use XML parser for iXBRL documents
            try:
                # Try lxml XML parser first (fastest and most reliable)
                soup = BeautifulSoup(doc_content, features='xml')
            except:
                # Fallback to html.parser if lxml not available
                soup = BeautifulSoup(doc_content, 'html.parser')
        else:
            # Use HTML parser for traditional documents
            soup = BeautifulSoup(doc_content, 'html.parser')

        return soup

    def extract_text(self, doc_content: str) -> str:
        """
        Extract clean text from SEC document (HTML or iXBRL)

        Strips all HTML/XML tags and returns plain text suitable for:
        - Keyword searching
        - Pattern matching
        - AI analysis

        Args:
            doc_content: Raw document HTML/XML

        Returns:
            Clean plain text
        """
        soup = self.parse_document(doc_content)

        # Extract text and clean whitespace
        text = soup.get_text(separator=' ', strip=True)

        # Remove excessive whitespace
        import re
        text = re.sub(r'\s+', ' ', text)

        return text

    def extract_exhibits(self, filing_url: str) -> List[Dict]:
        """
        Extract exhibit links from SEC filing index page

        8-K filings often have key information in exhibits:
        - Exhibit 99.1: Press release (deal announcements, redemption results)
        - Exhibit 10.1: Business combination agreement (deal terms)
        - Exhibit 2.1: Merger agreement

        Args:
            filing_url: URL to SEC filing index page

        Returns:
            List of exhibit dicts with keys:
            - exhibit_number: e.g., "99.1", "10.1", "2.1"
            - description: Human-readable description
            - url: Full URL to exhibit document

        Example:
            >>> fetcher = SECFilingFetcher()
            >>> exhibits = fetcher.extract_exhibits("https://www.sec.gov/cgi-bin/viewer?...")
            >>> for ex in exhibits:
            >>>     print(f"{ex['exhibit_number']}: {ex['description']}")
        """
        # Fetch the index page
        content = self.fetch_document(filing_url)
        if not content:
            return []

        try:
            soup = BeautifulSoup(content, 'html.parser')
            exhibits = []

            # Strategy 1: Look for table with document listings
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) >= 4:
                        # Typical SEC index table format:
                        # Col 0: Sequence
                        # Col 1: Description
                        # Col 2: Document link
                        # Col 3: Type (e.g., "EX-99.1", "EX-10.1")
                        # Col 4: Size

                        doc_type = cols[3].text.strip() if len(cols) > 3 else ''
                        description = cols[1].text.strip() if len(cols) > 1 else ''

                        # Check if this is an exhibit
                        if doc_type.startswith('EX-'):
                            # Extract exhibit number (e.g., "EX-99.1" -> "99.1")
                            exhibit_num = doc_type.replace('EX-', '')

                            # Get document link
                            link_col = cols[2] if len(cols) > 2 else None
                            if link_col:
                                link = link_col.find('a')
                                if link and link.get('href'):
                                    href = link['href']
                                    if href.startswith('/'):
                                        exhibit_url = f"https://www.sec.gov{href}"
                                    else:
                                        exhibit_url = href

                                    exhibits.append({
                                        'exhibit_number': exhibit_num,
                                        'description': description,
                                        'url': exhibit_url
                                    })

            # Strategy 2: Fallback to looking for tableFile class (older format)
            if not exhibits:
                table = soup.find('table', {'class': 'tableFile'})
                if table:
                    for row in table.find_all('tr')[1:]:  # Skip header
                        cols = row.find_all('td')
                        if len(cols) >= 4:
                            doc_type = cols[3].text.strip()
                            if doc_type.startswith('EX-'):
                                exhibit_num = doc_type.replace('EX-', '')
                                description = cols[1].text.strip()

                                link = cols[2].find('a')
                                if link and link.get('href'):
                                    exhibit_url = f"https://www.sec.gov{link['href']}"
                                    exhibits.append({
                                        'exhibit_number': exhibit_num,
                                        'description': description,
                                        'url': exhibit_url
                                    })

            return exhibits

        except Exception as e:
            print(f"   ⚠️  Exhibit extraction error: {e}")
            return []

    def get_statistics(self) -> Dict:
        """
        Get statistics about SEC fetcher usage

        Returns:
            Dict with keys:
            - total_requests: Total number of requests made
            - requests_per_second: Average requests per second
        """
        return {
            'total_requests': self.request_count
        }


# Convenience functions for backward compatibility
def fetch_sec_document(url: str) -> Optional[str]:
    """Convenience function - fetch a single SEC document"""
    fetcher = SECFilingFetcher()
    return fetcher.fetch_document(url)


def search_sec_filings(cik: str, filing_type: str, count: int = 10) -> List[Dict]:
    """Convenience function - search SEC filings"""
    fetcher = SECFilingFetcher()
    return fetcher.search_filings(cik, filing_type, count)
