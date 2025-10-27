#!/usr/bin/env python3
"""
Universal SEC Filing Text Extractor

Extracts clean text from SEC EDGAR filings (8-K, S-1, S-4, DEF 14A, etc.)
Handles both HTML and iXBRL formats

Usage:
    from sec_text_extractor import extract_filing_text
    text = extract_filing_text(filing_url)
"""

import requests
from bs4 import BeautifulSoup
import re
from typing import Optional

def extract_filing_text(filing_url: str, max_chars: int = 100000) -> Optional[str]:
    """
    Extract clean text from an SEC filing
    
    Args:
        filing_url: Full URL to SEC filing (e.g., https://www.sec.gov/Archives/edgar/data/...)
        max_chars: Maximum characters to return (default 100k)
    
    Returns:
        Clean text string or None if extraction fails
    """
    try:
        response = requests.get(
            filing_url,
            headers={'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'},
            timeout=30
        )
        
        if response.status_code != 200:
            return None
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style", "meta", "link"]):
            script.decompose()
        
        # Get text
        text = soup.get_text()
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        # Return truncated text
        return text[:max_chars] if max_chars else text
        
    except Exception as e:
        print(f"⚠️  Error extracting text from {filing_url}: {e}")
        return None


def extract_txt_file(accession_number: str, cik: str) -> Optional[str]:
    """
    Extract from .txt version of filing (plain text format)
    
    Args:
        accession_number: SEC accession number (e.g., 0001193125-25-223444)
        cik: Company CIK number
    
    Returns:
        Plain text content
    """
    # Convert accession number to filename format
    txt_filename = accession_number.replace('-', '') + '.txt'
    
    # Build URL: https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{filename}.txt
    cik_clean = cik.lstrip('0')
    accession_clean = accession_number.replace('-', '')
    
    txt_url = f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{accession_clean}/{txt_filename}"
    
    try:
        response = requests.get(
            txt_url,
            headers={'User-Agent': 'LEVP SPAC Platform fenil@legacyevp.com'},
            timeout=30
        )
        
        if response.status_code == 200:
            return response.text
        return None
        
    except Exception as e:
        print(f"⚠️  Error fetching .txt file: {e}")
        return None


def search_filing_for_patterns(filing_text: str, patterns: dict) -> dict:
    """
    Search filing text for specific patterns
    
    Args:
        filing_text: Full filing text
        patterns: Dict of {name: regex_pattern}
    
    Returns:
        Dict of {name: [matches]}
    """
    results = {}
    
    for name, pattern in patterns.items():
        matches = re.findall(pattern, filing_text, re.IGNORECASE | re.DOTALL)
        if matches:
            results[name] = matches
    
    return results


if __name__ == "__main__":
    # Test on AEXA 8-K
    test_url = "https://www.sec.gov/Archives/edgar/data/2079173/000119312525223444/d82578d8k.htm"
    
    print("Testing SEC text extractor...")
    text = extract_filing_text(test_url, max_chars=50000)
    
    if text:
        print(f"✓ Extracted {len(text)} characters")
        
        # Search for key information
        patterns = {
            'overallotment': r'over.?allotment.{0,200}',
            'sponsor_shares': r'(175,?000|sponsor).{0,200}(class A|shares)',
            'trust_cash': r'trust.{0,100}(cash|deposited|account).{0,200}'
        }
        
        results = search_filing_for_patterns(text, patterns)
        
        for name, matches in results.items():
            print(f"\n{name.upper()}:")
            for match in matches[:2]:
                clean = ' '.join(str(match).split())[:200]
                print(f"  {clean}")
    else:
        print("✗ Extraction failed")

