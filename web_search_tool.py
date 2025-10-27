#!/usr/bin/env python3
"""
Web Search Tool
Wrapper around available web search APIs

Priority:
1. Claude Code WebSearch (if available)
2. Google Custom Search API (if configured)
3. Return empty results

This allows web_research_agent.py to work in any environment
"""

import os
import subprocess
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def web_search(query: str, max_results: int = 10) -> str:
    """
    Execute web search and return formatted results

    Args:
        query: Search query string
        max_results: Maximum number of results to return

    Returns:
        Formatted string with search results (title, URL, snippet)
    """

    # Method 1: Google Custom Search API (preferred)
    try:
        result = _google_custom_search(query, max_results)
        if result:
            return result
    except Exception as e:
        print(f"Google Search error: {e}")

    # Method 2: Try Claude Code WebSearch (subprocess call)
    # NOTE: This will only work when running inside Claude Code environment
    try:
        result = _claude_code_web_search(query, max_results)
        if result:
            return result
    except Exception as e:
        pass

    # Method 3: No search available
    return "Web search not available in this environment"


def _claude_code_web_search(query: str, max_results: int) -> str:
    """
    Use Claude Code's WebSearch tool via subprocess

    NOTE: This is a placeholder - actual implementation depends on
    how Claude Code exposes WebSearch programmatically
    """
    # For now, return empty - this would need Claude Code API integration
    return None


def _google_custom_search(query: str, max_results: int) -> str:
    """
    Use Google Custom Search API (requires API key)
    """
    api_key = os.getenv('GOOGLE_SEARCH_API_KEY')
    search_engine_id = os.getenv('GOOGLE_SEARCH_ENGINE_ID')

    if not api_key or not search_engine_id:
        return None

    import requests

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': api_key,
        'cx': search_engine_id,
        'q': query,
        'num': min(max_results, 10)
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get('items', []):
            results.append(f"""
Title: {item.get('title', 'N/A')}
URL: {item.get('link', 'N/A')}
Snippet: {item.get('snippet', 'N/A')}
""")

        return "\n".join(results)

    except Exception as e:
        print(f"Google Search error: {e}")
        return None


# For manual testing
if __name__ == "__main__":
    test_query = "VACH SPAC VERAXA Biotech deal 2025"
    result = web_search(test_query)
    print(result)
