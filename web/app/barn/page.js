"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiPost, horseHref } from "../../lib/api";
import { horseCaps, matingCaps } from "../../lib/display";
import { loadBarn } from "../../lib/barn";
import { loadUser } from "../../lib/auth";
import HypofoalDetail from "../../components/HypofoalDetail";

export default function BarnPage() {
  const [barn, setBarn] = useState({ starred: [], hypofoals: [], favorites: [], analyzed: [] });
  const [user, setUser] = useState(null);
  const [report, setReport] = useState(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState("");

  useEffect(() => {
    const refresh = () => {
      setBarn(loadBarn());
      setUser(loadUser());
    };
    refresh();
    window.addEventListener("crossr-barn", refresh);
    window.addEventListener("crossr-auth", refresh);
    return () => {
      window.removeEventListener("crossr-barn", refresh);
      window.removeEventListener("crossr-auth", refresh);
    };
  }, []);

  async function openHypofoal(entry) {
    if (!entry?.sire || !entry?.dam) {
      setReportError("Saved hypofoal is missing sire or dam.");
      return;
    }
    setReportLoading(true);
    setReportError("");
    setReport(null);
    try {
      const data = await apiPost("/api/hypomating/report", {
        sire: entry.sire,
        dam: entry.dam,
      });
      setReport(data);
    } catch (e) {
      setReportError(e.message || "Could not load hypofoal.");
    } finally {
      setReportLoading(false);
    }
  }

  if (report || reportLoading || reportError) {
    return (
      <HypofoalDetail
        report={report}
        loading={reportLoading}
        error={reportError}
        onBack={() => {
          setReport(null);
          setReportError("");
        }}
      />
    );
  }

  return (
    <div className="barn-grid">
      <div className="panel wide">
        <h4>ACCOUNT</h4>
        {user ? (
          <p>SIGNED IN AS <strong>{horseCaps(user.username)}</strong> · {user.email}. BARN PREFERENCES ARE SAVED TO THIS ACCOUNT.</p>
        ) : (
          <p className="empty" style={{ padding: 0 }}>
            You are browsing as a guest. <Link href="/signin">Create an account</Link> to save starred stallions and hypofoals.
          </p>
        )}
      </div>
      <div className="panel">
        <h4>STARRED STALLIONS</h4>
        {barn.starred.length ? barn.starred.map((n) => (
          <div key={n} className="suggest-card"><Link href={horseHref(n)}>{horseCaps(n)}</Link></div>
        )) : <p className="empty">Star stallions from the directory or a profile.</p>}
      </div>
      <div className="panel">
        <h4>HYPOFOALS</h4>
        {barn.hypofoals.length === 0 ? (
          <p className="empty">Create a hypofoal from Hypomating to save it here.</p>
        ) : null}
        {barn.hypofoals.map((h) => (
          <button
            key={h.foal_name}
            type="button"
            className="ghost catalog-btn hypofoal-barn-btn"
            onClick={() => openHypofoal(h)}
          >
            {matingCaps(h.sire, h.dam, h.foal_name)}
          </button>
        ))}
      </div>
      <div className="panel">
        <h4>MY HORSES / FAVORITES</h4>
        {barn.favorites.map((n) => (
          <div key={n} className="suggest-card"><Link href={horseHref(n)}>{horseCaps(n)}</Link></div>
        ))}
      </div>
      <div className="panel">
        <h4>MY ANALYZED SALES</h4>
        {barn.analyzed.map((a) => (
          <div key={a.id} className="suggest-card">
            <div>{horseCaps(a.name)}<div className="parents">{horseCaps(a.sale)}</div></div>
          </div>
        ))}
      </div>
    </div>
  );
}
