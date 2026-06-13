import re

with open('index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

keywords = ['ai_summary', 'ticker', 'is_etf', 'ETF', 'small_summary', 'advice', 'light', 'score']
for i, line in enumerate(lines):
    for kw in keywords:
        if kw in line:
            print(f'{i+1}: {line.rstrip()[:150]}')
            break
