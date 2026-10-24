"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { apiGet, apiPost, horseHref } from "../../lib/api";
import { horseCaps } from "../../lib/display";
import {
  clearHypomatingSession,
  loadHypomatingSession,
  recordAppView,
  saveHypomatingSession,
} from "../../lib/appNav";
import { saveHypofoal } from "../../lib/barn";
import PedigreeChart from "../../components/PedigreeChart";
import FemaleFamily from "../../components/FemaleFamily";
import HorseText from "../../components/HorseText";
import HypofoalDetail from "../../components/HypofoalDetail";

const STATUS_ORDER = ["MG1W", "G1W", "MGSW", "G2W", "G3W", "MSW", "SW"];
const GRADE_ORDER = { G1: 0, G2: 1, G3: 2 };

function sortCrosses(crosses) {
  return [...crosses].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status));
}

// Racing-age sex: stallions raced as colts, mares as fillies.
const SEX_AT_RACING = { C: "C.", H: "C.", F: "F.", M: "F.", G: "G.", R: "R." };

function sexAbbrev(sex) {
  const letter = String(sex || "").trim().charAt(0).toUpperCase();
  return SEX_AT_RACING[letter] || (letter ? `${letter}.` : "");
}

function HorseLink({ name }) {
  if (!name) return null;
  return <Link className="horse-inline-link" href={horseHref(name)}>{horseCaps(name)}</Link>;
}

/** PRACTICAL JOKE [MG1W] (C. BY INTO MISCHIEF) OUT OF THE MARE HALO HUMOR (M. BY DISTORTED HUMOR), then its wins. */
function CrossSuccess({ cross }) {
  const sex = sexAbbrev(cross.sex);
  const wins = [...(cross.wins || [])].sort((a, b) => {
    const ga = GRADE_ORDER[String(a.grade).toUpperCase()] ?? 9;
    const gb = GRADE_ORDER[String(b.grade).toUpperCase()] ?? 9;
    return ga - gb || String(a.year).localeCompare(String(b.year));
  });
  return (
    <div className="cross-success">
      <p className="cross-head">
        <HorseLink name={cross.name} /> <span className="cross-status">[{cross.status}]</span>
        {cross.similarity != null ? <span className="cross-sim"> {cross.similarity}% similar</span> : null}
        {cross.sire ? <> ({sex ? `${sex} ` : ""}BY <HorseLink name={cross.sire} />)</> : null}
        {cross.dam ? <> OUT OF THE MARE <HorseLink name={cross.dam} /></> : null}
        {cross.damsire ? <> (M. BY <HorseLink name={cross.damsire} />)</> : null}
      </p>
      {wins.length ? (
        <ul className="cross-wins">
          {wins.map((w, i) => (
            <li key={`${w.race}-${w.year}-${i}`}>
              {[w.grade, horseCaps(w.race)].filter(Boolean).join(" ")}
              {w.year ? <span className="cross-year"> · {w.year}</span> : null}
            </li>
          ))}
        </ul>
      ) : cross.prose ? (
        <p className="cross-prose">{cross.prose}</p>
      ) : null}
    </div>
  );
}

function HypomatingInner() {
  const params = useSearchParams();
  const sireFromPage = params.get("sire") || "";
  const [mare, setMare] = useState(sireFromPage ? "" : (params.get("mare") || ""));
  const [surface, setSurface] = useState("neither");
  const [minFee, setMinFee] = useState("");
  const [maxFee, setMaxFee] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [openLogic, setOpenLogic] = useState(null);
  const [openLineage, setOpenLineage] = useState(null);
  const [lineageData, setLineageData] = useState(null);
  const [lineageLoading, setLineageLoading] = useState(false);
  const [report, setReport] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [sireCrosses, setSireCrosses] = useState(null);
  const [yearChoices, setYearChoices] = useState(null);
  const [restored, setRestored] = useState(false);

  useEffect(() => {
    if (sireFromPage || restored) return;
    const saved = loadHypomatingSession();
    if (saved?.result) {
      setMare(saved.mare || "");
      setSurface(saved.surface || "neither");
      setMinFee(saved.minFee || "");
      setMaxFee(saved.maxFee || "");
      setResult(saved.result);
      setOpenLineage(saved.openLineage || null);
      setLineageData(saved.lineage || null);
      setReport(saved.report || null);
    }
    setRestored(true);
  }, [sireFromPage, restored]);

  useEffect(() => {
    if (!sireFromPage) {
      setSireCrosses(null);
      return;
    }
    setLoading(true);
    setError("");
    setResult(null);
    apiGet(`/api/hypomating/crosses/${encodeURIComponent(sireFromPage)}?limit=30`)
      .then(setSireCrosses)
      .catch((e) => {
        setError(e.message);
        setSireCrosses(null);
      })
      .finally(() => setLoading(false));
  }, [sireFromPage]);

  async function run(ev) {
    ev?.preventDefault();
    setLoading(true);
    setError("");
    setReport(null);
    setSireCrosses(null);
    setYearChoices(null);
    try {
      const data = await apiPost("/api/hypomating/suggest", {
        mare,
        surface,
        min_fee: minFee ? Number(minFee) : null,
        max_fee: maxFee ? Number(maxFee) : null,
      });
      setResult(data);
      saveHypomatingSession({ mare, surface, minFee, maxFee, result: data });
    } catch (e) {
      if (e.status === 409 && e.detail?.error === "ambiguous_year") {
        setYearChoices(e.detail);
        setError("");
      } else {
        setError(e.message);
      }
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  async function toggleLineage(name) {
    if (openLineage === name) {
      setOpenLineage(null);
      return;
    }
    setOpenLineage(name);
    setLineageLoading(true);
    setError("");
    try {
      const data = await apiGet(
        `/api/hypomating/lineage/${encodeURIComponent(name)}${maxFee ? `?max_fee=${maxFee}` : ""}`,
      );
      setLineageData(data);
      saveHypomatingSession({
        mare, surface, minFee, maxFee, result, report,
        lineage: data, openLineage: name,
      });
    } catch (e) {
      setError(e.message);
      setLineageData(null);
    } finally {
      setLineageLoading(false);
    }
  }

  async function makeReport(sire) {
    if (!result?.mare) return;
    setReportLoading(true);
    setError("");
    try {
      const data = await apiPost("/api/hypomating/report", { sire, dam: result.mare });
      setReport(data);
      saveHypofoal({ foal_name: data.foal_name, sire, dam: data.dam });
      saveHypomatingSession({
        mare, surface, minFee, maxFee, result, lineage: lineageData, openLineage, report: data,
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setReportLoading(false);
    }
  }

  const brood = result?.broodmare;
  // Lineage groups already shown on a suggestion card open there; only list the rest separately.
  const suggestionNames = new Set((result?.suggestions || []).map((s) => s.name));
  const suggestionKeys = new Set([...suggestionNames].map((n) => String(n).toUpperCase()));
  // Alternatives skip stallions already suggested above.
  const lineageOptions = (lineageData?.options || []).filter(
    (o) => o.rank != null
      && String(o.rank).toUpperCase() !== "N/A"
      && !suggestionKeys.has(String(o.name).toUpperCase()),
  );
  const extraLineageGroups = (result?.lineage_groups || []).filter((g) => !suggestionNames.has(g.anchor));

  if (sireFromPage) {
    return (
      <div>
        <div className="panel">
          <h2>TOP BROODMARE SIRE CROSSES</h2>
          <p className="sub">
            DAUGHTERS OF THESE BROODMARE SIRES HAVE PRODUCED STAKES WINNERS WHEN CROSSED WITH{" "}
            <Link href={horseHref(sireFromPage)}>{horseCaps(sireFromPage)}</Link>.
          </p>
          {loading ? <p className="empty">Loading proven nicks…</p> : null}
          {error ? <p className="error">{error}</p> : null}
          {!loading && sireCrosses && !(sireCrosses.crosses || []).length ? (
            <p className="empty">No stakes-winning crosses on file for this stallion yet.</p>
          ) : null}
          {(sireCrosses?.crosses || []).map((c, idx) => (
            <div key={c.broodmare_sire} className="suggest-card">
              <div>
                <strong>
                  {idx + 1}. <Link href={horseHref(c.broodmare_sire)}>{horseCaps(c.broodmare_sire)}</Link>
                </strong>
                <div className="parents">
                  BROODMARE SIRE RANK: {c.rank ? `#${c.rank}` : "UNRANKED"} · {c.winners?.length || 0} STAKES WINNER{(c.winners?.length || 0) === 1 ? "" : "S"}
                </div>
                <div className="logic">
                  {(c.winners || []).map((w) => (
                    <p key={w.name}>
                      <Link href={horseHref(w.name)}>{horseCaps(w.name)}</Link>
                      {" "}({horseCaps(w.status)})
                      {w.dam ? <> · OUT OF {horseCaps(w.dam)}, A DAUGHTER OF {horseCaps(c.broodmare_sire)}</> : null}
                    </p>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (report || reportLoading) {
    return (
      <HypofoalDetail
        report={report}
        loading={reportLoading}
        error={error}
        onBack={() => {
          setReport(null);
          saveHypomatingSession({
            mare, surface, minFee, maxFee, result, lineage: lineageData, openLineage, report: null,
          });
        }}
      />
    );
  }

  return (
    <div>
      {!result ? (
        <form className="wizard" onSubmit={run}>
          <h2>HYPOMATING</h2>
          <div className="field">
            <label>ENTER YOUR BROODMARE NAME</label>
            <input value={mare} onChange={(e) => setMare(e.target.value)} required />
          </div>
          <div className="field">
            <label>WHAT IS YOUR PRICE RANGE?</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <input value={minFee} onChange={(e) => setMinFee(e.target.value)} placeholder="Min stud fee" />
              <input value={maxFee} onChange={(e) => setMaxFee(e.target.value)} placeholder="Max stud fee" />
            </div>
          </div>
          <div className="field">
            <label>DESIRED SURFACE</label>
            <div className="surfaces">
              {["dirt", "turf", "neither"].map((s) => (
                <label key={s}>
                  <input type="radio" name="surface" checked={surface === s} onChange={() => setSurface(s)} />
                  {horseCaps(s)}
                </label>
              ))}
            </div>
          </div>
          {yearChoices ? (
            <div className="field">
              <p className="sub">MULTIPLE HORSES NAMED {horseCaps(yearChoices.name)} ARE IN THE PEDIGREE DATABASE. WHICH FOALING YEAR DO YOU WANT?</p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {(yearChoices.years || []).map((year) => (
                  <button
                    key={year}
                    type="button"
                    className="primary"
                    onClick={() => {
                      setMare(`${yearChoices.name} (${year})`);
                      setYearChoices(null);
                    }}
                  >
                    {horseCaps(yearChoices.name)} ({year})
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {error ? <p className="error">{error}</p> : null}
          <button className="primary" disabled={loading}>{loading ? "SEARCHING CROSSES…" : "FIND STALLIONS"}</button>
        </form>
      ) : (
        <div>
          <button
            className="ghost"
            onClick={() => {
              clearHypomatingSession();
              setResult(null);
              setOpenLineage(null);
              setLineageData(null);
              setReport(null);
            }}
          >
            ← NEW SEARCH
          </button>
          <div className="hypo-results">
            <div className="panel">
              <h4>BROODMARE · {horseCaps(result.mare)}</h4>
              {result.damsire ? <p className="sub">DAMSIRE: {horseCaps(result.damsire)}</p> : null}
              <PedigreeChart tree={brood?.pedigree} showSubject={false} />
              <div className="family-panel" style={{ marginTop: 12 }}>
                <h4>FEMALE FAMILY</h4>
                <FemaleFamily family={brood?.female_family || []} />
              </div>
            </div>
            <div>
              <div className="panel">
                <h4>SUGGESTED STALLIONS</h4>
                {(result.suggestions || []).length === 0 ? (
                  <p className="empty">No stallions in this fee band. Check the alternatives below.</p>
                ) : null}
                {(result.suggestions || []).map((s) => (
                  <div key={s.name} className="suggest-card suggest-card-stack">
                    <div className="suggest-card-main">
                      <div>
                        <strong>
                          <Link href={horseHref(s.name)}>{horseCaps(s.name)}</Link>
                        </strong>
                        <div className="parents">RANK #{s.rank} · {horseCaps(s.stud_fee)}</div>
                      </div>
                      <div className="suggest-actions">
                        <Link
                          className="ghost suggest-profile"
                          href={horseHref(s.name)}
                          onClick={() => {
                            saveHypomatingSession({
                              mare, surface, minFee, maxFee, result,
                              lineage: lineageData, openLineage, report,
                            });
                            recordAppView("/hypomating", "Hypomating");
                          }}
                        >
                          SEE PROFILE
                        </Link>
                        <button className="ghost" onClick={() => setOpenLogic(openLogic === s.name ? null : s.name)}>LOGIC</button>
                        <button className="primary" onClick={() => makeReport(s.name)}>CREATE HYPOFOAL</button>
                      </div>
                    </div>
                    {openLogic === s.name ? (
                      <div className="logic logic-wide">
                        {[...(s.cross_meta || []).map((m) => ({
                          name: m.foal_name,
                          status: m.status,
                          sex: m.sex,
                          sire: m.sire || m.actual_sire_name,
                          dam: m.dam,
                          damsire: m.damsire,
                          wins: m.wins,
                          similarity: m.similarity,
                          prose: m.wins ? null : m.races_sentence,
                        })), ...sortCrosses(s.crosses || [])].map((c) => (
                          <CrossSuccess key={`${c.name}-${c.status}`} cross={c} />
                        ))}
                        {Object.entries(s.reasons_by_tier || {}).flatMap(([tier, msgs]) =>
                          msgs
                            // Cross successes are listed above in structured form.
                            .filter((msg) => !(s.crosses || []).length || !msg.startsWith("Cross Success"))
                            .map((msg) => {
                              const linkNames = [
                                s.name,
                                result.mare,
                                result.damsire,
                                ...(s.cross_meta || []).map((m) => m.foal_name),
                                ...(brood?.progeny || []).map((p) => p.name),
                              ].filter(Boolean);
                              return (
                                <p key={msg}>
                                  {horseCaps(tier)}: <HorseText text={msg} names={linkNames} />
                                </p>
                              );
                            })
                        )}
                      </div>
                    ) : null}
                    {s.has_lineage ? (
                      <div className="suggest-alts">
                        <button className="ghost alts-btn" type="button" onClick={() => toggleLineage(s.name)}>
                          <span>ALTERNATIVES</span>
                          <span className="alts-toggle">{openLineage === s.name ? "CLOSE" : "OPEN"}</span>
                        </button>
                        {openLineage === s.name ? (
                          <div className="lineage-inline">
                            <h4>ALTERNATIVES</h4>
                            {lineageLoading ? <p className="empty">Loading lineage…</p> : null}
                            {!lineageLoading && !lineageOptions.length ? (
                              <p className="empty">No ranked lineage options in this fee band.</p>
                            ) : null}
                            {lineageOptions.map((o) => (
                              <div key={o.name} className="suggest-card">
                                <div>
                                  <Link href={horseHref(o.name)}>{horseCaps(o.name)}</Link>
                                  <div className="parents">RANK #{o.rank} · {horseCaps(o.stud_fee)}</div>
                                </div>
                                <div className="suggest-actions">
                                  <Link className="ghost" href={horseHref(o.name)}>SEE PROFILE</Link>
                                  <button className="primary" type="button" onClick={() => makeReport(o.name)}>
                                    CREATE HYPOFOAL
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
              {extraLineageGroups.length ? (
                <div className="panel" style={{ marginTop: 12 }}>
                  <h4>ALTERNATIVES</h4>
                  {extraLineageGroups.map((g) => (
                    <div key={g.anchor} className="suggest-card suggest-card-stack">
                      <div className="suggest-card-main">
                        <div>
                          <strong>{horseCaps(g.anchor)}</strong>
                          <div className="parents">{g.variant ? "PROVEN CROSS · NOT STANDING" : "RELATED SIRES IN BUDGET"}</div>
                        </div>
                        <button className="ghost alts-btn" type="button" onClick={() => toggleLineage(g.anchor)}>
                          <span>ALTERNATIVES</span>
                          <span className="alts-toggle">{openLineage === g.anchor ? "CLOSE" : "OPEN"}</span>
                        </button>
                      </div>
                      {openLineage === g.anchor ? (
                        <div className="lineage-inline">
                          <h4>ALTERNATIVES</h4>
                          {lineageLoading ? <p className="empty">Loading lineage…</p> : null}
                          {!lineageLoading && !lineageOptions.length ? (
                            <p className="empty">No ranked lineage options in this fee band.</p>
                          ) : null}
                          {lineageOptions.map((o) => (
                            <div key={o.name} className="suggest-card">
                              <div>
                                <Link href={horseHref(o.name)}>{horseCaps(o.name)}</Link>
                                <div className="parents">RANK #{o.rank} · {horseCaps(o.stud_fee)}</div>
                              </div>
                              <div className="suggest-actions">
                                <Link className="ghost" href={horseHref(o.name)}>SEE PROFILE</Link>
                                <button className="primary" type="button" onClick={() => makeReport(o.name)}>
                                  CREATE HYPOFOAL
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
              {error ? <p className="error">{error}</p> : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function HypomatingPage() {
  return (
    <Suspense fallback={<p className="empty">Loading hypomating…</p>}>
      <HypomatingInner />
    </Suspense>
  );
}
