import re
with open('c:\\vibe coding\\國家寶藏\\index.html', 'r', encoding='utf8') as f:
    html = f.read()

# Update buildPortfolioCard signature and add concentration warning
old_build_port = r'function buildPortfolioCard\(s\) \{'
new_build_port = r'function buildPortfolioCard(s, concentrationWarning="") {'
html = re.sub(old_build_port, new_build_port, html)

old_port_header = r'''        <div class="card-name" style="display:flex;align-items:center;gap:8px;">
           \$\{s.name\}
           <span style="font-size:11px; padding:2px 6px; background:rgba\(255,255,255,0\.1\); border-radius:12px; color:var\(--color-cyan\);">體檢: \$\{s.score \|\| '--'\} 分</span>
        </div>'''
new_port_header = r'''        <div class="card-name" style="display:flex;align-items:center;gap:8px;">
           ${s.name}
           <span style="font-size:11px; padding:2px 6px; background:rgba(255,255,255,0.1); border-radius:12px; color:var(--color-cyan);">體檢: ${s.score || '--'} 分</span>
           ${concentrationWarning}
        </div>'''
html = re.sub(old_port_header, new_port_header, html)

# Update pnl logic in buildPortfolioCard to show value
old_pnl = r'''  let pnlStr = '--';
  if \(s.pnl_percent !== null && s.pnl_percent !== undefined\) \{
    const color = s.pnl_percent >= 0 \? 'var\(--color-red\)' : 'var\(--color-green\)';
    pnlStr = `<span style="color:\$\{color\};font-weight:bold;">\$\{s.pnl_percent\}%</span>`;
  \}'''
new_pnl = r'''  let pnlStr = '--';
  if (s.pnl_percent !== null && s.pnl_percent !== undefined) {
    const color = s.pnl_percent >= 0 ? 'var(--color-red)' : 'var(--color-green)';
    let valStr = (s.pnl_value !== null && s.pnl_value !== undefined) ? ` / $${Math.round(s.pnl_value).toLocaleString()}` : '';
    pnlStr = `<span style="color:${color};font-weight:bold;">${s.pnl_percent}%${valStr}</span>`;
  }'''
html = re.sub(old_pnl, new_pnl, html)

# Update edit modal UI
old_modal = r'''  <div id="edit-modal" style="display:none; position:fixed; top:50%; left:50%; transform:translate\(-50%, -50%\); background:var\(--bg-card\); padding:20px; border-radius:8px; border:1px solid rgba\(255,255,255,0\.1\); z-index:100; min-width:300px;">
    <h3>編輯成本價 - <span id="edit-code"></span></h3>
    <input type="number" id="edit-cost" placeholder="請輸入成本價 \(留空代表不計算損益\)" style="width:100%; margin:10px 0; padding:8px; background:var\(--bg-body\); border:1px solid rgba\(255,255,255,0\.2\); color:#fff; border-radius:4px;">
    <div style="display:flex; justify-content:flex-end; gap:8px;">
      <button onclick="closeEditModal\(\)" style="padding:6px 12px; background:transparent; border:1px solid rgba\(255,255,255,0\.3\); color:#fff; border-radius:4px; cursor:pointer;">取消</button>
      <button onclick="savePortfolioConfig\(\)" style="padding:6px 12px; background:var\(--color-blue\); border:none; color:#fff; border-radius:4px; cursor:pointer;">儲存</button>
    </div>
  </div>'''

new_modal = r'''  <div id="edit-modal" style="display:none; position:fixed; top:50%; left:50%; transform:translate(-50%, -50%); background:var(--bg-card); padding:20px; border-radius:8px; border:1px solid rgba(255,255,255,0.1); z-index:100; min-width:300px;">
    <h3 style="margin-top:0;">編輯庫存 - <span id="edit-code"></span></h3>
    <label style="font-size:12px; color:var(--text-muted);">成本價 (均價)</label>
    <input type="number" id="edit-cost" placeholder="留空代表不計算損益" style="width:100%; margin:4px 0 12px 0; padding:8px; background:var(--bg-body); border:1px solid rgba(255,255,255,0.2); color:#fff; border-radius:4px;">
    
    <label style="font-size:12px; color:var(--text-muted);">持有股數 (1張 = 1000股)</label>
    <input type="number" id="edit-shares" placeholder="留空代表不計算台幣損益" style="width:100%; margin:4px 0 12px 0; padding:8px; background:var(--bg-body); border:1px solid rgba(255,255,255,0.2); color:#fff; border-radius:4px;">
    
    <div style="display:flex; justify-content:flex-end; gap:8px; margin-top:8px;">
      <button onclick="closeEditModal()" style="padding:6px 12px; background:transparent; border:1px solid rgba(255,255,255,0.3); color:#fff; border-radius:4px; cursor:pointer;">取消</button>
      <button onclick="savePortfolioConfig()" style="padding:6px 12px; background:var(--color-blue); border:none; color:#fff; border-radius:4px; cursor:pointer;">儲存</button>
    </div>
  </div>'''
html = re.sub(old_modal, new_modal, html)

old_edit_fn = r'''function editCostPrice\(code, name, cost\) \{
  document\.getElementById\('edit-code'\)\.innerText = `\$\{code\} \$\{name\}`;
  document\.getElementById\('edit-cost'\)\.value = cost !== null \? cost : '';
  document\.getElementById\('edit-modal'\)\.style\.display = 'block';
  document\.getElementById\('modal-overlay'\)\.style\.display = 'block';
\}'''
new_edit_fn = r'''function editCostPrice(code, name, cost, shares) {
  document.getElementById('edit-code').innerText = `${code} ${name}`;
  document.getElementById('edit-cost').value = cost !== null ? cost : '';
  document.getElementById('edit-shares').value = shares !== null ? shares : '';
  document.getElementById('edit-modal').style.display = 'block';
  document.getElementById('modal-overlay').style.display = 'block';
}'''
html = re.sub(old_edit_fn, new_edit_fn, html)

with open('c:\\vibe coding\\國家寶藏\\index.html', 'w', encoding='utf8') as f:
    f.write(html)
