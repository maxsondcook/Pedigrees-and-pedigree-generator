"use client";

import Link from "next/link";
import { horseHref } from "../lib/api";

/** Linkify known horse names inside free-form logic / bio copy. */
export default function HorseText({ text, names = [], hrefFor = null }) {
  const raw = text == null ? "" : String(text);
  if (!raw) return null;

  const unique = [];
  const seen = new Set();
  for (const name of names) {
    const n = (name || "").trim();
    if (!n) continue;
    const key = n.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(n);
  }
  unique.sort((a, b) => b.length - a.length);

  if (!unique.length) return <>{raw}</>;

  const escaped = unique.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const re = new RegExp(`(${escaped.join("|")})`, "gi");
  const parts = raw.split(re);
  const link = (label) => (hrefFor ? hrefFor(label) : horseHref(label));

  return (
    <>
      {parts.map((part, i) => {
        const match = unique.find((n) => n.toLowerCase() === part.toLowerCase());
        if (!match) return <span key={i}>{part}</span>;
        return (
          <Link key={i} href={link(match)} className="horse-inline-link">
            {part}
          </Link>
        );
      })}
    </>
  );
}
