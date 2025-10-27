"""Shared utilities for SPAC monitoring system"""

from .sec_filing_fetcher import SECFilingFetcher, fetch_sec_document, search_sec_filings

__all__ = ['SECFilingFetcher', 'fetch_sec_document', 'search_sec_filings']
