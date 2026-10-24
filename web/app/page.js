"use client";

import Link from "next/link";

const FEATURES = [
  {
    href: "/stallions",
    title: "Stallions",
    body: "Stud fees, sire rankings, mares bred and top progeny for every stallion on the roster.",
    cta: "Browse stallions",
  },
  {
    href: "/hypomating",
    title: "Hypomating",
    body: "Enter a broodmare to see suggested stallions, the logic behind each cross, and a hypothetical foal report.",
    cta: "Plan a mating",
  },
  {
    href: "/sales",
    title: "Sales",
    body: "Work through sale catalogs hip by hip with pedigrees, female families and projected values.",
    cta: "Open the catalogs",
  },
];

export default function Home() {
  return (
    <main className="landing">
      <section className="landing-hero">
        <div className="landing-copy">
          <span className="landing-eyebrow">Thoroughbred pedigree &amp; sales intelligence</span>
          <h1>Buy or breed the next superstar</h1>
          <p className="landing-lead">
            Crossr brings stallion records, mating analysis and sale catalogs into one workspace,
            so you can judge a cross or a yearling on the evidence.
          </p>
          <div className="landing-cta">
            <Link className="primary" href="/stallions">Browse stallions</Link>
            <Link className="ghost" href="/hypomating">Plan a mating</Link>
          </div>
          <p className="landing-account">
            New here? <Link href="/signin">Create an account</Link> to save horses to your barn.
          </p>
        </div>
        <div className="landing-art" aria-hidden="true">
          <img src="/crossr-stallion-mark-orange.png" alt="" />
        </div>
      </section>

      <section className="landing-features">
        {FEATURES.map((f) => (
          <Link key={f.href} href={f.href} className="landing-card">
            <h2>{f.title}</h2>
            <p>{f.body}</p>
            <span className="landing-card-cta">{f.cta} →</span>
          </Link>
        ))}
      </section>
    </main>
  );
}
