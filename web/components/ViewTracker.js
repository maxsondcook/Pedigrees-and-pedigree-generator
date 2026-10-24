"use client";

import { Suspense, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { recordAppView } from "../lib/appNav";

function ViewTrackerInner() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!pathname || pathname.startsWith("/horses")) return;
    if (pathname === "/" || pathname === "/signin") return;
    const qs = searchParams?.toString?.() || "";
    const href = qs ? `${pathname}?${qs}` : pathname;
    let label = "";
    if (pathname.startsWith("/sales")) {
      const title = searchParams.get("title") || "";
      const hip = searchParams.get("hip") || searchParams.get("lot") || "";
      label = title && hip ? `${title} · Hip #${hip}` : title || "Sales";
    } else if (pathname.startsWith("/hypomating")) {
      label = "Hypomating";
    } else if (pathname.startsWith("/stallions")) {
      label = "Stallions";
    } else if (pathname.startsWith("/barn")) {
      label = "My Barn";
    } else if (pathname.startsWith("/compare")) {
      label = "Compare";
    }
    recordAppView(href, label);
  }, [pathname, searchParams]);

  return null;
}

export default function ViewTracker() {
  return (
    <Suspense fallback={null}>
      <ViewTrackerInner />
    </Suspense>
  );
}
