#!/usr/bin/env python3
"""Extract tickers with no PIPE from test results"""

import re

with open('/tmp/pipe_test_results.txt', 'r') as f:
    content = f.read()

# Find all test blocks
test_blocks = re.split(r'={80}\nTest \d+/\d+:', content)[1:]

no_pipe_tickers = []

for block in test_blocks:
    # Extract ticker and target
    ticker_match = re.search(r'^([A-Z]+) → (.+?)$', block, re.MULTILINE)
    if not ticker_match:
        continue

    ticker = ticker_match.group(1)
    target = ticker_match.group(2)

    # Check if PIPE was found
    has_pipe_extraction = '✅ PIPE DATA EXTRACTED:' in block
    no_pipe_found = '   ℹ️  No PIPE data found' in block

    if no_pipe_found and not has_pipe_extraction:
        no_pipe_tickers.append((ticker, target))

print("SPACs with NO PIPE found (13 total):")
print("=" * 80)
for ticker, target in no_pipe_tickers:
    print(f"{ticker:6s} → {target}")
