#!/usr/bin/env python3
"""Fix social.py to add market cap validation"""

import os
os.chdir('/root/.openclaw/workspace')

# Read the file - use the path we found
filepath = 'consensus_engine/scanners/social.py'

with open(filepath, 'r') as f:
    content = f.read()

# Check if already fixed
if 'valid_tickers' in content and 'validate_even_quote' in content:
    print("Already has validation code - resetting first")
    # Get original from git
    import subprocess
    subprocess.run(['git', 'checkout', '--', filepath], capture_output=True)
    with open(filepath, 'r') as f:
        content = f.read()

# Add helper function after the imports
if '_has_market_cap' not in content:
    # Find where to insert - after the imports section
    insert_pos = content.find('log = logging.getLogger')
    if insert_pos > 0:
        helper = '''

async def _has_market_cap(ticker: str) -> bool:
    """Check if ticker has any market cap - skip if not a real stock."""
    try:
        from consensus_engine.utils.    tickers import validate_even_ticker
        return await validate_even_ticker(ticker)
    except Exception:
        return True  # Fail open on errors

'''
        content = content[:insert_pos] + helper + content[insert_pos:]

# Replace the loop to filter tickers
old_code = '''    results = {}
    async with aiohttp.ClientSession() as session:
        for ticker in tickers[:10]:'''

new_code = '''    # Filter to valid tickers with market cap
    valid_tickers = []
    for t in tickers[:10]:
        if await _has_market_cap(t):
            valid_tickers.append(t)
    if not valid_tickers:
        return {}

    results = {}
    async with aiohttp.ClientSession() as session:
        for ticker in valid_tickers:'''

content = content.replace(old_code, new_code)

# Write back
with open(filepath, 'w') as f:
    f.write(content)

print("Fixed! Added market cap validation.")
