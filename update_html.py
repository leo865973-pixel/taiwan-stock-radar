import re
with open('c:\\vibe coding\\國家寶藏\\index.html', 'r', encoding='utf8') as f:
    html = f.read()

html = re.sub(
    r'(<div class="card-actions">\s*<button.*?editCostPrice.*?<button.*?openAiDiagnosis.*?</div>\s*</div>)',
    r'''<div style="margin-top:12px; padding:8px; background:rgba(255,255,255,0.05); border-radius:6px; font-size:12px; color:var(--text-muted); border-left:3px solid var(--color-cyan);">
      <span style="font-weight:bold; color:#fff;">📝 小白解讀：</span> ${s.advice || '暫無解讀'}
    </div>
    \1''',
    html,
    flags=re.DOTALL
)

html = re.sub(
    r'(<div class="card-actions">\s*<button.*?copyRawData.*?<button.*?openAiDiagnosis.*?</div>\s*</div>)',
    r'''<div style="margin-top:12px; padding:8px; background:rgba(255,255,255,0.05); border-radius:6px; font-size:12px; color:var(--text-muted); border-left:3px solid var(--color-cyan);">
      <span style="font-weight:bold; color:#fff;">📝 小白解讀：</span> ${s.advice || '暫無解讀'}
    </div>
    \1''',
    html,
    flags=re.DOTALL
)

with open('c:\\vibe coding\\國家寶藏\\index.html', 'w', encoding='utf8') as f:
    f.write(html)
