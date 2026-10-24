"use client";

const STORAGE_KEY = "crossr-sales-nav-v1";

export function salesReturnFromParts({ mode, catalogId, catalogTitle, year, hip, lotId } = {}) {
  if (!mode || (!catalogId && catalogId !== 0)) return null;
  const hipKey = mode === "past" ? String(lotId ?? hip ?? "") : String(hip ?? "");
  if (!hipKey) return null;
  return {
    mode: String(mode),
    catalogId: String(catalogId),
    catalogTitle: catalogTitle ? String(catalogTitle) : "",
    year: year != null && year !== "" ? String(year) : "",
    hip: String(hip ?? ""),
    lotId: lotId != null && lotId !== "" ? String(lotId) : "",
    hipKey,
  };
}

export function parseSalesReturn(searchParams) {
  if (!searchParams) return null;
  const get = (key) => {
    if (typeof searchParams.get === "function") return searchParams.get(key) || "";
    return searchParams[key] || "";
  };
  const mode = get("salesMode") || get("mode") || "";
  const catalogId = get("salesCatalog") || get("catalog") || "";
  const hip = get("salesHip") || get("hip") || "";
  const lotId = get("salesLot") || get("lot") || "";
  const year = get("salesYear") || get("year") || "";
  const catalogTitle = get("salesTitle") || "";
  if (!mode || !catalogId) return null;
  if (mode === "past" && !lotId && !hip) return null;
  if (mode !== "past" && !hip) return null;
  return salesReturnFromParts({ mode, catalogId, catalogTitle, year, hip, lotId: lotId || hip });
}

export function salesHref(ret) {
  if (!ret) return "/sales";
  const params = new URLSearchParams();
  params.set("mode", ret.mode);
  params.set("catalog", ret.catalogId);
  if (ret.year) params.set("year", ret.year);
  if (ret.mode === "past") {
    params.set("lot", ret.lotId || ret.hipKey);
  } else {
    params.set("hip", ret.hip || ret.hipKey);
  }
  if (ret.catalogTitle) params.set("title", ret.catalogTitle);
  return `/sales?${params.toString()}`;
}

export function withSalesReturn(href, ret) {
  if (!ret || !href) return href;
  const url = new URL(href, "http://local.invalid");
  url.searchParams.set("salesMode", ret.mode);
  url.searchParams.set("salesCatalog", ret.catalogId);
  if (ret.year) url.searchParams.set("salesYear", ret.year);
  if (ret.catalogTitle) url.searchParams.set("salesTitle", ret.catalogTitle);
  if (ret.mode === "past") {
    url.searchParams.set("salesLot", ret.lotId || ret.hipKey);
    if (ret.hip) url.searchParams.set("salesHip", ret.hip);
  } else {
    url.searchParams.set("salesHip", ret.hip || ret.hipKey);
  }
  return `${url.pathname}${url.search}`;
}

export function horseHrefWithReturn(name, ret) {
  const base = `/horses/${encodeURIComponent(name || "")}`;
  return withSalesReturn(base, ret);
}

function readStore() {
  if (typeof window === "undefined") return { returnTo: null, stack: [] };
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return { returnTo: null, stack: [] };
    const parsed = JSON.parse(raw);
    return {
      returnTo: parsed?.returnTo || null,
      stack: Array.isArray(parsed?.stack) ? parsed.stack : [],
    };
  } catch {
    return { returnTo: null, stack: [] };
  }
}

function writeStore(next) {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* ignore quota */
  }
}

/** Remember sales return target and push the horse page onto the in-app stack. */
export function rememberSalesVisit(ret, horseName) {
  if (!ret) return;
  const store = readStore();
  const returnTo = store.returnTo && sameReturn(store.returnTo, ret) ? store.returnTo : ret;
  const stack = sameReturn(store.returnTo, ret) ? [...store.stack] : [];
  const label = String(horseName || "").trim();
  if (label && stack[stack.length - 1] !== label) stack.push(label);
  writeStore({ returnTo, stack });
}

export function clearSalesNav() {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

export function peekSalesNav() {
  return readStore();
}

function sameReturn(a, b) {
  if (!a || !b) return false;
  return a.mode === b.mode && a.catalogId === b.catalogId && a.hipKey === b.hipKey;
}
