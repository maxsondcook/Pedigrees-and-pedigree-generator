"use client";

import Link from "next/link";
import { horseHref } from "../lib/api";
import { horseCaps } from "../lib/display";

/**
 * Black-type winner gate (stakes WIN or better only).
 * Allowlist matches graded/group/listed win codes from the Place==1 stakes index:
 *   MG1W, G1W, MGSW, G2W, G3W, MSW (multi listed/ungraded SW), SW (listed/ungraded SW).
 * Stakes-placed-only horses never receive a win status from the index and must NEVER
 * get the "Black-type winner, above." trailer — that phrase is reserved for the
 * profile subject when isBlackTypeWinner(status) is true.
 */
export const BLACK_TYPE_WIN_STATUS = new Set([
  "MG1W", "G1W", "MGSW", "G2W", "G3W", "MSW", "SW",
]);

export function isBlackTypeWinner(statusOrRow) {
  const status = typeof statusOrRow === "string" || statusOrRow == null
    ? statusOrRow
    : statusOrRow.status;
  return Boolean(status && BLACK_TYPE_WIN_STATUS.has(String(status).toUpperCase()));
}

function FoalLine({ p, hrefFor }) {
  const sexBit = p.sex ? `${horseCaps(p.sex)}. ` : "";
  const blackType = isBlackTypeWinner(p);
  const link = (label) => (hrefFor ? hrefFor(label) : horseHref(label));
  const trailer = p.is_subject && blackType
    ? ". Black-type winner, above."
    : p.status
      ? `. ${horseCaps(p.status)}.`
      : ".";
  return (
    <div className={`ff-foal${p.is_subject ? " subject" : ""}${blackType ? " stakes" : ""}`}>
      <Link href={link(p.name)}>{horseCaps(p.name)}</Link>
      {p.year ? <span className="yr"> ({p.year})</span> : null}
      {p.sire ? <> ({sexBit}BY <Link href={link(p.sire)}>{horseCaps(p.sire)}</Link>)</> : null}
      {trailer}
      {(p.races || []).length ? ` ${horseCaps((p.races).join(", "))}.` : null}
      {(p.produce || [])
        // The same grand-foal can arrive twice from different sources; list it once.
        .filter((g, i, all) => all.findIndex((o) => String(o.name).toUpperCase() === String(g.name).toUpperCase()) === i)
        .map((g) => (
        <div className="ff-grand" key={`${g.name}-${g.sire}`}>
          DAM OF <Link href={link(g.name)}>{horseCaps(g.name)}</Link>
          {g.sire ? <> ({g.sex ? `${horseCaps(g.sex)}. ` : ""}BY <Link href={link(g.sire)}>{horseCaps(g.sire)}</Link>)</> : null}
          {g.status ? `. ${horseCaps(g.status)}.` : "."}
          {(g.races || []).length ? ` ${horseCaps(g.races.join(", "))}.` : null}
        </div>
      ))}
    </div>
  );
}

export default function FemaleFamily({ family, hrefFor = null }) {
  if (!family || family.length === 0) {
    return <p className="empty">No dam line on file for this horse yet.</p>;
  }
  const link = (label) => (hrefFor ? hrefFor(label) : horseHref(label));
  return family.map((d) => (
    <div className="ff-block" key={d.ordinal}>
      <div className="ff-ord">{horseCaps(d.ordinal)}</div>
      <div className="ff-head">
        <Link href={link(d.name)}>{horseCaps(d.name)}</Link>
        {d.year ? ` (${d.year})` : ""}
        {d.sire ? <>, BY <Link href={link(d.sire)}>{horseCaps(d.sire)}</Link>.</> : "."}
        {d.status ? ` ${horseCaps(d.status)}.` : ""}
      </div>
      <div className="ff-racing">
        {(d.racing || []).length ? horseCaps(d.racing.join("; ")) : "RACING RECORD NOT ON FILE."}
      </div>
      <div className="ff-prod-label">PRODUCE</div>
      {(d.produce || []).length === 0 ? (
        <p className="empty">No produce on file yet.</p>
      ) : (
        d.produce.map((p) => <FoalLine key={`${p.name}-${p.sire}`} p={p} hrefFor={hrefFor} />)
      )}
    </div>
  ));
}
