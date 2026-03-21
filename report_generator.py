import csv
import json
import logging
import os
from collections import Counter
from typing import List

from categorizer import CategoryResult
from config import Config, FilterConfig

log = logging.getLogger(__name__)

CHART_COLORS = [
    "#6366f1", "#22c55e", "#ef4444", "#f59e0b",
    "#8b5cf6", "#14b8a6", "#f97316", "#64748b",
    "#ec4899", "#06b6d4", "#84cc16", "#e11d48",
]


def _apply_filters(results: List[CategoryResult], filters: FilterConfig) -> List[CategoryResult]:
    filtered = results

    if filters.include_categories:
        filtered = [r for r in filtered if r.category in filters.include_categories]

    if filters.exclude_categories:
        filtered = [r for r in filtered if r.category not in filters.exclude_categories]

    if filters.only_worth_checking:
        filtered = [r for r in filtered if r.worth_checking]

    if filters.require_tags:
        lower_required = {t.lower() for t in filters.require_tags}
        filtered = [
            r for r in filtered
            if any(t.lower() in lower_required for t in r.tags)
        ]

    if len(filtered) < len(results):
        log.info("Filters reduced results from %d to %d users.", len(results), len(filtered))

    return filtered


class ReportGenerator:
    def __init__(self, config: Config):
        self.config = config
        os.makedirs(config.output_dir, exist_ok=True)

    def generate(self, results: List[CategoryResult]) -> None:
        filtered = _apply_filters(results, self.config.filters)
        self._save_csv(filtered)
        self._save_json(filtered)
        self._save_html(filtered)
        self._print_summary(filtered)

    def _save_csv(self, results: List[CategoryResult]) -> None:
        path = os.path.join(self.config.output_dir, "categorized_users.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "User ID", "Username", "First Name", "Last Name",
                "Display Name", "Category", "Worth Checking",
                "Tags", "Summary", "Reasoning",
                "Age", "City", "Country", "Profession",
                "Experience Years", "Languages", "Links", "Contact Info",
                "Message Count", "Sample Messages (first 3)",
            ])
            for r in results:
                md = r.user_metadata
                writer.writerow([
                    r.user_id,
                    r.username,
                    r.first_name,
                    r.last_name,
                    r.display_name,
                    r.category,
                    "Yes" if r.worth_checking else "No",
                    ", ".join(r.tags),
                    r.summary,
                    r.reasoning,
                    md.age or "",
                    md.city or "",
                    md.country or "",
                    md.profession or "",
                    md.experience_years or "",
                    ", ".join(md.languages) if md.languages else "",
                    ", ".join(md.links) if md.links else "",
                    md.contact_info or "",
                    len(r.messages),
                    " | ".join(r.messages[:3]),
                ])
        log.info("CSV  → %s", path)

    def _save_json(self, results: List[CategoryResult]) -> None:
        path = os.path.join(self.config.output_dir, "categorized_users.json")
        data = [
            {
                "user_id": r.user_id,
                "username": r.username,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "display_name": r.display_name,
                "category": r.category,
                "worth_checking": r.worth_checking,
                "tags": r.tags,
                "summary": r.summary,
                "reasoning": r.reasoning,
                "user_metadata": r.user_metadata.to_dict(),
                "message_count": len(r.messages),
                "messages": r.messages,
            }
            for r in results
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        log.info("JSON → %s", path)

    def _save_html(self, results: List[CategoryResult]) -> None:
        users_json = json.dumps([
            {
                "user_id": r.user_id,
                "display_name": r.display_name,
                "username": r.username,
                "category": r.category,
                "worth_checking": r.worth_checking,
                "tags": r.tags,
                "summary": r.summary,
                "reasoning": r.reasoning,
                "message_count": len(r.messages),
                "messages": r.messages[:5],
                "user_metadata": r.user_metadata.to_dict(),
            }
            for r in results
        ], ensure_ascii=False)

        category_counts = Counter(r.category for r in results)
        total_users = len(results)
        total_msgs = sum(len(r.messages) for r in results)
        total_wc = sum(1 for r in results if r.worth_checking)
        categories_list = sorted(category_counts.keys())

        # Collect all unique tags for the tag filter
        all_tags = sorted({t for r in results for t in r.tags})

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Telegram Channel Analysis</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #f1f5f9;
      --surface: #ffffff;
      --surface-hover: #f8fafc;
      --border: #e2e8f0;
      --text: #0f172a;
      --text-secondary: #475569;
      --text-muted: #94a3b8;
      --primary: #6366f1;
      --primary-light: #eef2ff;
      --primary-dark: #4f46e5;
      --success: #22c55e;
      --warning: #f59e0b;
      --warning-light: #fef3c7;
      --warning-border: #fbbf24;
      --danger: #ef4444;
      --radius: 12px;
      --shadow: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
      --shadow-md: 0 4px 6px -1px rgba(0,0,0,.07), 0 2px 4px -2px rgba(0,0,0,.05);
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg); color: var(--text);
      line-height: 1.6; padding: 0;
    }}

    /* ── Header ─────────────────────────────────── */
    .header {{
      background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
      color: white; padding: 32px 40px 28px; margin-bottom: 28px;
    }}
    .header h1 {{ font-size: 1.75rem; font-weight: 700; letter-spacing: -0.02em; }}
    .header .subtitle {{ color: rgba(255,255,255,.75); font-size: 0.875rem; margin-top: 4px; }}

    /* ── Stats bar ──────────────────────────────── */
    .stats {{
      display: flex; gap: 14px; flex-wrap: wrap;
      padding: 0 32px; margin-top: -20px; margin-bottom: 24px;
      position: relative; z-index: 1;
    }}
    .stat-card {{
      background: var(--surface); border-radius: var(--radius);
      padding: 16px 24px; box-shadow: var(--shadow-md);
      text-align: center; min-width: 120px; flex: 1;
    }}
    .stat-card .num {{ font-size: 2rem; font-weight: 800; color: var(--primary); line-height: 1; }}
    .stat-card .lbl {{ font-size: 0.75rem; color: var(--text-muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}

    /* ── Main layout ────────────────────────────── */
    .container {{ padding: 0 32px 48px; max-width: 1400px; margin: 0 auto; }}

    /* ── Filters panel ──────────────────────────── */
    .filters {{
      background: var(--surface); border-radius: var(--radius);
      padding: 20px 24px; box-shadow: var(--shadow);
      margin-bottom: 24px;
    }}
    .filters-header {{
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 16px;
    }}
    .filters-header h2 {{ font-size: 0.95rem; font-weight: 700; color: var(--text); }}
    .filters-count {{ font-size: 0.8rem; color: var(--text-muted); }}
    .filter-row {{
      display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end;
    }}
    .filter-group {{ display: flex; flex-direction: column; gap: 4px; }}
    .filter-group label {{
      font-size: 0.72rem; font-weight: 600; color: var(--text-muted);
      text-transform: uppercase; letter-spacing: 0.05em;
    }}
    .filter-group input, .filter-group select {{
      padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px;
      font-size: 0.85rem; color: var(--text); background: var(--surface);
      outline: none; transition: border-color .15s;
    }}
    .filter-group input:focus, .filter-group select:focus {{
      border-color: var(--primary);
    }}
    .filter-group input[type="text"] {{ width: 240px; }}
    .filter-group select {{ min-width: 160px; }}
    .filter-toggle {{
      display: flex; align-items: center; gap: 8px; cursor: pointer;
      padding: 8px 14px; border: 1px solid var(--border); border-radius: 8px;
      font-size: 0.85rem; color: var(--text-secondary); background: var(--surface);
      transition: all .15s; user-select: none;
    }}
    .filter-toggle:hover {{ border-color: var(--primary); color: var(--primary); }}
    .filter-toggle.active {{
      background: var(--primary-light); border-color: var(--primary);
      color: var(--primary-dark); font-weight: 600;
    }}
    .btn-reset {{
      padding: 8px 16px; border: 1px solid var(--border); border-radius: 8px;
      font-size: 0.82rem; color: var(--text-secondary); background: var(--surface);
      cursor: pointer; transition: all .15s;
    }}
    .btn-reset:hover {{ border-color: var(--danger); color: var(--danger); }}

    /* ── Chart section ──────────────────────────── */
    .chart-section {{
      background: var(--surface); border-radius: var(--radius);
      padding: 24px; box-shadow: var(--shadow); margin-bottom: 24px;
    }}
    .chart-section h2 {{ font-size: 0.95rem; font-weight: 700; margin-bottom: 16px; }}
    .chart-wrap {{
      width: 100%; overflow-x: auto;
    }}
    .chart-wrap canvas {{
      display: block;
    }}

    /* ── User cards ─────────────────────────────── */
    .results-header {{
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 16px;
    }}
    .results-header h2 {{ font-size: 1.1rem; font-weight: 700; }}

    .user-list {{ display: flex; flex-direction: column; gap: 10px; }}
    .user-card {{
      background: var(--surface); border-radius: var(--radius);
      border: 1px solid var(--border); padding: 18px 22px;
      box-shadow: var(--shadow); transition: box-shadow .15s, border-color .15s;
      cursor: pointer;
    }}
    .user-card:hover {{ box-shadow: var(--shadow-md); border-color: var(--primary); }}
    .user-card.expanded {{ border-color: var(--primary); }}

    .card-top {{
      display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    }}
    .card-name {{
      font-weight: 700; font-size: 0.95rem; color: var(--text);
    }}
    .card-category {{
      display: inline-block; padding: 2px 10px; border-radius: 20px;
      font-size: 0.72rem; font-weight: 600; letter-spacing: 0.02em;
      background: var(--primary-light); color: var(--primary-dark);
    }}
    .card-wc {{
      display: inline-block; padding: 2px 10px; border-radius: 20px;
      font-size: 0.72rem; font-weight: 600;
      background: var(--warning-light); color: #92400e;
      border: 1px solid var(--warning-border);
    }}
    .card-tags {{ display: flex; gap: 4px; flex-wrap: wrap; margin-left: auto; }}
    .tag {{
      display: inline-block; padding: 2px 8px; border-radius: 6px;
      font-size: 0.7rem; font-weight: 500;
      background: #f1f5f9; color: #475569;
    }}
    .card-summary {{
      margin-top: 8px; font-size: 0.85rem; color: var(--text-secondary); line-height: 1.55;
    }}

    /* ── Expanded details ───────────────────────── */
    .card-details {{
      display: none; margin-top: 14px; padding-top: 14px;
      border-top: 1px solid var(--border);
    }}
    .user-card.expanded .card-details {{ display: block; }}
    .detail-grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 12px 24px;
      font-size: 0.82rem; margin-bottom: 14px;
    }}
    .detail-item {{ }}
    .detail-label {{
      font-size: 0.7rem; font-weight: 600; color: var(--text-muted);
      text-transform: uppercase; letter-spacing: 0.04em;
    }}
    .detail-value {{ color: var(--text); margin-top: 2px; }}
    .card-messages {{ margin-top: 12px; }}
    .card-messages h4 {{
      font-size: 0.78rem; font-weight: 600; color: var(--text-muted);
      text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 8px;
    }}
    .msg {{
      background: #f8fafc; border-radius: 8px; padding: 10px 14px;
      font-size: 0.82rem; color: var(--text-secondary); line-height: 1.5;
      margin-bottom: 6px; border-left: 3px solid var(--border);
      white-space: pre-wrap; word-break: break-word;
    }}
    .reasoning {{
      font-size: 0.8rem; color: var(--text-muted); font-style: italic; margin-top: 8px;
    }}

    /* ── Empty state ────────────────────────────── */
    .empty-state {{
      text-align: center; padding: 48px 24px; color: var(--text-muted);
    }}
    .empty-state .icon {{ font-size: 2.5rem; margin-bottom: 12px; }}
    .empty-state p {{ font-size: 0.9rem; }}

    /* ── Responsive ─────────────────────────────── */
    @media (max-width: 768px) {{
      .header {{ padding: 24px 20px 20px; }}
      .stats {{ padding: 0 16px; }}
      .container {{ padding: 0 16px 32px; }}
      .filter-row {{ flex-direction: column; }}
      .filter-group input[type="text"] {{ width: 100%; }}
      .detail-grid {{ grid-template-columns: 1fr; }}
      .card-tags {{ margin-left: 0; margin-top: 8px; }}
    }}
  </style>
</head>
<body>

  <div class="header">
    <h1>Telegram Channel Analysis</h1>
    <p class="subtitle">Model: {_esc(self.config.model)} &middot; {total_users} users &middot; {total_msgs} messages</p>
  </div>

  <div class="stats">
    <div class="stat-card"><div class="num">{total_users}</div><div class="lbl">Users</div></div>
    <div class="stat-card"><div class="num">{total_msgs}</div><div class="lbl">Messages</div></div>
    <div class="stat-card"><div class="num">{len(categories_list)}</div><div class="lbl">Categories</div></div>
    <div class="stat-card"><div class="num">{total_wc}</div><div class="lbl">Worth Checking</div></div>
  </div>

  <div class="container">

    <!-- Filters -->
    <div class="filters">
      <div class="filters-header">
        <h2>Filters</h2>
        <span class="filters-count" id="filterCount">Showing {total_users} of {total_users} users</span>
      </div>
      <div class="filter-row">
        <div class="filter-group">
          <label>Search</label>
          <input type="text" id="searchInput" placeholder="Name, tag, summary...">
        </div>
        <div class="filter-group">
          <label>Category</label>
          <select id="categoryFilter">
            <option value="">All categories</option>
            {"".join(f'<option value="{_esc(c)}">{_esc(c)} ({category_counts[c]})</option>' for c in categories_list)}
          </select>
        </div>
        <div class="filter-group">
          <label>Tag</label>
          <select id="tagFilter">
            <option value="">All tags</option>
            {"".join(f'<option value="{_esc(t)}">{_esc(t)}</option>' for t in all_tags)}
          </select>
        </div>
        <div class="filter-toggle" id="wcToggle" onclick="toggleWC()">
          Worth Checking only
        </div>
        <button class="btn-reset" onclick="resetFilters()">Reset</button>
      </div>
    </div>

    <!-- Chart -->
    <div class="chart-section">
      <h2>Category Distribution</h2>
      <div class="chart-wrap">
        <canvas id="chart" width="700" height="300"></canvas>
      </div>
    </div>

    <!-- Results -->
    <div class="results-header">
      <h2>Users</h2>
    </div>
    <div class="user-list" id="userList"></div>
    <div class="empty-state" id="emptyState" style="display:none;">
      <div class="icon">&#128269;</div>
      <p>No users match the current filters.</p>
    </div>
  </div>

  <script>
    // ── Data ──────────────────────────────────────────────────────────
    const ALL_USERS = {users_json};
    const COLORS = {json.dumps(CHART_COLORS)};

    // ── State ─────────────────────────────────────────────────────────
    let filterSearch = '';
    let filterCategory = '';
    let filterTag = '';
    let filterWC = false;

    // ── DOM refs ──────────────────────────────────────────────────────
    const searchInput = document.getElementById('searchInput');
    const categoryFilter = document.getElementById('categoryFilter');
    const tagFilter = document.getElementById('tagFilter');
    const wcToggle = document.getElementById('wcToggle');
    const userListEl = document.getElementById('userList');
    const emptyState = document.getElementById('emptyState');
    const filterCountEl = document.getElementById('filterCount');

    // ── Filtering ─────────────────────────────────────────────────────
    function getFiltered() {{
      return ALL_USERS.filter(u => {{
        if (filterWC && !u.worth_checking) return false;
        if (filterCategory && u.category !== filterCategory) return false;
        if (filterTag && !u.tags.some(t => t === filterTag)) return false;
        if (filterSearch) {{
          const q = filterSearch.toLowerCase();
          const haystack = [
            u.display_name, u.username, u.category, u.summary,
            ...u.tags,
            u.user_metadata.profession || '',
            u.user_metadata.city || '',
          ].join(' ').toLowerCase();
          if (!haystack.includes(q)) return false;
        }}
        return true;
      }});
    }}

    function esc(s) {{
      const d = document.createElement('div');
      d.textContent = s;
      return d.innerHTML;
    }}

    function truncate(s, n) {{
      return s.length > n ? s.slice(0, n) + '...' : s;
    }}

    function renderUsers() {{
      const filtered = getFiltered();
      filterCountEl.textContent = `Showing ${{filtered.length}} of ${{ALL_USERS.length}} users`;

      if (filtered.length === 0) {{
        userListEl.innerHTML = '';
        emptyState.style.display = 'block';
        return;
      }}
      emptyState.style.display = 'none';

      userListEl.innerHTML = filtered.map(u => {{
        const tagsHtml = u.tags.map(t => `<span class="tag">${{esc(t)}}</span>`).join('');
        const wcBadge = u.worth_checking ? '<span class="card-wc">Worth Checking</span>' : '';

        const md = u.user_metadata || {{}};
        const metaItems = [];
        if (md.profession) metaItems.push(['Profession', md.profession]);
        if (md.age) metaItems.push(['Age', md.age]);
        if (md.city) metaItems.push(['City', md.city]);
        if (md.country) metaItems.push(['Country', md.country]);
        if (md.experience_years) metaItems.push(['Experience', md.experience_years + ' years']);
        if (md.languages && md.languages.length) metaItems.push(['Languages', md.languages.join(', ')]);
        if (md.links && md.links.length) metaItems.push(['Links', md.links.join(', ')]);
        if (md.contact_info) metaItems.push(['Contact', md.contact_info]);

        const metaHtml = metaItems.length
          ? `<div class="detail-grid">${{metaItems.map(([l,v]) =>
              `<div class="detail-item"><div class="detail-label">${{esc(l)}}</div><div class="detail-value">${{esc(String(v))}}</div></div>`
            ).join('')}}</div>`
          : '';

        const msgsHtml = u.messages.map(m =>
          `<div class="msg">${{esc(truncate(m, 500))}}</div>`
        ).join('');

        return `
          <div class="user-card" onclick="this.classList.toggle('expanded')">
            <div class="card-top">
              <span class="card-name">${{esc(u.display_name)}}</span>
              <span class="card-category">${{esc(u.category)}}</span>
              ${{wcBadge}}
              <span style="color:var(--text-muted);font-size:0.78rem;">${{u.message_count}} msg${{u.message_count !== 1 ? 's' : ''}}</span>
              <div class="card-tags">${{tagsHtml}}</div>
            </div>
            <div class="card-summary">${{esc(u.summary)}}</div>
            <div class="card-details">
              ${{metaHtml}}
              <div class="reasoning">Reasoning: ${{esc(u.reasoning)}}</div>
              <div class="card-messages">
                <h4>Messages (up to 5)</h4>
                ${{msgsHtml}}
              </div>
            </div>
          </div>`;
      }}).join('');
    }}

    // ── Chart ─────────────────────────────────────────────────────────
    function renderChart() {{
      const counts = {{}};
      ALL_USERS.forEach(u => {{ counts[u.category] = (counts[u.category] || 0) + 1; }});
      const labels = Object.keys(counts).sort((a,b) => counts[b] - counts[a]);
      const data = labels.map(l => counts[l]);
      const colors = labels.map((_, i) => COLORS[i % COLORS.length]);

      new Chart(document.getElementById('chart'), {{
        type: 'bar',
        data: {{
          labels,
          datasets: [{{ label: 'Users', data, backgroundColor: colors, borderRadius: 6 }}]
        }},
        options: {{
          indexAxis: 'y',
          responsive: false,
          plugins: {{
            legend: {{ display: false }},
            tooltip: {{
              callbacks: {{
                label: ctx => {{
                  const t = ctx.dataset.data.reduce((a,b) => a+b, 0);
                  return ` ${{ctx.raw}} users (${{(ctx.raw/t*100).toFixed(1)}}%)`;
                }}
              }}
            }}
          }},
          scales: {{
            x: {{ beginAtZero: true, ticks: {{ stepSize: 1 }}, grid: {{ color: '#f1f5f9' }} }},
            y: {{ ticks: {{ font: {{ size: 12 }} }}, grid: {{ display: false }} }}
          }}
        }}
      }});
    }}

    // ── Event listeners ───────────────────────────────────────────────
    searchInput.addEventListener('input', e => {{
      filterSearch = e.target.value;
      renderUsers();
    }});
    categoryFilter.addEventListener('change', e => {{
      filterCategory = e.target.value;
      renderUsers();
    }});
    tagFilter.addEventListener('change', e => {{
      filterTag = e.target.value;
      renderUsers();
    }});

    function toggleWC() {{
      filterWC = !filterWC;
      wcToggle.classList.toggle('active', filterWC);
      renderUsers();
    }}

    function resetFilters() {{
      filterSearch = ''; filterCategory = ''; filterTag = ''; filterWC = false;
      searchInput.value = '';
      categoryFilter.value = '';
      tagFilter.value = '';
      wcToggle.classList.remove('active');
      renderUsers();
    }}

    // ── Init ──────────────────────────────────────────────────────────
    renderChart();
    renderUsers();
  </script>
</body>
</html>"""

        path = os.path.join(self.config.output_dir, "report.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        log.info("HTML → %s", path)

    # ── Console summary ───────────────────────────────────────────────

    def _print_summary(self, results: List[CategoryResult]) -> None:
        counts = Counter(r.category for r in results)
        total = len(results)
        wc = sum(1 for r in results if r.worth_checking)

        log.info("")
        log.info("─" * 56)
        log.info("  RESULTS")
        log.info("─" * 56)
        log.info("  Total users      : %d", total)
        log.info("  Total messages   : %d", sum(len(r.messages) for r in results))
        log.info("  Worth checking   : %d", wc)
        log.info("")
        for cat, n in sorted(counts.items(), key=lambda x: -x[1]):
            bar = "█" * int(n / total * 28) if total else ""
            pct = f"{n/total*100:.1f}%"
            log.info("  %-30s %4d  %6s  %s", cat, n, pct, bar)
        log.info("─" * 56)


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
