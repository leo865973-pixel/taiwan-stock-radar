"""
Fix ALL git conflict markers in dashboard_data.json.
For each conflict, we keep the THEIRS section (below =======).
"""
import re

with open('dashboard_data.json', 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern to match git conflict blocks:  <<<<<<< ... ======= ... >>>>>>>
# Keep the THEIRS part (after =======)
pattern = re.compile(
    r'<<<<<<< [^\n]*\n'   # <<<<<< HEAD line
    r'.*?'                 # HEAD content
    r'=======\n'           # separator
    r'(.*?)'               # THEIRS content (captured)
    r'>>>>>>> [^\n]*\n',   # >>>>>>> line
    re.DOTALL
)

count = len(pattern.findall(content))
fixed = pattern.sub(r'\1', content)

with open('dashboard_data.json', 'w', encoding='utf-8') as f:
    f.write(fixed)

print(f"Fixed {count} conflict blocks")

# Verify JSON is valid
import json
try:
    with open('dashboard_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    print("JSON valid! updated_at:", data.get('updated_at'))
    print("portfolio count:", len(data.get('portfolio', [])))
    print("market_scanned count:", len(data.get('market_scanned', [])))
    if data.get('portfolio'):
        print("First portfolio keys:", list(data['portfolio'][0].keys()))
except Exception as e:
    print("JSON error:", e)
    # Find the error location
    with open('dashboard_data.json', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    for i in range(min(30, len(lines))):
        if '<<<<' in lines[i] or '>>>>' in lines[i] or '======' in lines[i]:
            print(f"Conflict marker at line {i}: {repr(lines[i][:80])}")
