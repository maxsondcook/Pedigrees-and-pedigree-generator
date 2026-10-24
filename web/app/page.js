"use client";

import Link from "next/link";
import GreenHeader from "../components/GreenHeader";

export default function Home() {
  return (
    <div className="home-root">
      <GreenHeader />
      <main className="home-hero">
        <h1 className="home-tag">BUY OR BREED THE NEXT SUPERSTAR</h1>
        <img className="home-horse" src="/logo.png" alt="Crossr horse" />
        <div className="home-cta">
          <Link className="primary" href="/stallions">Browse stallions</Link>
          <Link className="ghost home-ghost" href="/signin">Create an account</Link>
        </div>
      </main>
    </div>
  );
}
