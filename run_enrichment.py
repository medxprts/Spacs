#!/usr/bin/env python3
"""Run SEC enrichment for all SPACs"""

from sec_data_scraper import SPACDataEnricher

if __name__ == "__main__":
    enricher = SPACDataEnricher()
    try:
        enricher.enrich_all(limit=None)
    finally:
        enricher.close()
