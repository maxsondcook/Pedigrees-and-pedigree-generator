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

function StallionRankingsPanel({ rankingMeta, rankList, setRankList }) {
  const lists = rankingMeta.lists || [];
  const bloodhorseLists = lists.filter((list) => list.group !== "book");
  const bookLists = lists.filter((list) => list.group === "book");
  const rows = (rankingMeta.rows && rankingMeta.rows[rankList]) || [];
  const columns = (rankingMeta.columns && rankingMeta.columns[rankList]) || [
    { key: "year", label: "Year", type: "number" },
    { key: "rank", label: "Rank", type: "number" },
  ];
  const metricOptions = columns.filter((c) => c.key !== "year");

  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("year");
  const [sortDir, setSortDir] = useState("desc");
  const [filterMetric, setFilterMetric] = useState("");
  const [filterMin, setFilterMin] = useState("");
  const [filterMax, setFilterMax] = useState("");

  useEffect(() => {
    setQuery("");
    setSortKey("year");
    setSortDir("desc");
    setFilterMetric("");
    setFilterMin("");
    setFilterMax("");
  }, [rankList]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const minN = filterMin !== "" ? Number(filterMin) : null;
    const maxN = filterMax !== "" ? Number(filterMax) : null;
    let next = rows.filter((row) => {
      if (q) {
        const hay = columns
          .map((col) => String(row[col.key] ?? ""))
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (filterMetric) {
        const num = row[`${filterMetric}_num`] ?? parseMetricNumber(row[filterMetric]);
        if (minN != null && !Number.isNaN(minN)) {
          if (num == null || num < minN) return false;
        }
        if (maxN != null && !Number.isNaN(maxN)) {
          if (num == null || num > maxN) return false;
        }
      }
      return true;
    });
    const dir = sortDir === "asc" ? 1 : -1;
    const copy = [...next];
    copy.sort((a, b) => {
      const aNum = a[`${sortKey}_num`] ?? parseMetricNumber(a[sortKey]);
      const bNum = b[`${sortKey}_num`] ?? parseMetricNumber(b[sortKey]);
      if (aNum != null && bNum != null && aNum !== bNum) return (aNum - bNum) * dir;
      if (aNum != null && bNum == null) return -1 * dir;
      if (aNum == null && bNum != null) return 1 * dir;
      const as = String(a[sortKey] ?? "");
      const bs = String(b[sortKey] ?? "");
      return as.localeCompare(bs, undefined, { numeric: true }) * dir;
    });
    return copy;
  }, [rows, columns, query, sortKey, sortDir, filterMetric, filterMin, filterMax]);

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
    <div className="stallion-rankings-panel" style={{ marginTop: 16 }}>
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
        <input
          className="rankings-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search metrics…"
          aria-label="Search ranking rows"
        />
        <select
          value={filterMetric}
          onChange={(e) => setFilterMetric(e.target.value)}
          aria-label="Filter metric"
        >
          <option value="">Filter metric…</option>
          {metricOptions.map((col) => (
            <option key={col.key} value={col.key}>{col.label}</option>
          ))}
        </select>
        <input
          className="rankings-range"
          value={filterMin}
          onChange={(e) => setFilterMin(e.target.value)}
          placeholder="Min"
          inputMode="decimal"
          disabled={!filterMetric}
          aria-label="Minimum metric value"
        />
        <input
          className="rankings-range"
          value={filterMax}
          onChange={(e) => setFilterMax(e.target.value)}
          placeholder="Max"
          inputMode="decimal"
          disabled={!filterMetric}
          aria-label="Maximum metric value"
        />
      </div>
      <p className="rankings-meta">
        {visible.length} / {rows.length} years
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
  const bmsRank = s.broodmare_rank || (data.broodmare_sire || []).find((row) => row.rank)?.rank;
  const bmsCountLabel = (data.broodmare_sire || []).find((row) => row.count_label)?.count_label || "Runners";
  const rankingMeta = data.sire_rankings || {};
  const RANK_LISTS = rankingMeta.lists || [];

  return (
    <div className="dash">
      <div className="sales-return-bar dash-span">
        <button className="primary" type="button" onClick={goBack}>
          {backLabel}
        </button>
        <button className="ghost" type="button" onClick={goBack}>Close</button>
      </div>
      <div>
        <div className="panel">
          <h4>SALES CATALOG PEDIGREE</h4>
          <PedigreeChart tree={data.pedigree} showSubject={false} hrefFor={hrefFor} />
        </div>
        <div className="panel family-panel" style={{ marginTop: 12 }}>
          <h4>FEMALE FAMILY</h4>
          <FemaleFamily family={family} hrefFor={hrefFor} />
        </div>
      </div>

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
            <div className="kpi">
              <span>BMS Rank</span>
              <b className="muted">{bmsRank ? `#${bmsRank}` : "NA"}</b>
            </div>
          </div>
        </div>
        <h4 style={{ marginTop: 16 }}>RACE RECORD & MAJOR WINS</h4>
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
                <td>{r.age}</td>
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
        {(data.stud_book || []).length ? (
          <div style={{ marginTop: 16 }}>
            <h4>STUD FEE & MARES BRED</h4>
            <div className="history-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Year</th>
                    <th>Stud Fee</th>
                    <th>Mares Bred</th>
                    <th>Live Foals</th>
                    <th>Live Foal %</th>
                  </tr>
                </thead>
                <tbody>
                  {data.stud_book.map((row) => (
                    <tr key={row.year}>
                      <td>{row.year}</td>
                      <td className="money">{row.stud_fee || "—"}</td>
                      <td>{row.mares_bred ?? "—"}</td>
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
          <StallionRankingsPanel
            rankingMeta={rankingMeta}
            rankList={rankList}
            setRankList={setRankList}
          />
        ) : null}
        {s.career_highlight ? (
          <div className="notes" style={{ marginTop: 16 }}>{s.career_highlight}</div>
        ) : null}
        <div style={{ marginTop: 16 }}>
          <Link className="primary" href={data.has_profile ? `/hypomating?sire=${encodeURIComponent(data.name)}` : `/hypomating?mare=${encodeURIComponent(data.name)}`}>
            {data.has_profile ? "Select for hypomating" : "Use as broodmare"}
          </Link>
        </div>
      </div>

      <div>
        {(data.broodmare_sire || []).length ? (
          <div className="panel" style={{ marginBottom: 12 }}>
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
        <div className="panel" style={{ marginTop: 12 }}>
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
      </div>

      <div className="tools">
        <button onClick={() => { toggleStar(data.name); saveFavorite(data.name); setTick((n) => n + 1); }} title="Star">
          {isStarred(data.name) && tick >= 0 ? "★" : "☆"}
        </button>
        <button type="button" onClick={goBack} title="Go Back">←</button>
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
