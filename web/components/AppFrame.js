"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import Nav from "./Nav";
import ViewTracker from "./ViewTracker";
import { refreshAuth } from "../lib/auth";
import { SalesChromeProvider } from "../lib/SalesChrome";

export default function AppFrame({ children }) {
  const path = usePathname();

  useEffect(() => {
    refreshAuth();
  }, []);

  if (path === "/" || path === "/signin") {
    return children;
  }

  const sales = path.startsWith("/sales");

  return (
    <SalesChromeProvider>
      <div className={`shell${sales ? " shell-sales" : ""}`}>
        <ViewTracker />
        <Nav />
        {children}
      </div>
    </SalesChromeProvider>
  );
}
