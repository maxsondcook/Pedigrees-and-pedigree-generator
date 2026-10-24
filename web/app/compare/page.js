"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiGet } from "../../lib/api";
import PedigreeChart from "../../components/PedigreeChart";

function CompareInner() {
  const params = useSearchParams();
  const a = params.get("a") || "";
  const b = params.get("b") || "";
  const [left, setLeft] = useState(null);
  const [right, setRight] = useState(null);
  const [sim, setSim] = useState(null);

  useEffect(() => {
    if (a) apiGet(`/api/horses/${encodeURIComponent(a)}`).then(setLeft).catch(() => setLeft(null));
    if (b) apiGet(`/api/horses/${encodeURIComponent(b)}`).then(setRight).catch(() => setRight(null));
    if (a && b) {
      const qs = new URLSearchParams({ a, b });
      apiGet(`/api/similarity?${qs}`)
        .then(setSim)
        .catch(() => setSim(null));
    } else {
      setSim(null);
    }
  }, [a, b]);

  function col(d) {
    if (!d) return <p className="empty">Loading…</p>;
    const s = d.stallion || {};
    return (
      <div className="panel">
        <h2>{d.name}</h2>
        <p>{s.farm} · {s.stud_fee} · Rank {s.rank || "NA"}</p>
        <p>Foaled {s.year_foaled} · Stud {s.entered_stud}</p>
        <PedigreeChart tree={d.pedigree} />
      </div>
    );
  }

  return (
    <div>
      {a && b ? (
        <div className="panel" style={{ textAlign: "center", marginBottom: 12 }}>
          <h4>PEDIGREE SIMILARITY</h4>
          {sim ? (
            <>
              <b style={{ display: "block", fontSize: 36, color: "var(--green)", marginTop: 6 }}>{sim.percent}%</b>
              {sim.label ? <p className="sub">{sim.label}</p> : null}
            </>
          ) : (
            <p className="empty">Calculating similarity…</p>
          )}
        </div>
      ) : null}
      <div className="dash" style={{ gridTemplateColumns: "1fr 1fr" }}>
        {col(left)}
        {col(right)}
      </div>
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<p className="empty">Loading comparison…</p>}>
      <CompareInner />
    </Suspense>
  );
}
