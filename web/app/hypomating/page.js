"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { apiGet, apiPost, horseHref } from "../../lib/api";
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
  const [lineage, setLineage] = useState(null);
  const [report, setReport] = useState(null);
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
      setLineage(saved.lineage || null);
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

  async function loadLineage(name) {
    const data = await apiGet(`/api/hypomating/lineage/${encodeURIComponent(name)}${maxFee ? `?max_fee=${maxFee}` : ""}`);
    setLineage(data);
  }

  async function makeReport(sire) {
    const data = await apiPost("/api/hypomating/report", { sire, dam: result.mare });
    setReport(data);
    saveHypofoal({ foal_name: data.foal_name, sire, dam: data.dam });
  }

  const brood = result?.broodmare;

  if (sireFromPage) {
    return (
      <div>
        <div className="panel">
          <h2>TOP BROODMARE SIRE CROSSES</h2>
          <p className="sub">
            Daughters of these broodmare sires have produced stakes winners when crossed with{" "}
            <Link href={horseHref(sireFromPage)}>{sireFromPage}</Link>.
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
                  {idx + 1}. <Link href={horseHref(c.broodmare_sire)}>{c.broodmare_sire}</Link>
                </strong>
                <div className="parents">
                  Broodmare sire rank: {c.rank ? `#${c.rank}` : "Unranked"} · {c.winners?.length || 0} stakes winner{(c.winners?.length || 0) === 1 ? "" : "s"}
                </div>
                <div className="logic">
                  {(c.winners || []).map((w) => (
                    <p key={w.name}>
                      <Link href={horseHref(w.name)}>{w.name}</Link>
                      {" "}({w.status})
                      {w.dam ? <> · out of {w.dam}, a daughter of {c.broodmare_sire}</> : null}
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

  return (
    <div>
      {!result ? (
        <form className="wizard" onSubmit={run}>
          <h2>HYPOMATING</h2>
          <div className="field">
            <label>Enter your broodmare name</label>
            <input value={mare} onChange={(e) => setMare(e.target.value)} required />
          </div>
          <div className="field">
            <label>What is your price range?</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <input value={minFee} onChange={(e) => setMinFee(e.target.value)} placeholder="Min stud fee" />
              <input value={maxFee} onChange={(e) => setMaxFee(e.target.value)} placeholder="Max stud fee" />
            </div>
          </div>
          <div className="field">
            <label>Desired surface</label>
            <div className="surfaces">
              {["dirt", "turf", "neither"].map((s) => (
                <label key={s}>
                  <input type="radio" name="surface" checked={surface === s} onChange={() => setSurface(s)} />
                  {s[0].toUpperCase() + s.slice(1)}
                </label>
              ))}
            </div>
          </div>
          {yearChoices ? (
            <div className="field">
              <p className="sub">Multiple horses named {yearChoices.name} are in the pedigree database. Which foaling year do you want?</p>
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
                    {yearChoices.name} ({year})
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {error ? <p className="error">{error}</p> : null}
          <button className="primary" disabled={loading}>{loading ? "Searching crosses…" : "Find stallions"}</button>
        </form>
      ) : (
        <div>
          <button
            className="ghost"
            onClick={() => {
              clearHypomatingSession();
              setResult(null);
              setLineage(null);
              setReport(null);
            }}
          >
            ← New search
          </button>
          <div className="dash" style={{ marginTop: 12, gridTemplateColumns: "minmax(720px, 1.55fr) minmax(360px, 1fr)" }}>
            <div className="panel">
              <h4>BROODMARE · {result.mare}</h4>
              {result.damsire ? <p className="sub">Damsire: {result.damsire}</p> : null}
              <PedigreeChart tree={brood?.pedigree} />
              <h4 style={{ marginTop: 12 }}>Race record</h4>
              {(brood?.own?.races || []).length ? (
                <ul>{brood.own.races.map((r) => <li key={r}>{r}</li>)}</ul>
              ) : (
                <p className="empty">No graded stakes record on file for this mare.</p>
              )}
              <h4>Progeny</h4>
              {(brood?.progeny || []).map((p) => (
                <div key={p.name} className="suggest-card">
                  <div>
                    <Link href={horseHref(p.name)}>{p.name}</Link>
                    <div className="parents">by {p.sire} · {p.class || p.status}</div>
                  </div>
                </div>
              ))}
              <div className="family-panel" style={{ marginTop: 12 }}>
                <h4>FEMALE FAMILY</h4>
                <FemaleFamily family={brood?.female_family || []} />
              </div>
            </div>
            <div>
              <div className="panel">
                <h4>SUGGESTED STALLIONS</h4>
                {(result.suggestions || []).length === 0 ? (
                  <p className="empty">No stallions in this fee band. Check lineage alternatives below.</p>
                ) : null}
                {(result.suggestions || []).map((s) => (
                  <div key={s.name} className="suggest-card suggest-card-stack">
                    <div className="suggest-card-main">
                      <div>
                        <strong>{s.name}</strong>
                        <div className="parents">Rank #{s.rank} · {s.stud_fee}</div>
                        {openLogic === s.name ? (
                          <div className="logic">
                            {(s.cross_meta || []).map((m) => {
                              const linkNames = [
                                m.foal_name,
                                m.actual_sire_name,
                                result.mare,
                                result.damsire,
                                ...(brood?.progeny || []).map((p) => p.name),
                              ].filter(Boolean);
                              return (
                                <p key={m.foal_name}>
                                  <HorseText text={m.races_sentence} names={linkNames} />
                                  <br />
                                  <HorseText text={m.bio_sentence} names={linkNames} />
                                </p>
                              );
                            })}
                            {Object.entries(s.reasons_by_tier || {}).flatMap(([tier, msgs]) =>
                              msgs.map((msg) => {
                                const linkNames = [
                                  s.name,
                                  result.mare,
                                  result.damsire,
                                  ...(s.cross_meta || []).map((m) => m.foal_name),
                                  ...(brood?.progeny || []).map((p) => p.name),
                                ].filter(Boolean);
                                return (
                                  <p key={msg}>
                                    {tier}: <HorseText text={msg} names={linkNames} />
                                  </p>
                                );
                              })
                            )}
                          </div>
                        ) : null}
                      </div>
                      <div className="suggest-actions">
                        <Link
                          className="ghost suggest-profile"
                          href={horseHref(s.name)}
                          onClick={() => {
                            saveHypomatingSession({
                              mare, surface, minFee, maxFee, result, lineage, report,
                            });
                            recordAppView("/hypomating", "Hypomating");
                          }}
                        >
                          Profile
                        </Link>
                        <button className="ghost" onClick={() => setOpenLogic(openLogic === s.name ? null : s.name)}>Logic</button>
                        <button className="primary" onClick={() => makeReport(s.name)}>Create hypofoal</button>
                      </div>
                    </div>
                    {s.has_lineage ? (
                      <div className="suggest-alts">
                        <span className="meta-label">Alternatives</span>
                        <button className="ghost" type="button" onClick={() => loadLineage(s.name)}>
                          Lineage options of {s.name}
                        </button>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
              {(result.lineage_groups || []).length ? (
                <div className="panel" style={{ marginTop: 12 }}>
                  <h4>ALTERNATIVES</h4>
                  {(result.lineage_groups || []).map((g) => (
                    <div key={g.anchor} className="suggest-card">
                      <div>
                        <strong>Lineage alternatives of {g.anchor}</strong>
                        <div className="parents">{g.variant ? "Cross variant" : "Related sires in budget"}</div>
                      </div>
                      <button className="ghost" onClick={() => loadLineage(g.anchor)}>Open</button>
                    </div>
                  ))}
                </div>
              ) : null}
              {lineage ? (
                <div className="panel" style={{ marginTop: 12 }}>
                  <h4>LINEAGE OPTIONS · {lineage.stallion}</h4>
                  {lineage.options.map((o) => (
                    <div key={o.name} className="suggest-card">
                      <div>{o.name} · #{o.rank} · {o.stud_fee}</div>
                      <button className="primary" onClick={() => makeReport(o.name)}>Use</button>
                    </div>
                  ))}
                </div>
              ) : null}
              {report ? (
                <div className="panel" style={{ marginTop: 12 }}>
                  <h4>SAVE HYPOFOAL · {report.foal_name}</h4>
                  <PedigreeChart tree={report.pedigree} />
                  <p>Inbreeding coefficient: {report.inbreeding?.coefficient_pct}%</p>
                </div>
              ) : null}
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
