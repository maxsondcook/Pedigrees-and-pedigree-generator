const KEY = "crossr-sales-desk-v1";

function seedClients() {
  return [1, 2, 3, 4].map((n) => ({
    id: `c${n}`,
    name: `Client ${n}`,
    sex: "",
    color: "",
    maxPrice: "",
    height: "",
  }));
}

function empty() {
  return { clients: seedClients(), dismissed: {}, notes: {}, stars: {} };
}

export function loadDesk() {
  if (typeof window === "undefined") return empty();
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
    const clients = Array.isArray(saved.clients) && saved.clients.length ? saved.clients : seedClients();
    return { ...empty(), ...saved, clients };
  } catch {
    return empty();
  }
}

export function saveDesk(next) {
  localStorage.setItem(KEY, JSON.stringify(next));
  return next;
}

export function deskKey(mode, catalogId) {
  return `${mode}:${catalogId}`;
}

/** Catalog-scoped star ids (same shape as dismissed). Supports legacy flat boolean maps. */
export function starredIds(desk, mode, catalogId) {
  if (!desk || catalogId == null || catalogId === "") return [];
  const key = deskKey(mode, catalogId);
  const scoped = (desk.stars || {})[key];
  if (Array.isArray(scoped)) return scoped.map(String);
  // Legacy: { [lotId]: true } without catalog scope
  if (scoped && typeof scoped === "object") {
    return Object.entries(scoped).filter(([, on]) => on).map(([id]) => String(id));
  }
  const flat = desk.stars || {};
  if (Array.isArray(flat)) return flat.map(String);
  return Object.entries(flat)
    .filter(([, on]) => on === true)
    .map(([id]) => String(id));
}

export function withStarToggle(desk, mode, catalogId, lotId, on) {
  const key = deskKey(mode, catalogId);
  const list = new Set(starredIds(desk, mode, catalogId));
  const id = String(lotId);
  if (on) list.add(id);
  else list.delete(id);
  return {
    ...desk,
    stars: {
      ...(desk.stars || {}),
      [key]: Array.from(list),
    },
  };
}
