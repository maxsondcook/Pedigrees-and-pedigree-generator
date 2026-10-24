"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { apiGet, horseHref } from "../../../lib/api";
import { isStarred, toggleStar, saveFavorite } from "../../../lib/barn";
import PedigreeChart from "../../../components/PedigreeChart";
import FemaleFamily from "../../../components/FemaleFamily";
import {
  horseHrefWithReturn,
  rememberSalesVisit,
  resolveReturnTarget,
} from "../../../lib/appNav";

function money(n) {
  if (n == null || n === "") return "—";
  if (typeof n === "string" && /\$/.test(n)) return n;
  const num = Number(n);
  if (!Number.isFinite(num)) return String(n);
  return `$${num.toLocaleString()}`;
}

function pickStat(source, ...keys) {
  if (!source || typeof source !== "object") return null;
  for (const key of keys) {
    const value = source[key];
    if (value != null && value !== "" && value !== "N/A") return value;
  }
  return null;
}

function formatStatValue(value) {
  if (value == null || value === "") return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    return Number.isInteger(value) ? String(value) : String(value);
  }
  return String(value);
}

function collectStatCards(source, fields) {
  const cards = [];
  for (const field of fields) {
    const value = formatStatValue(pickStat(source, ...(field.keys || [field.label])));
    if (value == null) continue;
    cards.push({ label: field.label, value });
  }
  return cards;
}

const RACING_STAT_FIELDS = [
  { label: "Crops", keys: ["Crops"] },
  { label: "Foals", keys: ["Foals"] },
  { label: "Crops of Racing Age", keys: ["Crops of Racing Age"] },
  { label: "Foals of Racing Age", keys: ["Foals of Racing Age"] },
  { label: "Champions", keys: ["Champions"] },
  { label: "Graded Blacktype Winners", keys: ["Graded Blacktype Winners"] },
  { label: "Blacktype Winners", keys: ["Blacktype Winners"] },
  { label: "Blacktype Placers", keys: ["Blacktype Placers"] },
  { label: "Starters", keys: ["Starters"] },
  { label: "Starters %", keys: ["Starters %", "Starters%"] },
  { label: "Winners %", keys: ["Winners %", "Winners%", "Winners"] },
  { label: "Blacktype Winners %", keys: ["Blacktype Winners %", "Blacktype Winners%", "Black Type %", "BTW %"] },
  { label: "Blacktype Placers %", keys: ["Blacktype Placers %", "Blacktype Placers%"] },
  { label: "Wins %", keys: ["Wins %", "Wins%"] },
  { label: "Placings %", keys: ["Placings %", "Placings%"] },
  { label: "Comparable Index", keys: ["Comparable Index", "CI"] },
  { label: "Avg Distance Raced", keys: ["Avg Distance Raced"] },
  { label: "Avg Winning Distance", keys: ["Avg Winning Distance"] },
  { label: "Avg Max Win Distance", keys: ["Avg Max Win Distance"] },
  { label: "Avg Min Win Distance", keys: ["Avg Min Win Distance"] },
];

const EARNINGS_STAT_FIELDS = [
  { label: "Earnings", keys: ["Earnings", "Total Earnings"] },
  { label: "Avg Earnings / starter", keys: ["Avg Earnings/starter", "Average Earnings Per Runner", "Avg Earnings"] },
  { label: "Avg Earnings / start", keys: ["Avg Earnings/start"] },
  { label: "Median Earnings", keys: ["Median Earnings"] },
  { label: "Avg Earnings Index", keys: ["Avg Earnings Index", "AEI"] },
];

const LEGACY_STAT_FIELDS = [
  { label: "Total Earnings", keys: ["Total Earnings"] },
  { label: "Average Progeny Win Distance", keys: ["Average Progeny Win Distance"] },
  { label: "GSW / G1W Ratio", keys: ["GSW / G1W Ratio"] },
];

function ProgenyStatSection({ title, cards }) {
  if (!cards.length) return null;
  return (
    <div className="progeny-stat-section">
      <h5>{title}</h5>
      <div className="stats-grid">
        {cards.map((card) => (
          <div className="stat-box" key={`${title}-${card.label}`}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function parseMetricNumber(val) {
  if (val == null || val === "") return null;
  if (typeof val === "number" && Number.isFinite(val)) return val;
  const text = String(val).trim();
  const paren = text.match(/\(\s*\$?\s*([\d,]+(?:\.\d+)?)\s*\)\s*$/);
  if (paren) {
    const n = Number(paren[1].replace(/,/g, ""));
    return Number.isFinite(n) ? n : null;
  }
  const cleaned = text.replace(/[,$%\s]/g, "").replace(/^\$/, "");
  if (!cleaned || cleaned === "-" || cleaned === ".") return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

function formatRankingCell(row, col) {
  const key = col.key;
  const raw = row[key];
  if (raw == null || raw === "") return "—";
  if (key === "rank") return `#${raw}`;
  if (col.type === "money") {
    if (typeof raw === "string" && /\$/.test(raw)) return raw;
    const n = row[`${key}_num`] ?? parseMetricNumber(raw);
    return n != null ? money(n) : String(raw);
  }
  return String(raw);
}

// Shown elsewhere on the page, so left out of the rankings table.
const RANKING_HIDDEN_KEYS = new Set(["chief_earner", "chief_earner_earnings", "stud_fee", "farm"]);
// Runner/winner column pairs collapsed into one Win% column.
// Raw runner/winner counts are left out; SW% (stakes winners ÷ runners) stands in for BT SWs.
const RUNNER_KEYS = new Set([
  "runners", "winners",
  "all_surfaces_runners", "all_surfaces_winners",
  "turf_runners", "turf_winners",
]);
const SW_PCT = { key: "sw_pct", label: "SW%", type: "percent" };

function shapeRankingTable(rawColumns, rawRows, rankList) {
  const keys = new Set(rawColumns.map((c) => c.key));
  const canSwPct = keys.has("runners") && keys.has("stakes_winners");
  const replacesStakesWins = canSwPct && keys.has("stakes_wins");
  const columns = [];
  for (const col of rawColumns) {
    // The Stud Fee list ranks by fee, so it keeps that column.
    if (RANKING_HIDDEN_KEYS.has(col.key) && !(rankList === "stud_fee" && col.key === "stud_fee")) continue;
    if (RUNNER_KEYS.has(col.key)) continue;
    if (col.key === "stakes_wins" && replacesStakesWins) {
      columns.push(SW_PCT);
      continue;
    }
    columns.push(col);
    if (col.key === "stakes_winners" && canSwPct && !replacesStakesWins) columns.push(SW_PCT);
  }
  const rows = canSwPct
    ? rawRows.map((row) => {
        const r = row.runners_num ?? parseMetricNumber(row.runners);
        const sw = row.stakes_winners_num ?? parseMetricNumber(row.stakes_winners);
        const pct = r && sw != null ? (sw / r) * 100 : null;
        return { ...row, sw_pct_num: pct, sw_pct: pct != null ? `${pct.toFixed(1)}%` : null };
      })
    : rawRows;
  return { columns, rows };
}

// Regional international lists fold into their parent list as earnings columns.
const RANKING_REGIONS = [
  { suffix: "_north_america", key: "north_america_earnings", label: "NA" },
  { suffix: "_japan_and_hong_kong", key: "japan_hong_kong_earnings", label: "HK/Japan" },
  { suffix: "_europe_and_dubai", key: "europe_dubai_earnings", label: "Europe/ME" },
];

function regionalParent(listId) {
  const region = RANKING_REGIONS.find((r) => listId.endsWith(r.suffix));
  return region ? listId.slice(0, -region.suffix.length) : null;
}

function mergeRegionalLists(meta) {
  const allLists = meta.lists || [];
  const ids = new Set(allLists.map((l) => l.id));
  const lists = allLists.filter((l) => {
    const parent = regionalParent(l.id);
    return !(parent && ids.has(parent));
  });
  const columns = { ...(meta.columns || {}) };
  const rows = { ...(meta.rows || {}) };
  for (const list of lists) {
    const regional = RANKING_REGIONS.filter((r) => ids.has(list.id + r.suffix));
    if (!regional.length) continue;
    const byYear = new Map();
    for (const row of rows[list.id] || []) byYear.set(row.year, { ...row });
    for (const r of regional) {
      for (const row of rows[list.id + r.suffix] || []) {
        const merged = byYear.get(row.year) || {
          year: row.year,
          rank: row.rank,
          year_earnings: row.year_earnings,
          year_earnings_num: row.year_earnings_num,
        };
        if (merged[r.key] == null && row.region_earnings != null) {
          merged[r.key] = row.region_earnings;
          merged[`${r.key}_num`] = row.region_earnings_num;
        }
        byYear.set(row.year, merged);
      }
    }
    rows[list.id] = [...byYear.values()];
    columns[list.id] = [
      { key: "year", label: "Year", type: "number" },
      { key: "rank", label: "Rank", type: "number" },
      { key: "year_earnings", label: "Earnings", type: "money" },
      ...regional.map((r) => ({ key: r.key, label: r.label, type: "money" })),
    ];
  }
  return splitSalesList(combineCropLists({ lists, columns, rows }));
}

// First/second/third-crop lists cover one year each, so they show as one list with a Crop column.
const CROP_LIST_GROUPS = [
  {
    id: "leading_crop_sires",
    label: "Leading 1st–3rd Crop Sires",
    parts: [
      ["leading_first_crop_sires", "1st"],
      ["leading_second_crop_sires", "2nd"],
      ["leading_third_crop_sires", "3rd"],
    ],
  },
  {
    id: "leading_international_crop_sires",
    label: "Leading International 1st–3rd Crop Sires",
    parts: [
      ["leading_international_first_crop_sires", "1st"],
      ["leading_international_2nd_crop_sires", "2nd"],
      ["leading_international_3rd_crop_sires", "3rd"],
    ],
  },
];

// First-crop-only stats read as mostly blank across three crops, so leave them out.
const CROP_HIDDEN_KEYS = new Set(["repeat_winners", "current_2yos", "yearling_average"]);

// Yearling sale figures published with the AEI list get their own Sales Results list.
const AEI_LIST = "leading_sires_by_aei";
const SALES_LIST = "yearling_sales_results";
const SALES_KEYS = [
  "lifetime_yearlings_sold",
  "lifetime_yearling_average",
  "yearling_window",
  "window_yearlings_sold",
  "window_yearling_average",
];

const SALES_LABELS = {
  lifetime_yearlings_sold: "Lifetime Sold",
  lifetime_yearling_average: "Lifetime Avg",
  yearling_window: "Window",
  window_yearlings_sold: "Window Sold",
  window_yearling_average: "Window Avg",
};

function splitSalesList(meta) {
  const aeiCols = meta.columns[AEI_LIST];
  if (!aeiCols || !aeiCols.some((c) => SALES_KEYS.includes(c.key))) return meta;
  const columns = { ...meta.columns };
  columns[AEI_LIST] = aeiCols.filter((c) => !SALES_KEYS.includes(c.key));
  columns[SALES_LIST] = [
    { key: "year", label: "Year", type: "number" },
    ...aeiCols
      .filter((c) => SALES_KEYS.includes(c.key))
      .map((c) => ({ ...c, label: SALES_LABELS[c.key] || c.label })),
  ];
  const rows = { ...meta.rows, [SALES_LIST]: meta.rows[AEI_LIST] || [] };
  const lists = [...meta.lists];
  const at = lists.findIndex((l) => l.id === AEI_LIST);
  if (at === -1) return meta;
  lists.splice(at + 1, 0, { ...lists[at], id: SALES_LIST, label: "Yearling Sales Results" });
  return { lists, columns, rows };
}

function cropGroupFor(listId) {
  return CROP_LIST_GROUPS.find((g) => g.parts.some(([id]) => id === listId)) || null;
}

function combineCropLists(meta) {
  let lists = [...meta.lists];
  const columns = { ...meta.columns };
  const rows = { ...meta.rows };
  for (const group of CROP_LIST_GROUPS) {
    const present = group.parts.filter(([id]) => lists.some((l) => l.id === id));
    if (!present.length) continue;
    const merged = [];
    const cols = [
      { key: "year", label: "Year", type: "number" },
      { key: "crop", label: "Crop", type: "text" },
    ];
    for (const [id, crop] of present) {
      for (const row of rows[id] || []) merged.push({ ...row, crop, crop_num: parseInt(crop, 10) });
      for (const col of columns[id] || []) {
        if (CROP_HIDDEN_KEYS.has(col.key)) continue;
        if (!cols.some((c) => c.key === col.key)) cols.push(col);
      }
    }
    const at = lists.findIndex((l) => l.id === present[0][0]);
    const firstList = lists[at];
    lists = lists.filter((l) => !present.some(([id]) => id === l.id));
    lists.splice(at, 0, { ...firstList, id: group.id, label: group.label });
    columns[group.id] = cols;
    rows[group.id] = merged;
  }
  return { lists, columns, rows };
}

function StallionRankingsPanel({ rankingMeta: rawRankingMeta, rankList: rawRankList, setRankList }) {
  const rankingMeta = useMemo(() => mergeRegionalLists(rawRankingMeta), [rawRankingMeta]);
  const parentList = regionalParent(rawRankList) && rankingMeta.lists.some((l) => l.id === regionalParent(rawRankList))
    ? regionalParent(rawRankList)
    : rawRankList;
  const groupedList = cropGroupFor(parentList)?.id || parentList;
  const isBook = (id) => (rankingMeta.lists || []).some((l) => l.id === id && l.group === "book");
  const rankList = isBook(groupedList)
    ? ((rankingMeta.lists || []).find((l) => l.group !== "book")?.id || groupedList)
    : groupedList;
  const lists = rankingMeta.lists || [];
  const bloodhorseLists = lists.filter((list) => list.group !== "book");
  // Book ranks (stud fee, mares bred) live in the Stud Fee & Mares Bred panel.
  const bookLists = [];
  const { columns, rows } = useMemo(
    () => shapeRankingTable(
      (rankingMeta.columns && rankingMeta.columns[rankList]) || [
        { key: "year", label: "Year", type: "number" },
        { key: "rank", label: "Rank", type: "number" },
      ],
      (rankingMeta.rows && rankingMeta.rows[rankList]) || [],
      rankList,
    ),
    [rankingMeta, rankList],
  );

  const [sortKey, setSortKey] = useState("year");
  const [sortDir, setSortDir] = useState("desc");

  useEffect(() => {
    setSortKey("year");
    setSortDir("desc");
  }, [rankList]);

  const visible = useMemo(() => {
    const dir = sortDir === "asc" ? 1 : -1;
    const copy = [...rows];
    copy.sort((a, b) => {
      const aNum = a[`${sortKey}_num`] ?? parseMetricNumber(a[sortKey]);
      const bNum = b[`${sortKey}_num`] ?? parseMetricNumber(b[sortKey]);
      // Missing values (—) always sort last, whichever direction.
      const aBlank = a[sortKey] == null || a[sortKey] === "";
      const bBlank = b[sortKey] == null || b[sortKey] === "";
      if (aBlank !== bBlank) return aBlank ? 1 : -1;
      if (aNum != null && bNum != null && aNum !== bNum) return (aNum - bNum) * dir;
      if (aNum != null && bNum == null) return -1;
      if (aNum == null && bNum != null) return 1;
      const as = String(a[sortKey] ?? "");
      const bs = String(b[sortKey] ?? "");
      return as.localeCompare(bs, undefined, { numeric: true }) * dir;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  function toggleSort(key) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDir(key === "year" || key === "rank" ? "desc" : "desc");
  }

  if (!lists.length) return null;

  return (
    <div className="stallion-rankings-panel">
      <h4>STALLION RANKINGS</h4>
      <div className="rankings-toolbar">
        <select
          value={rankList}
          onChange={(e) => setRankList(e.target.value)}
          aria-label="Ranking list"
        >
          {bloodhorseLists.map((list) => (
            <option key={list.id} value={list.id}>{list.label}</option>
          ))}
          {bookLists.length ? (
            <optgroup label="Book">
              {bookLists.map((list) => (
                <option key={list.id} value={list.id}>{list.label}</option>
              ))}
            </optgroup>
          ) : null}
        </select>
      </div>
      <p className="rankings-meta">
        {rows.length} {rows.length === 1 ? "year" : "years"}
        {sortKey ? ` · sorted by ${columns.find((c) => c.key === sortKey)?.label || sortKey} (${sortDir})` : ""}
      </p>
      <div className="history-wrap rankings-rich-wrap">
        <table className="rankings-rich-table">
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key}>
                  <button
                    type="button"
                    className={`rankings-sort${sortKey === col.key ? " active" : ""}`}
                    onClick={() => toggleSort(col.key)}
                  >
                    {col.label}
                    {sortKey === col.key ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={`${rankList}-${row.year}-${row.table_name || ""}`}>
                {columns.map((col) => (
                  <td
                    key={col.key}
                    className={col.type === "money" || col.key === "aei" || col.key === "comparable_index" ? "money" : undefined}
                  >
                    {formatRankingCell(row, col)}
                  </td>
                ))}
              </tr>
            ))}
            {!visible.length ? (
              <tr>
                <td colSpan={Math.max(columns.length, 1)} className="rankings-empty">
                  No ranking rows match this filter.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HorsePage() {
  const { name } = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const decoded = decodeURIComponent(name || "");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const [rankList, setRankList] = useState("leading_sire");
  const returnTarget = useMemo(() => resolveReturnTarget(searchParams), [searchParams]);
  const salesReturn = returnTarget.sales;
  const hrefFor = useMemo(
    () => (horseName) => (salesReturn ? horseHrefWithReturn(horseName, salesReturn) : horseHref(horseName)),
    [salesReturn],
  );

  useEffect(() => {
    if (salesReturn) rememberSalesVisit(salesReturn, decoded);
  }, [salesReturn, decoded]);

  useEffect(() => {
    setData(null);
    setRankList("leading_sire");
    apiGet(`/api/horses/${encodeURIComponent(decoded)}`)
      .then((payload) => {
        setData(payload);
        const lists = (payload && payload.sire_rankings && payload.sire_rankings.lists) || [];
        const preferred = lists.find((list) => list.id === "leading_sire") || lists[0];
        setRankList(preferred ? preferred.id : "leading_sire");
      })
      .catch((e) => setError(e.message));
  }, [decoded]);

  function goBack() {
    const href = returnTarget?.href;
    if (href) {
      router.push(href);
      return;
    }
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back();
      return;
    }
    router.push("/stallions");
  }

  const backLabel = returnTarget?.label
    ? `← Go Back · ${returnTarget.label}`
    : "← Go Back";

  if (error) {
    return (
      <div>
        <div className="sales-return-bar">
          <button className="primary" type="button" onClick={goBack}>{backLabel}</button>
          <button className="ghost" type="button" onClick={goBack}>Close</button>
        </div>
        <p className="error">{error}</p>
      </div>
    );
  }
  if (!data) {
    return (
      <div>
        <div className="sales-return-bar">
          <button className="primary" type="button" onClick={goBack}>{backLabel}</button>
          <button className="ghost" type="button" onClick={goBack}>Close</button>
        </div>
        <p className="empty">Loading profile…</p>
      </div>
    );
  }
  if (data.ambiguous) {
    return (
      <div className="panel">
        <div className="sales-return-bar">
          <button className="primary" type="button" onClick={goBack}>{backLabel}</button>
          <button className="ghost" type="button" onClick={goBack}>Close</button>
        </div>
        <h2>Which {data.name}?</h2>
        <p className="sub">Multiple horses named {data.name} are in the pedigree database. Choose a foaling year.</p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          {(data.years || []).map((year) => (
            <Link key={year} className="primary" href={hrefFor(`${data.name} (${year})`)}>
              {data.name} ({year})
            </Link>
          ))}
        </div>
      </div>
    );
  }

  const s = data.stallion || {};
  const racing = s.progeny_racing || {};
  const earn = s.progeny_earnings || {};
  const legacy = s.legacy_progeny || {};
  const racingCards = collectStatCards(racing, RACING_STAT_FIELDS);
  const earningsCards = collectStatCards(earn, EARNINGS_STAT_FIELDS);
  const legacyCards = collectStatCards(legacy, LEGACY_STAT_FIELDS);
  const hasProgenyStats = racingCards.length || earningsCards.length || legacyCards.length;
  const totals = data.race_totals || {};
  const family = data.female_family || [];
  const bmsCountLabel = (data.broodmare_sire || []).find((row) => row.count_label)?.count_label || "Runners";
  const rankingMeta = data.sire_rankings || {};
  const RANK_LISTS = rankingMeta.lists || [];
  // Stud fee / mares bred ranks show beside the book figures, not in the rankings list.
  const bookRank = { stud_fee: {}, mares_bred: {} };
  for (const id of Object.keys(bookRank)) {
    for (const row of (rankingMeta.rows || {})[id] || []) bookRank[id][row.year] = row.rank;
  }

  return (
    <div className="dash">
      <div className="sales-return-bar dash-span">
        <button className="primary" type="button" onClick={goBack}>
          {backLabel}
        </button>
        <button className="ghost" type="button" onClick={goBack}>Close</button>
        <button
          className="ghost star-btn"
          type="button"
          title="Star"
          onClick={() => { toggleStar(data.name); saveFavorite(data.name); setTick((n) => n + 1); }}
        >
          {isStarred(data.name) && tick >= 0 ? "★" : "☆"}
        </button>
      </div>
      <div>
        <div className="panel">
          <h4>PEDIGREE</h4>
          <PedigreeChart tree={data.pedigree} showSubject={false} hrefFor={hrefFor} />
        </div>
        <div className="panel family-panel" style={{ marginTop: 12 }}>
          <h4>FEMALE FAMILY</h4>
          <FemaleFamily family={family} hrefFor={hrefFor} />
        </div>
      </div>

      <div className="horse-panels">
        <div className="panel">
          <div className="hero">
            <div className="farm">{s.farm || "PEDIGREE PROFILE"}</div>
            <h1>{data.name.toUpperCase()}</h1>
            <div className="sub">
              Foaled: {s.year_foaled || data.year || "—"} · Entered Stud: {s.entered_stud || "—"}
            </div>
            <div className="kpi-row">
              <div className="kpi">
                <span>Stud Fee</span>
                <b>{s.stud_fee || "—"}</b>
              </div>
              <div className="kpi">
                <span>Sire Rank</span>
                <b className="muted">{s.rank ? `#${s.rank}` : "NA"}</b>
              </div>
            </div>
          </div>
          {s.career_highlight ? (
            <div className="notes" style={{ marginTop: 16 }}>{s.career_highlight}</div>
          ) : null}
          <div style={{ marginTop: 16, textAlign: "center" }}>
            <Link className="primary" href={data.has_profile ? `/hypomating?sire=${encodeURIComponent(data.name)}` : `/hypomating?mare=${encodeURIComponent(data.name)}`}>
              {data.has_profile ? "Select for hypomating" : "Use as broodmare"}
            </Link>
          </div>
        </div>

        <div className="panel">
          <h4>RACE RECORD & MAJOR WINS</h4>
          <table>
            <thead>
              <tr>
                <th>Season</th><th>Age</th><th>Starts</th><th>1st</th><th>2nd</th><th>3rd</th><th>Earnings</th>
              </tr>
            </thead>
            <tbody>
              {(data.race_record || []).map((r) => (
                <tr key={r.age}>
                  <td>{r.season}</td>
                  <td>{String(r.age ?? "").match(/\d+/)?.[0] || r.age}</td>
                  <td>{r.starts}</td>
                  <td>{r.firsts}</td>
                  <td>{r.seconds}</td>
                  <td>{r.thirds}</td>
                  <td className="money">{r.earnings_display}</td>
                </tr>
              ))}
              <tr>
                <td>TOTAL</td>
                <td>—</td>
                <td>{totals.starts || 0}</td>
                <td>{totals.firsts || 0}</td>
                <td>{totals.seconds || 0}</td>
                <td>{totals.thirds || 0}</td>
                <td className="money">{money(totals.earnings)}</td>
              </tr>
            </tbody>
          </table>
          {s.major_wins ? <div className="notes" style={{ marginTop: 12 }}>{s.major_wins}</div> : null}
        </div>

        {(data.stud_book || []).length ? (
          <div className="panel">
            <h4>STUD FEE & MARES BRED</h4>
          <div className="history-wrap">
            <table>
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Stud Fee</th>
                  <th>Fee Rank</th>
                  <th>Mares Bred</th>
                  <th>MB Rank</th>
                  <th>Live Foals</th>
                  <th>Live Foal %</th>
                </tr>
              </thead>
              <tbody>
                {data.stud_book.map((row) => (
                  <tr key={row.year}>
                    <td>{row.year}</td>
                    <td className="money">{row.stud_fee || "—"}</td>
                    <td>{bookRank.stud_fee[row.year] ? `#${bookRank.stud_fee[row.year]}` : "—"}</td>
                    <td>{row.mares_bred ?? "—"}</td>
                    <td>{bookRank.mares_bred[row.year] ? `#${bookRank.mares_bred[row.year]}` : "—"}</td>
                    <td>{row.live_foals ?? "—"}</td>
                    <td>{row.live_foal_pct || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </div>
        ) : null}

        {data.stallion && RANK_LISTS.length ? (
          <div className="panel">
            <StallionRankingsPanel
              rankingMeta={rankingMeta}
              rankList={rankList}
              setRankList={setRankList}
            />
          </div>
        ) : null}

        <div className="panel progeny-stats-panel">
          <h4>PROGENY STATISTICS</h4>
          {hasProgenyStats ? (
            <div className="progeny-stats-scroll">
              <ProgenyStatSection title="Racing" cards={racingCards} />
              <ProgenyStatSection title="Earnings" cards={earningsCards} />
              <ProgenyStatSection title="Legacy" cards={legacyCards} />
            </div>
          ) : (
            <p className="catalog-empty">No progeny statistics on file yet.</p>
          )}
        </div>

        <div className="panel">
          <h4>TOP PROGENY</h4>
          {(data.top_progeny || []).length ? (
            <table>
              <thead>
                <tr><th>Horse</th><th>Broodmare Sire</th><th>Class</th><th>Earnings</th></tr>
              </thead>
              <tbody>
                {[...data.top_progeny]
                  .sort((a, b) => (Number(b.earnings) || 0) - (Number(a.earnings) || 0))
                  .map((p) => (
                  <tr key={p.name}>
                    <td><Link href={hrefFor(p.name)}>{p.name}</Link></td>
                    <td>{p.broodmare_sire}</td>
                    <td>{p.class}</td>
                    <td className="money">{p.earnings != null ? money(p.earnings) : (p.earnings_display || "—")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="catalog-empty">No top progeny recorded for this stallion yet.</p>
          )}
        </div>

        {(data.broodmare_sire || []).length ? (
          <div className="panel">
            <h4>BROODMARE SIRE</h4>
          <div className="history-wrap">
            <table>
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Rank</th>
                  <th>Earnings $</th>
                  <th>{bmsCountLabel}</th>
                </tr>
              </thead>
              <tbody>
                {data.broodmare_sire.map((row) => (
                  <tr key={row.year}>
                    <td>{row.year}</td>
                    <td>{row.rank ? `#${row.rank}` : "—"}</td>
                    <td className="money">{row.earnings != null ? money(row.earnings) : "—"}</td>
                    <td>{row.count ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function HorsePageSuspense() {
  return (
    <Suspense fallback={<p className="empty">Loading profile…</p>}>
      <HorsePage />
    </Suspense>
  );
}
