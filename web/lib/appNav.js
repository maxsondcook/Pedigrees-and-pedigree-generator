"use client";

import {
  horseHrefWithReturn,
  parseSalesReturn,
  rememberSalesVisit,
  salesHref,
} from "./salesNav";

const VIEW_KEY = "crossr-app-nav-v1";
const HYPO_KEY = "crossr-hypomating-session-v1";

function readView() {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(VIEW_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.href) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeView(next) {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(VIEW_KEY, JSON.stringify(next));
  } catch {
    /* ignore quota */
  }
}

function kindFromHref(href) {
  const path = String(href || "").split("?")[0];
  if (path.startsWith("/sales")) return "sales";
  if (path.startsWith("/hypomating")) return "hypomating";
  if (path.startsWith("/stallions")) return "stallions";
  if (path.startsWith("/barn")) return "barn";
  if (path.startsWith("/compare")) return "compare";
  return "path";
}

function defaultLabel(kind, href) {
  if (kind === "sales") return "Sales";
  if (kind === "hypomating") return "Hypomating";
  if (kind === "stallions") return "Stallions";
  if (kind === "barn") return "My Barn";
  if (kind === "compare") return "Compare";
  if (href && href !== "/") return href.replace(/^\//, "").split("?")[0];
  return "previous page";
}

/** Record the last non-profile in-app view for Go Back. */
export function recordAppView(href, label) {
  if (!href || typeof window === "undefined") return;
  const path = String(href).split("?")[0];
  if (!path || path === "/" || path === "/signin" || path.startsWith("/horses")) return;
  const kind = kindFromHref(href);
  const prev = readView();
  // Keep a richer sales/hypomating label if the path is the same and label is weaker.
  const nextLabel = label || prev?.label || defaultLabel(kind, href);
  writeView({
    href: String(href),
    label: String(nextLabel),
    kind,
    at: Date.now(),
  });
}

export function salesReturnLabel(sales) {
  if (!sales) return "Sales";
  const title = sales.catalogTitle || "Sale";
  const hip = sales.hip || sales.hipKey;
  return hip ? `${title} · Hip #${hip}` : title;
}

/**
 * Resolve where a profile Go Back should land.
 * Prefer explicit sales return query params, then the recorded in-app view.
 */
export function resolveReturnTarget(searchParams) {
  const sales = parseSalesReturn(searchParams);
  if (sales) {
    return {
      kind: "sales",
      href: salesHref(sales),
      label: salesReturnLabel(sales),
      sales,
    };
  }
  const stored = readView();
  if (stored?.href) {
    return {
      kind: stored.kind || kindFromHref(stored.href),
      href: stored.href,
      label: stored.label || defaultLabel(stored.kind, stored.href),
      sales: null,
    };
  }
  return {
    kind: "fallback",
    href: "/stallions",
    label: "Stallions",
    sales: null,
  };
}

export function saveHypomatingSession(payload) {
  if (typeof window === "undefined" || !payload) return;
  try {
    sessionStorage.setItem(HYPO_KEY, JSON.stringify({ ...payload, at: Date.now() }));
  } catch {
    /* ignore */
  }
  recordAppView("/hypomating", "Hypomating");
}

export function loadHypomatingSession() {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(HYPO_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function clearHypomatingSession() {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.removeItem(HYPO_KEY);
  } catch {
    /* ignore */
  }
}

export {
  horseHrefWithReturn,
  parseSalesReturn,
  rememberSalesVisit,
  salesHref,
};
