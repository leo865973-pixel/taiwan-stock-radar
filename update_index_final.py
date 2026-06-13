import re

with open('c:\\vibe coding\\國家寶藏\\index.html', 'r', encoding='utf8') as f:
    html = f.read()

# 1. Add portfolio summary to section header
old_port_header = r'<span class="section-meta" id="portfolio-count"></span>'
new_port_header = r'''<span class="section-meta" id="portfolio-count"></span>
        <div id="portfolio-summary" style="margin-left: 10px; font-size:12px; color:var(--text-muted);"></div>'''
html = re.sub(old_port_header, new_port_header, html)

# 2. Update renderPortfolio to calculate totals and concentration
old_render_port = r'''function renderPortfolio\(portfolio\) \{\n\s*const grid = document\.getElementById\('portfolio-grid'\);\n\s*document\.getElementById\('portfolio-count'\)\.textContent = `共 \$\{portfolio\.length\} 檔`;\n\n\s*if \(!portfolio\.length\) \{\n\s*grid\.innerHTML = '<div class="empty-state">庫存資料為空</div>';\n\s*return;\n\s*\}\n\n\s*grid\.innerHTML = portfolio\.map\(s => buildPortfolioCard\(s\)\)\.join\(''\);\n\}'''
new_render_port = r'''function renderPortfolio(portfolio) {
  const grid = document.getElementById('portfolio-grid');
  document.getElementById('portfolio-count').textContent = `共 ${portfolio.length} 檔`;
  const summaryEl = document.getElementById('portfolio-summary');

  if (!portfolio.length) {
    grid.innerHTML = '<div class="empty-state">庫存資料為空</div>';
    if(summaryEl) summaryEl.innerHTML = '';
    return;
  }

  let totalValue = 0;
  let totalCost = 0;
  let hasShares = false;

  portfolio.forEach(s => {
    if (s.shares && s.price && s.cost_price) {
      hasShares = true;
      totalValue += s.price * s.shares;
      totalCost += s.cost_price * s.shares;
    }
  });

  if(summaryEl) {
    if (hasShares) {
      const totalPnl = totalValue - totalCost;
      const pnlColor = totalPnl >= 0 ? 'var(--color-red)' : 'var(--color-green)';
      summaryEl.innerHTML = `總市值: <b style="color:white;">NT$ ${Math.round(totalValue).toLocaleString()}</b> | 總損益: <b style="color:${pnlColor};">NT$ ${Math.round(totalPnl).toLocaleString()}</b>`;
    } else {
      summaryEl.innerHTML = '';
    }
  }

  grid.innerHTML = portfolio.map(s => {
    let concentrationWarning = '';
    if (hasShares && s.shares && s.price && totalValue > 0) {
      const weight = (s.price * s.shares) / totalValue;
      if (weight > 0.3) {
        concentrationWarning = `<span style="font-size:11px; padding:2px 6px; background:rgba(255,0,0,0.2); border-radius:12px; color:#ff4444; border:1px solid #ff4444; margin-left:8px;">⚠️ 佔比 ${(weight*100).toFixed(0)}% 過高</span>`;
      }
    }
    return buildPortfolioCard(s, concentrationWarning);
  }).join('');
}'''
html = re.sub(old_render_port, new_render_port, html)

# 3. Update buildPortfolioCard
# This was already updated by my previous regex, but let's make sure!
if 'function buildPortfolioCard(s, concentrationWarning="")' not in html:
    html = re.sub(r'function buildPortfolioCard\(s\) \{', r'function buildPortfolioCard(s, concentrationWarning="") {', html)
    
if '${concentrationWarning}' not in html:
    html = re.sub(r'(\$\{s\.name\}\s*<span[^>]*>.*?</span>)', r'\1\n           ${concentrationWarning}', html)

if 's.pnl_value' not in html:
    old_pnl = r'''  let pnlStr = '--';
  if \(s.pnl_percent !== null && s.pnl_percent !== undefined\) \{
    const color = s.pnl_percent >= 0 \? 'var\(--color-red\)' : 'var\(--color-green\)';
    pnlStr = `<span style="color:\$\{color\};font-weight:bold;">\$\{s.pnl_percent\}%</span>`;
  \}'''
    new_pnl = r'''  let pnlStr = '--';
  if (s.pnl_percent !== null && s.pnl_percent !== undefined) {
    const color = s.pnl_percent >= 0 ? 'var(--color-red)' : 'var(--color-green)';
    let valStr = (s.pnl_value !== null && s.pnl_value !== undefined) ? ` / NT$ ${Math.round(s.pnl_value).toLocaleString()}` : '';
    pnlStr = `<span style="color:${color};font-weight:bold;">${s.pnl_percent}%${valStr}</span>`;
  }'''
    html = re.sub(old_pnl, new_pnl, html)

# Update PM Add Form UI
old_pm_inputs = r'''<input class="pm-input" id="pm-cost"      placeholder="買入成本（選填）" type="number" step="0.01" />'''
new_pm_inputs = r'''<input class="pm-input" id="pm-cost"      placeholder="買入成本（選填）" type="number" step="0.01" />
        <input class="pm-input" id="pm-shares"    placeholder="持有股數 (1張=1000股)" type="number" />'''
html = re.sub(old_pm_inputs, new_pm_inputs, html)

# Update renderPmList
old_pm_row = r'''<span class="pm-stock-cost" id="pm-cost-display-\$\{i\}">\$\{s\.cost_price != null \? '成本 '\+s\.cost_price : '未設成本'\}</span>\n\s*<input type="number" step="0\.01" id="pm-cost-edit-\$\{i\}" value="\$\{s\.cost_price \|\| ''\}" style="display:none; width: 60px; font-size: 11px; padding: 2px; background: rgba\(255,255,255,0\.1\); border: 1px solid var\(--color-cyan\); color: white; border-radius: 4px; outline: none; margin-left: auto;">'''

new_pm_row = r'''<span class="pm-stock-cost" id="pm-cost-display-${i}" style="width: auto;">${s.cost_price != null ? '成本 '+s.cost_price : '未設成本'} ${s.shares != null ? '('+s.shares+'股)' : ''}</span>
    
    <input type="number" step="0.01" id="pm-cost-edit-${i}" value="${s.cost_price || ''}" placeholder="成本價" style="display:none; width: 60px; font-size: 11px; padding: 2px; background: rgba(255,255,255,0.1); border: 1px solid var(--color-cyan); color: white; border-radius: 4px; outline: none; margin-left: auto;">
    <input type="number" id="pm-shares-edit-${i}" value="${s.shares || ''}" placeholder="股數" style="display:none; width: 60px; font-size: 11px; padding: 2px; background: rgba(255,255,255,0.1); border: 1px solid var(--color-cyan); color: white; border-radius: 4px; outline: none; margin-left: 4px;">'''
html = re.sub(old_pm_row, new_pm_row, html)

# Update pmEditStock
old_pm_edit = r'''document\.getElementById\(`pm-cost-edit-\$\{index\}`\)\.style\.display = 'inline-block';'''
new_pm_edit = r'''document.getElementById(`pm-cost-edit-${index}`).style.display = 'inline-block';
    document.getElementById(`pm-shares-edit-${index}`).style.display = 'inline-block';'''
html = re.sub(old_pm_edit, new_pm_edit, html)

# Update pmSaveEditStock
old_pm_save_edit = r'''const newCost = parseFloat\(document\.getElementById\(`pm-cost-edit-\$\{index\}`\)\.value\);\n\s*list\[index\]\.cost_price = isNaN\(newCost\) \? null : newCost;'''
new_pm_save_edit = r'''const newCost = parseFloat(document.getElementById(`pm-cost-edit-${index}`).value);
    const newShares = parseInt(document.getElementById(`pm-shares-edit-${index}`).value, 10);
    
    list[index].cost_price = isNaN(newCost) ? null : newCost;
    list[index].shares = isNaN(newShares) ? null : newShares;'''
html = re.sub(old_pm_save_edit, new_pm_save_edit, html)

# Update pmAddStock
old_pm_add = r'''const cost = parseFloat\(document\.getElementById\('pm-cost'\)\.value\) \|\| null;\n\s*const isEtf = document\.getElementById\('pm-is-etf'\)\.checked;\n\s*if \(!code \|\| !name\) \{ alert\('請填寫股票代號和名稱！'\); return; \}\n\s*const list = getUserPortfolioConfig\(\);\n\s*if \(list\.find\(s => s\.code === code\)\) \{ alert\(code \+ ' 已在庫存中！'\); return; \}\n\s*list\.push\(\{ code, name, is_etf: isEtf, cost_price: cost \}\);'''

new_pm_add = r'''const cost = parseFloat(document.getElementById('pm-cost').value) || null;
  const shares = parseInt(document.getElementById('pm-shares').value, 10) || null;
  const isEtf = document.getElementById('pm-is-etf').checked;
  if (!code || !name) { alert('請填寫股票代號和名稱！'); return; }
  const list = getUserPortfolioConfig();
  if (list.find(s => s.code === code)) { alert(code + ' 已在庫存中！'); return; }
  list.push({ code, name, is_etf: isEtf, cost_price: cost, shares: shares });'''
html = re.sub(old_pm_add, new_pm_add, html)

old_pm_add_clear = r'''\['pm-code','pm-name','pm-cost'\]\.forEach'''
new_pm_add_clear = r'''['pm-code','pm-name','pm-cost','pm-shares'].forEach'''
html = re.sub(old_pm_add_clear, new_pm_add_clear, html)

# Update pmSaveAndClose
old_pm_save_close = r'''return s \? \{ \.\.\.s, cost_price: cfg\.cost_price \}'''
new_pm_save_close = r'''return s ? { ...s, cost_price: cfg.cost_price, shares: cfg.shares }'''
html = re.sub(old_pm_save_close, new_pm_save_close, html)

# Save
with open('c:\\vibe coding\\國家寶藏\\index.html', 'w', encoding='utf8') as f:
    f.write(html)
