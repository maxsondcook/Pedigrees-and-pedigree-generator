"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiGet, horseHref } from "../../lib/api";
import { isStarred, toggleStar } from "../../lib/barn";
import { recordAppView } from "../../lib/appNav";

function StallionMark({ variant = "green" }) {
  const src =
    variant === "orange"
      ? "/crossr-stallion-mark-orange.png"
      : "/crossr-stallion-mark.png";
  return (
    <div className={`stallion-avatar stallion-avatar--${variant}`} aria-hidden="true">
      <img className="stallion-mark" src={src} alt="" width={56} height={36} />
    </div>
  );
}

export default function StallionsPage() {
  const [rows, setRows] = useState([]);
  const [farms, setFarms] = useState([]);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [sort, setSort] = useState("rank");
  const [showFilters, setShowFilters] = useState(false);
  const [farm, setFarm] = useState("");
  const [minFee, setMinFee] = useState("");
  const [maxFee, setMaxFee] = useState("");
  const [studMin, setStudMin] = useState("");
  const [studMax, setStudMax] = useState("");
  const [crop, setCrop] = useState("");
  const [compare, setCompare] = useState([]);
  const [error, setError] = useState("");
  const [stars, setStars] = useState(0);
  const [listMeta, setListMeta] = useState({ ms: null, total: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 180);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    Promise.all([
      apiGet("/api/stallions?sort=rank"),
      apiGet("/api/stallions/farms").catch(() => ({ farms: [] })),
    ])
      .then(([list, farmPayload]) => {
        if (cancel) return;
        setRows(list.stallions || []);
        setListMeta({ ms: list.ms, total: list.total, source: list.source });
        setFarms(farmPayload.farms || []);
        setError("");
      })
      .catch((e) => {
        if (!cancel) setError(e.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => { cancel = true; };
  }, []);

  const visible = useMemo(() => {
    const qn = debouncedQ.toLowerCase();
    const farmN = farm.replace(/_/g, " ").trim().toLowerCase();
    const minN = minFee ? Number(minFee) : null;
    const maxN = maxFee ? Number(maxFee) : null;
    const studMinN = studMin ? Number(studMin) : null;
    const studMaxN = studMax ? Number(studMax) : null;
    let next = rows.filter((s) => {
      if (qn && !String(s.name || "").toLowerCase().includes(qn) && !String(s.key || "").toLowerCase().includes(qn)) {
        return false;
      }
      if (farmN && !(s.farm || "").toLowerCase().includes(farmN)) return false;
      const fee = Number(s.stud_fee_num) || 0;
      if (minN != null && !Number.isNaN(minN) && fee < minN) return false;
      if (maxN != null && !Number.isNaN(maxN) && fee > maxN) return false;
      const entered = Number(s.entered_stud) || 0;
      if (studMinN != null && !Number.isNaN(studMinN) && entered < studMinN) return false;
      if (studMaxN != null && !Number.isNaN(studMaxN) && entered > studMaxN) return false;
      if (crop && !(s.crop || "").toLowerCase().includes(crop.toLowerCase())) return false;
      return true;
    });
    const copy = [...next];
    if (sort === "name") copy.sort((a, b) => String(a.name).localeCompare(String(b.name)));
    else if (sort === "fee_desc") copy.sort((a, b) => (b.stud_fee_num || 0) - (a.stud_fee_num || 0));
    else if (sort === "fee_asc") copy.sort((a, b) => (a.stud_fee_num || 0) - (b.stud_fee_num || 0));
    else if (sort === "stud_year") copy.sort((a, b) => (b.entered_stud || 0) - (a.entered_stud || 0));
    else if (sort === "rank") copy.sort((a, b) => (a.rank || 9999) - (b.rank || 9999) || String(a.name).localeCompare(String(b.name)));
    else copy.sort((a, b) => (b.mares_bred_2026 || 0) - (a.mares_bred_2026 || 0) || String(a.name).localeCompare(String(b.name)));
    return copy;
  }, [rows, debouncedQ, sort, farm, minFee, maxFee, studMin, studMax, crop]);

  function star(name, ev) {
    ev.preventDefault();
    ev.stopPropagation();
    toggleStar(name);
    setStars((n) => n + 1);
  }

  function toggleCompare(name, ev) {
    ev.preventDefault();
    ev.stopPropagation();
    setCompare((cur) => (cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name].slice(0, 2)));
  }

  return (
    <div>
      <div className="search-row">
        <div className="search-box">
          <span>⌕</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="LOOK UP A STALLION..."
          />
        </div>
        <button className="ghost" onClick={() => setShowFilters((v) => !v)}>Filter</button>
        <select className="ghost" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="rank">Sort: Rank</option>
          <option value="mares">Sort: Mares bred 2026</option>
          <option value="name">Sort: A–Z</option>
          <option value="fee_desc">Sort: Stud fee (high)</option>
          <option value="fee_asc">Sort: Stud fee (low)</option>
          <option value="stud_year">Sort: Year entered stud</option>
        </select>
        {compare.length === 2 ? (
          <Link className="primary" href={`/compare?a=${encodeURIComponent(compare[0])}&b=${encodeURIComponent(compare[1])}`}>
            Compare
          </Link>
        ) : (
          <button className="primary" disabled>Compare</button>
        )}
      </div>

      <p className="stallion-list-meta">
        {loading ? "Loading 2026 mares-bred stallions…" : `${visible.length} / ${rows.length} stallions`}
        {listMeta.ms != null ? ` · list API ${listMeta.ms}ms` : ""}
      </p>

      {showFilters ? (
        <div className="filters">
          <label>
            Standing location
            <select value={farm} onChange={(e) => setFarm(e.target.value)}>
              <option value="">All farms</option>
              {farms.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </label>
          <label>
            Min stud fee
            <input value={minFee} onChange={(e) => setMinFee(e.target.value)} placeholder="0" />
          </label>
          <label>
            Max stud fee
            <input value={maxFee} onChange={(e) => setMaxFee(e.target.value)} placeholder="250000" />
          </label>
          <label>
            Entered stud from
            <input value={studMin} onChange={(e) => setStudMin(e.target.value)} placeholder="2015" />
          </label>
          <label>
            Crop
            <select value={crop} onChange={(e) => setCrop(e.target.value)}>
              <option value="">Any</option>
              <option value="First-crop">First-crop</option>
              <option value="Second-crop">Second-crop</option>
              <option value="yearling">First yearlings</option>
              <option value="weanling">First weanlings</option>
              <option value="Established">Established</option>
            </select>
          </label>
        </div>
      ) : null}

      {error ? <p className="error">{error}</p> : null}

      <div className="stallion-list">
        {visible.map((s, idx) => (
          <Link
            key={s.key}
            href={horseHref(s.name)}
            className="stallion-card"
            onClick={() => {
              if (typeof window !== "undefined") {
                recordAppView(`${window.location.pathname}${window.location.search}`, "Stallions");
              }
            }}
          >
            <StallionMark variant={idx % 2 === 0 ? "green" : "orange"} />
            <div>
              <h3>{s.name}</h3>
              <div className="parents">
                {(s.sire || "—") + " × " + (s.dam || "—")}
              </div>
            </div>
            <div>
              <div className="meta-label">Stud Fee & Standing Location</div>
              <div><span className="fee">{s.stud_fee}</span> | {s.farm || "—"}</div>
              {s.mares_bred_2026 != null ? (
                <div className="stallion-mares">{s.mares_bred_2026} mares bred 2026</div>
              ) : null}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span className={`badge ${String(s.badge || "").includes("Young") ? "young" : ""}`}>{s.badge || "—"}</span>
              <button className="star" onClick={(e) => star(s.name, e)} title="Star">{isStarred(s.name) && stars >= 0 ? "★" : "☆"}</button>
              <button className="ghost" onClick={(e) => toggleCompare(s.name, e)}>
                {compare.includes(s.name) ? "Added" : "+"}
              </button>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
