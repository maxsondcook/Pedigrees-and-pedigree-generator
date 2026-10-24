"use client";

import { useMemo } from "react";
import Link from "next/link";
import { horseHref } from "../lib/api";

const ANCESTOR_GENS = 5;
const LEAF_ROWS = 2 ** ANCESTOR_GENS;
/** Prefer wrapping by ~10ch so multi-word names stack (e.g. GREAT / ABOVE). Cap 18. */
const NAME_WRAP = 10;
const NAME_HARD_MAX = 18;
/** Max column width in ch including 1ch gutters on each side. */
const COL_MAX = 20;
const COL_MIN = 8;

function flatten(node, idx, depth, map) {
  if (!node || depth > ANCESTOR_GENS) return;
  map[idx] = node;
  flatten(node.sire, idx * 2 + 1, depth + 1, map);
  flatten(node.dam, idx * 2 + 2, depth + 1, map);
}

/** Wrap a horse name onto lines (prefer word breaks; soft wrap ~12, hard cap 18). */
export function wrapHorseName(name, max = NAME_WRAP) {
  const raw = String(name || "").trim().toUpperCase();
  if (!raw) return [];
  const limit = Math.min(Math.max(max, 1), NAME_HARD_MAX);
  const words = raw.split(/\s+/);
  const lines = [];
  let cur = "";
  for (const word of words) {
    if (!cur) {
      if (word.length <= limit) {
        cur = word;
      } else {
        for (let i = 0; i < word.length; i += NAME_HARD_MAX) {
          lines.push(word.slice(i, i + NAME_HARD_MAX));
        }
        cur = "";
      }
      continue;
    }
    if (`${cur} ${word}`.length <= limit) {
      cur = `${cur} ${word}`;
    } else {
      lines.push(cur);
      if (word.length <= limit) {
        cur = word;
      } else {
        for (let i = 0; i < word.length; i += NAME_HARD_MAX) {
          lines.push(word.slice(i, i + NAME_HARD_MAX));
        }
        cur = "";
      }
    }
  }
  if (cur) lines.push(cur);
  return lines;
}

function longestLine(name) {
  const lines = wrapHorseName(name);
  return lines.reduce((m, line) => Math.max(m, line.length), 0);
}

function columnChars(names) {
  if (!names.length) return COL_MIN;
  const longest = names.reduce((m, n) => Math.max(m, longestLine(n)), 0);
  // Name block + 1ch padding each side; never exceed COL_MAX / go below COL_MIN.
  return Math.min(COL_MAX, Math.max(COL_MIN, longest + 2));
}

function Cell({ n, className, style, hrefFor }) {
  const href = n?.name ? (hrefFor ? hrefFor(n.name) : horseHref(n.name)) : "";
  const year = n?.year != null && n.year !== "" ? String(n.year) : "";
  const lines = n?.name ? wrapHorseName(n.name) : [];
  return (
    <div className={`cat-cell ${className || ""}`} style={style}>
      {n?.name ? (
        <div className="cat-cell-inner">
          <Link
            className="cat-name"
            href={href}
            title={year ? `${n.name} (${year})` : n.name}
          >
            {lines.map((line, i) => (
              <span key={`${line}-${i}`} className="cat-name-line">
                {line}
              </span>
            ))}
          </Link>
          {year ? <span className="yr">{year}</span> : null}
        </div>
      ) : (
        <div className="cat-cell-inner empty" aria-hidden="true" />
      )}
    </div>
  );
}

export default function PedigreeChart({ tree, showSubject = true, hrefFor = null }) {
  const map = useMemo(() => {
    const m = {};
    flatten(tree, 0, 0, m);
    return m;
  }, [tree]);

  const colWidths = useMemo(() => {
    const widths = [];
    if (showSubject) {
      widths.push(columnChars(tree?.name ? [tree.name] : []));
    }
    for (let gen = 1; gen <= ANCESTOR_GENS; gen += 1) {
      const count = 2 ** gen;
      const start = count - 1;
      const names = [];
      for (let i = 0; i < count; i += 1) {
        const n = map[start + i];
        if (n?.name) names.push(n.name);
      }
      widths.push(columnChars(names));
    }
    return widths;
  }, [map, showSubject, tree]);

  if (!tree) return <div className="empty">No pedigree loaded.</div>;

  const cells = [];
  for (let gen = 1; gen <= ANCESTOR_GENS; gen += 1) {
    const count = 2 ** gen;
    const start = count - 1;
    const span = LEAF_ROWS / count;
    const col = (showSubject ? 1 : 0) + gen;
    for (let i = 0; i < count; i += 1) {
      const idx = start + i;
      const side = i < count / 2 ? "sire" : "dam";
      cells.push(
        <Cell
          key={idx}
          n={map[idx]}
          hrefFor={hrefFor}
          className={`cat-g${gen} ${side}`}
          style={{
            gridColumn: col,
            gridRow: span === 1 ? i + 1 : `${i * span + 1} / span ${span}`,
          }}
        />,
      );
    }
  }

  const subjectHref = tree.name ? (hrefFor ? hrefFor(tree.name) : horseHref(tree.name)) : "";
  const subjectYear = tree.year != null && tree.year !== "" ? String(tree.year) : "";
  const subjectLines = tree.name ? wrapHorseName(tree.name) : [];
  const gridCols = colWidths.map((ch) => `${ch}ch`).join(" ");

  return (
    <div
      className="pedigree-fit"
      style={{
        "--ped-grid-cols": gridCols,
      }}
    >
      <div className={`catalog-ped gen-5${showSubject ? "" : " no-subject"}`}>
        {showSubject ? (
          <div className="cat-subject">
            <Link
              className="cat-name"
              href={subjectHref}
              title={subjectYear ? `${tree.name} (${subjectYear})` : tree.name}
            >
              {subjectLines.map((line, i) => (
                <span key={`${line}-${i}`} className="cat-name-line">
                  {line}
                </span>
              ))}
            </Link>
            {subjectYear ? <span className="yr">{subjectYear}</span> : null}
          </div>
        ) : null}
        {cells}
      </div>
    </div>
  );
}
