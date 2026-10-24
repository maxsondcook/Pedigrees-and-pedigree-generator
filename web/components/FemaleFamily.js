"use client";

import Link from "next/link";
import { horseHref } from "../lib/api";

/** Stakes-win (or better) codes from the graded/group winners index. */
const BLACK_TYPE_STATUS = new Set(["MG1W", "G1W", "MGSW", "G2W", "G3W", "MSW", "SW"]);

function isBlackTypeWinner(p) {
  return Boolean(p?.status && BLACK_TYPE_STATUS.has(String(p.status).toUpperCase()));
}

function FoalLine({ p, hrefFor }) {
  const sexBit = p.sex ? `${p.sex}. ` : "";
  const blackType = isBlackTypeWinner(p);
  // Uppercase stakes winners (and the subject when they qualify as black-type).
  const displayName = blackType || p.status ? (p.name || "").toUpperCase() : p.name;
  const link = (label) => (hrefFor ? hrefFor(label) : horseHref(label));
  // "Black-type winner, above." only for the profile subject when they have a stakes-win status.
  const trailer = p.is_subject && blackType
    ? ". Black-type winner, above."
    : p.status
      ? `. ${p.status}.`
      : ".";
  return (
    <div className={`ff-foal${p.is_subject ? " subject" : ""}${blackType ? " stakes" : ""}`}>
      <Link href={link(p.name)}>{displayName}</Link>
      {p.year ? <span className="yr"> ({p.year})</span> : null}
      {p.sire ? <> ({sexBit}by <Link href={link(p.sire)}>{p.sire}</Link>)</> : null}
      {trailer}
      {(p.races || []).length ? ` ${(p.races).join(", ")}.` : null}
      {(p.produce || []).map((g) => (
        <div className="ff-grand" key={`${g.name}-${g.sire}`}>
          Dam of <Link href={link(g.name)}>{g.status ? g.name.toUpperCase() : g.name}</Link>
          {g.sire ? <> ({g.sex ? `${g.sex}. ` : ""}by <Link href={link(g.sire)}>{g.sire}</Link>)</> : null}
          {g.status ? `. ${g.status}.` : "."}
          {(g.races || []).length ? ` ${g.races.join(", ")}.` : null}
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
      <div className="ff-ord">{d.ordinal}</div>
      <div className="ff-head">
        <Link href={link(d.name)}>{(d.name || "").toUpperCase()}</Link>
        {d.year ? ` (${d.year})` : ""}
        {d.sire ? <>, by <Link href={link(d.sire)}>{d.sire}</Link>.</> : "."}
        {d.status ? ` ${d.status}.` : ""}
      </div>
      <div className="ff-racing">
        {(d.racing || []).length ? d.racing.join("; ") : "Racing record not on file."}
      </div>
      <div className="ff-prod-label">Produce</div>
      {(d.produce || []).length === 0 ? (
        <p className="empty">No produce on file yet.</p>
      ) : (
        d.produce.map((p) => <FoalLine key={`${p.name}-${p.sire}`} p={p} hrefFor={hrefFor} />)
      )}
    </div>
  ));
}
