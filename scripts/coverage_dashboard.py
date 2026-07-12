#!/usr/bin/env python3
"""Generate a self-contained HTML dashboard of data coverage by brand and
model family, to spot where data is missing and prioritize what to fill
next (specs AJAX gap, price enrichment, review-less families...).

Reads the live database, embeds aggregates as inline JSON (a few hundred
rows, not the raw catalog), writes coverage_dashboard.html at the repo
root. No external assets — openable offline, publishable as an artifact.

Run: PYTHONPATH=src .venv/bin/python scripts/coverage_dashboard.py
"""

import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
load_dotenv()

from bikefinder_rag.db.client import get_connection

OUT_PATH = Path(__file__).resolve().parent.parent / "coverage_dashboard.html"

# (json key, DB column, display label)
SPEC_FIELDS = [
    ("weight", "weight_kg", "Poids"),
    ("power", "power_hp", "Puissance"),
    ("torque", "torque_nm", "Couple"),
    ("seat", "seat_height_mm", "Hauteur selle"),
    ("displacement", "displacement_ccm", "Cylindrée"),
    ("price", "msrp_eur", "Prix"),
]


def fetchall(conn, sql):
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def collect(conn) -> dict:
    missing_exprs = ", ".join(
        f"count(*) FILTER (WHERE {col} IS NULL) AS miss_{key}" for key, col, _ in SPEC_FIELDS
    )
    brands = fetchall(conn, f"""
        SELECT m.brand, count(*) AS n_motos,
               min(m.year) AS year_min, max(m.year) AS year_max,
               count(DISTINCT m.family_id) AS n_families,
               count(DISTINCT rc.family_id) AS n_families_reviewed,
               {missing_exprs}
        FROM motorcycles m
        LEFT JOIN review_chunks rc ON rc.family_id = m.family_id
        GROUP BY m.brand
        ORDER BY n_motos DESC
    """)

    families = fetchall(conn, f"""
        SELECT f.brand, f.family_name, f.year_min, f.year_max,
               count(DISTINCT m.id) AS n_motos,
               (SELECT count(*) FROM review_chunks rc WHERE rc.family_id = f.id) AS n_comments,
               {missing_exprs}
        FROM model_families f
        JOIN motorcycles m ON m.family_id = f.id
        GROUP BY f.id, f.brand, f.family_name, f.year_min, f.year_max
    """)

    orphans = fetchall(conn, f"""
        SELECT m.brand, 'Sans forum' AS family_name,
               min(m.year) AS year_min, max(m.year) AS year_max,
               count(*) AS n_motos, 0 AS n_comments, {missing_exprs}
        FROM motorcycles m WHERE m.family_id IS NULL
        GROUP BY m.brand
    """)

    totals = fetchall(conn, f"""
        SELECT count(*) AS n_motos,
               (SELECT count(*) FROM model_families) AS n_families,
               (SELECT count(*) FROM review_chunks) AS n_comments,
               (SELECT count(DISTINCT family_id) FROM review_chunks) AS n_families_reviewed,
               {missing_exprs}
        FROM motorcycles
    """)[0]

    return {
        "generated": date.today().isoformat(),
        "fields": [{"key": k, "label": lbl} for k, _, lbl in SPEC_FIELDS],
        "totals": totals,
        "brands": brands,
        "families": families + orphans,
    }


HTML_TEMPLATE = r"""<title>Bikefinder — couverture des données</title>
<style>
.viz-root {
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --ink-1: #0b0b0b; --ink-2: #52514e; --ink-3: #898781;
  --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
  --seq-100:#cde2fb; --seq-200:#9ec5f4; --seq-300:#6da7ec; --seq-400:#3987e5;
  --seq-500:#256abf; --seq-600:#184f95; --seq-700:#0d366b;
  --cell-full:#f1f0ec;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .viz-root {
    --surface-1: #1a1a19; --page: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
    --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    --cell-full:#232322;
  }
}
:root[data-theme="dark"] .viz-root {
  --surface-1: #1a1a19; --page: #0d0d0d;
  --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
  --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
  --cell-full:#232322;
}
* { box-sizing: border-box; }
body { margin: 0; }
.viz-root {
  min-height: 100vh; background: var(--page); color: var(--ink-1);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 14px; line-height: 1.45; padding: 2rem 1.2rem 4rem;
}
.wrap { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 1.35rem; margin: 0 0 0.2rem; }
.sub { color: var(--ink-2); margin: 0 0 1.4rem; max-width: 72ch; }
h2 { font-size: 1.02rem; margin: 2rem 0 0.2rem; }
.hint { color: var(--ink-3); font-size: 0.82rem; margin: 0 0 0.8rem; }

.kpis { display: flex; gap: 0.8rem; flex-wrap: wrap; margin-bottom: 0.6rem; }
.kpi {
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
  padding: 0.7rem 1rem; min-width: 130px;
}
.kpi .v { font-size: 1.55rem; font-weight: 650; }
.kpi .l { color: var(--ink-3); font-size: 0.75rem; letter-spacing: 0.04em; text-transform: uppercase; }

.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 1rem; }
.scroll { overflow-x: auto; }

table { border-collapse: collapse; width: 100%; }
th, td { padding: 0.32rem 0.5rem; text-align: left; white-space: nowrap; }
thead th {
  color: var(--ink-3); font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em;
  border-bottom: 1px solid var(--grid); position: sticky; top: 0; background: var(--surface-1);
  cursor: pointer; user-select: none;
}
thead th.sorted { color: var(--ink-1); }
tbody td { border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: color-mix(in srgb, var(--seq-400) 7%, transparent); }

.hm td.cell { padding: 0; }
.hm .swatch {
  display: block; width: 100%; height: 22px; border-radius: 3px; margin: 1px;
  min-width: 64px; position: relative;
}
.brand-btn { background: none; border: none; color: var(--ink-1); font: inherit; cursor: pointer; padding: 0; }
.brand-btn:hover { text-decoration: underline; }
.num { text-align: right; }
td.num, th.num { text-align: right; }

.legend { display: flex; align-items: center; gap: 0.5rem; margin: 0.7rem 0 0; color: var(--ink-3); font-size: 0.78rem; }
.legend .ramp { display: flex; height: 10px; border-radius: 3px; overflow: hidden; }
.legend .ramp i { width: 26px; }

.controls { display: flex; gap: 0.7rem; align-items: center; margin: 0 0 0.7rem; flex-wrap: wrap; }
input[type="search"] {
  background: var(--surface-1); color: var(--ink-1); border: 1px solid var(--grid);
  border-radius: 6px; padding: 0.38rem 0.6rem; font: inherit; width: 240px;
}
.chip {
  background: color-mix(in srgb, var(--seq-400) 14%, transparent); border: none; color: var(--ink-1);
  border-radius: 999px; padding: 0.22rem 0.7rem; font: inherit; font-size: 0.82rem; cursor: pointer;
  display: none;
}
.chip.on { display: inline-block; }

#tooltip {
  position: fixed; pointer-events: none; z-index: 10; display: none;
  background: var(--ink-1); color: var(--page); border-radius: 6px;
  padding: 0.4rem 0.6rem; font-size: 0.78rem; max-width: 260px; white-space: normal;
}
.foot { color: var(--ink-3); font-size: 0.78rem; margin-top: 2.2rem; }
</style>

<div class="viz-root"><div class="wrap">
  <h1>Couverture des données Bikefinder</h1>
  <p class="sub">Où manque-t-il de la donnée, et où est-il rentable de la combler ?
  Plus une cellule est <b>foncée</b>, plus il <b>manque</b> de données. Cliquer une marque
  filtre la table des familles ; trier la table donne la liste de priorités.</p>

  <div class="kpis" id="kpis"></div>

  <h2>Manque par marque et par champ</h2>
  <p class="hint">% d'enregistrements sans valeur — survoler pour le détail, cliquer la marque pour le drill-down.</p>
  <div class="card scroll"><table class="hm" id="heatmap"></table>
    <div class="legend"><span>0 % manquant</span><span class="ramp" id="ramp"></span><span>100 % manquant</span></div>
  </div>

  <h2>Familles de modèles — priorités de comblement</h2>
  <p class="hint">Score = motos × part de champs manquants (avis compris). Trier par n'importe quelle colonne.</p>
  <div class="controls">
    <input type="search" id="search" placeholder="Filtrer (marque, famille)…">
    <button class="chip" id="brandChip"></button>
  </div>
  <div class="card scroll"><table id="famTable"></table></div>

  <p class="foot" id="foot"></p>
</div></div>
<div id="tooltip"></div>

<script>
const DATA = /*DATA*/;

const RAMP = ['var(--cell-full)','var(--seq-100)','var(--seq-200)','var(--seq-300)',
              'var(--seq-400)','var(--seq-500)','var(--seq-600)','var(--seq-700)'];
const rampColor = pct => pct <= 0 ? RAMP[0] : RAMP[Math.min(7, 1 + Math.floor(pct / (100/7)))];
const inkFor = pct => pct > 55 ? '#ffffff' : 'var(--ink-1)';
const fmt = n => n.toLocaleString('fr-FR');

const F = DATA.fields;
const T = DATA.totals;

// --- KPIs
const reviewMissTotal = Math.round(100 * (1 - T.n_families_reviewed / T.n_families));
document.getElementById('kpis').innerHTML = [
  [fmt(T.n_motos), 'motos'],
  [fmt(T.n_families), 'familles'],
  [fmt(T.n_comments), 'avis'],
  [Math.round(100 * T.miss_price / T.n_motos) + ' %', 'sans prix'],
  [Math.round(100 * T.miss_weight / T.n_motos) + ' %', 'sans poids'],
  [reviewMissTotal + ' %', 'familles sans avis'],
].map(([v, l]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');

// --- Heatmap (marques x champs, % manquant)
const tooltip = document.getElementById('tooltip');
function showTip(e, html) {
  tooltip.innerHTML = html; tooltip.style.display = 'block';
  tooltip.style.left = Math.min(e.clientX + 14, innerWidth - 280) + 'px';
  tooltip.style.top = (e.clientY + 14) + 'px';
}
function hideTip() { tooltip.style.display = 'none'; }

const hm = document.getElementById('heatmap');
const cols = ['Marque', 'Motos', ...F.map(f => f.label), 'Avis'];
hm.innerHTML = '<thead><tr>' + cols.map(c => `<th${c==='Motos'?' class="num"':''}>${c}</th>`).join('') + '</tr></thead>' +
  '<tbody>' + DATA.brands.map(b => {
    const cells = F.map(f => {
      const pct = Math.round(100 * b['miss_' + f.key] / b.n_motos);
      return { label: f.label, pct, detail: `${fmt(b['miss_' + f.key])} / ${fmt(b.n_motos)} motos sans valeur` };
    });
    const revPct = b.n_families ? Math.round(100 * (1 - b.n_families_reviewed / b.n_families)) : 100;
    cells.push({ label: 'Avis', pct: revPct,
                 detail: `${b.n_families - b.n_families_reviewed} / ${b.n_families} familles sans aucun avis` });
    return `<tr><td><button class="brand-btn" data-brand="${b.brand}">${b.brand}</button></td>` +
      `<td class="num">${fmt(b.n_motos)}</td>` +
      cells.map(c => `<td class="cell"><span class="swatch" style="background:${rampColor(c.pct)}"
        data-tip="<b>${b.brand} — ${c.label}</b><br>${c.pct} % manquant<br>${c.detail}"></span></td>`).join('') +
      '</tr>';
  }).join('') + '</tbody>';

hm.addEventListener('mousemove', e => {
  const s = e.target.closest('.swatch');
  s ? showTip(e, s.dataset.tip) : hideTip();
});
hm.addEventListener('mouseleave', hideTip);

document.getElementById('ramp').innerHTML = RAMP.map(c => `<i style="background:${c}"></i>`).join('');

// --- Table familles (priorités)
const famFieldKeys = F.map(f => f.key);
const rows = DATA.families.map(f => {
  const missing = famFieldKeys.reduce((s, k) => s + (f['miss_' + k] > 0 ? 1 : 0), 0) + (f.n_comments === 0 ? 1 : 0);
  const missShare = missing / (famFieldKeys.length + 1);
  return { ...f, missing, score: Math.round(f.n_motos * missShare * 10) / 10 };
});

const COLS = [
  ['brand', 'Marque'], ['family_name', 'Famille'], ['years', 'Années'],
  ['n_motos', 'Motos', 'num'], ['n_comments', 'Avis', 'num'],
  ['missing', 'Champs manquants', 'num'], ['score', 'Score priorité', 'num'],
];
let sortKey = 'score', sortDir = -1, brandFilter = null;

const famTable = document.getElementById('famTable');
function renderFam() {
  const q = document.getElementById('search').value.toLowerCase();
  let list = rows.filter(r =>
    (!brandFilter || r.brand === brandFilter) &&
    (!q || (r.brand + ' ' + r.family_name).toLowerCase().includes(q)));
  list.sort((a, b) => {
    const va = sortKey === 'years' ? a.year_min : a[sortKey], vb = sortKey === 'years' ? b.year_min : b[sortKey];
    return (va < vb ? -1 : va > vb ? 1 : 0) * sortDir;
  });
  famTable.innerHTML = '<thead><tr>' +
    COLS.map(([k, l, cls]) => `<th data-key="${k}" class="${cls || ''} ${k === sortKey ? 'sorted' : ''}">` +
      `${l}${k === sortKey ? (sortDir < 0 ? ' ↓' : ' ↑') : ''}</th>`).join('') +
    '</tr></thead><tbody>' +
    list.slice(0, 400).map(r => `<tr>
      <td>${r.brand}</td><td>${r.family_name}</td>
      <td>${r.year_min === r.year_max ? r.year_min : r.year_min + '–' + r.year_max}</td>
      <td class="num">${fmt(r.n_motos)}</td><td class="num">${fmt(r.n_comments)}</td>
      <td class="num">${r.missing} / ${famFieldKeys.length + 1}</td><td class="num"><b>${r.score}</b></td>
    </tr>`).join('') + '</tbody>';
  document.getElementById('foot').textContent =
    `${fmt(list.length)} familles affichées (max 400 lignes rendues) — généré le ${DATA.generated}, ` +
    `base: ${fmt(T.n_motos)} motos / ${fmt(T.n_comments)} avis.`;
}
famTable.addEventListener('click', e => {
  const th = e.target.closest('th');
  if (!th) return;
  const k = th.dataset.key;
  if (k === sortKey) sortDir *= -1; else { sortKey = k; sortDir = -1; }
  renderFam();
});
document.getElementById('search').addEventListener('input', renderFam);

const chip = document.getElementById('brandChip');
hm.addEventListener('click', e => {
  const btn = e.target.closest('.brand-btn');
  if (!btn) return;
  brandFilter = btn.dataset.brand;
  chip.textContent = brandFilter + ' ✕';
  chip.classList.add('on');
  renderFam();
  document.getElementById('famTable').scrollIntoView({ behavior: 'smooth', block: 'start' });
});
chip.addEventListener('click', () => { brandFilter = null; chip.classList.remove('on'); renderFam(); });

renderFam();
</script>
"""


def main() -> None:
    conn = get_connection()
    try:
        data = collect(conn)
    finally:
        conn.close()

    html = HTML_TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False, default=str))
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"{len(data['brands'])} marques, {len(data['families'])} lignes familles -> {OUT_PATH}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
