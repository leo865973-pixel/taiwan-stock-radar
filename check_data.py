import json
with open('dashboard_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print('=== PORTFOLIO (list) ===')
portfolio = data.get('portfolio', [])
for h in portfolio:
    print(f"  ticker={h.get('ticker')}, name={h.get('name')}, ai_summary={str(h.get('ai_summary',''))[:100]}")
    print(f"    keys: {list(h.keys())}")

print('\n=== MARKET_SCANNED sample ===')
scanned = data.get('market_scanned', [])
if scanned:
    s = scanned[0]
    print(f"  keys: {list(s.keys())}")
    print(f"  ticker={s.get('ticker')}, name={s.get('name')}")
    print(f"  type={s.get('type','N/A')}")

print('\n=== run_summary ===')
print(data.get('run_summary'))
