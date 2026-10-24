"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { horseHref } from "../../lib/api";
import { loadBarn } from "../../lib/barn";
import { loadUser } from "../../lib/auth";

export default function BarnPage() {
  const [barn, setBarn] = useState({ starred: [], hypofoals: [], favorites: [], analyzed: [] });
  const [user, setUser] = useState(null);
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

  return (
    <div className="barn-grid">
      <div className="panel wide">
        <h4>ACCOUNT</h4>
        {user ? (
          <p>Signed in as <strong>{user.username}</strong> · {user.email}. Barn preferences are saved to this account.</p>
        ) : (
          <p className="empty" style={{ padding: 0 }}>
            You are browsing as a guest. <Link href="/signin">Create an account</Link> to save starred stallions and hypofoals.
          </p>
        )}
      </div>
      <div className="panel">
        <h4>STARRED STALLIONS</h4>
        {barn.starred.length ? barn.starred.map((n) => (
          <div key={n} className="suggest-card"><Link href={horseHref(n)}>{n}</Link></div>
        )) : <p className="empty">Star stallions from the directory or a profile.</p>}
      </div>
      <div className="panel">
        <h4>HYPOFOALS</h4>
        {barn.hypofoals.map((h) => (
          <div key={h.foal_name} className="suggest-card">
            <div>{h.sire} × {h.dam}</div>
          </div>
        ))}
      </div>
      <div className="panel">
        <h4>MY HORSES / FAVORITES</h4>
        {barn.favorites.map((n) => (
          <div key={n} className="suggest-card"><Link href={horseHref(n)}>{n}</Link></div>
        ))}
      </div>
      <div className="panel">
        <h4>MY ANALYZED SALES</h4>
        {barn.analyzed.map((a) => (
          <div key={a.id} className="suggest-card">
            <div>{a.name}<div className="parents">{a.sale}</div></div>
          </div>
        ))}
      </div>
    </div>
  );
}
