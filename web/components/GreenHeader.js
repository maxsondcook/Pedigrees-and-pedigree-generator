"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { loadUser, signOutAccount } from "../lib/auth";

const LINKS = [
  { href: "/stallions", label: "STALLIONS" },
  { href: "/hypomating", label: "HYPOMATING" },
  { href: "/sales", label: "SALES" },
  { href: "/barn", label: "MY BARN", barn: true },
];

export default function GreenHeader({ compact = false }) {
  const path = usePathname();
  const [user, setUser] = useState(null);

  useEffect(() => {
    const sync = () => setUser(loadUser());
    sync();
    window.addEventListener("crossr-auth", sync);
    return () => window.removeEventListener("crossr-auth", sync);
  }, []);

  return (
    <header className={`home-header${compact ? " compact" : ""}`}>
      <Link href="/" className="home-brand" aria-label="Crossr home">
        <img className="home-brand-mark" src="/crossr-stallion-mark-orange.png" alt="" />
        <span className="home-wordmark">CROSSR</span>
      </Link>
      <nav className="home-nav">
        {LINKS.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={`${l.barn ? "barn" : ""}${path.startsWith(l.href) ? " active" : ""}`}
          >
            {l.label}
          </Link>
        ))}
        {user ? (
          <>
            <Link href="/barn" className="account-link">{user.username}</Link>
            <button className="home-signout" onClick={() => signOutAccount()}>Sign out</button>
          </>
        ) : (
          <Link href="/signin" className={`account-link${path === "/signin" ? " active" : ""}`}>
            SIGN IN
          </Link>
        )}
      </nav>
    </header>
  );
}
