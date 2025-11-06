#!/usr/bin/env python3
import asyncio
import sys
sys.path.append('/home/ubuntu/spac-research')

from database import SessionLocal, SPAC
from agents.pipe_extractor_agent import PIPEExtractorAgent
from utils.sec_filing_fetcher import SECFilingFetcher
from datetime import timedelta

async def test_chac():
    db = SessionLocal()
    spac = db.query(SPAC).filter(SPAC.ticker == 'CHAC').first()
    db.close()

    print(f'Testing CHAC - {spac.target}')
    print(f'Database shows: pipe_size=$275M')
    print()

    fetcher = SECFilingFetcher()
    after_date = spac.announced_date - timedelta(days=7)
    filings = fetcher.get_8ks_after_date(cik=spac.cik, after_date=after_date, count=5)

    if filings:
        extractor = PIPEExtractorAgent()
        result = await extractor.process_filing(filings[0], 'CHAC')

        if result and result.get('pipe_data'):
            pipe = result['pipe_data']
            print(f'\n✅ EXTRACTED PIPE DATA:')
            print(f'   Total PIPE: ${pipe.get("pipe_size")}M')
            print(f'   Price: ${pipe.get("pipe_price")}')
            print(f'   Percentage: {pipe.get("pipe_percentage")}%')
            print(f'   Investors: {pipe.get("pipe_investors")}')
            print(f'   Confidence: {pipe.get("confidence")}%')

        extractor.close()

asyncio.run(test_chac())
