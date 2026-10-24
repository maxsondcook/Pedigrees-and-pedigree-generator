const KEY = "crossr-barn-v1";

function empty() {
  return { starred: [], hypofoals: [], favorites: [], analyzed: [] };
}

export function loadBarn() {
  if (typeof window === "undefined") return empty();
  try {
    return { ...empty(), ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return empty();
  }
}

function loggedIn() {
  if (typeof window === "undefined") return false;
  try {
    return Boolean(JSON.parse(sessionStorage.getItem("crossr-user") || "null"));
  } catch {
    return false;
  }
}

async function persistRemote(next) {
  if (!loggedIn()) return;
  try {
    const { apiPost } = await import("./api");
    await apiPost("/api/auth/preferences", next);
  } catch {
    /* keep the local copy even if sync fails */
  }
}

export function saveBarn(next) {
  localStorage.setItem(KEY, JSON.stringify(next));
  window.dispatchEvent(new Event("crossr-barn"));
  persistRemote(next);
}

export function applyRemoteBarn(prefs) {
  const next = { ...empty(), ...(prefs || {}) };
  localStorage.setItem(KEY, JSON.stringify(next));
  window.dispatchEvent(new Event("crossr-barn"));
}

export function toggleStar(name) {
  const barn = loadBarn();
  const set = new Set(barn.starred);
  if (set.has(name)) set.delete(name);
  else set.add(name);
  barn.starred = Array.from(set);
  saveBarn(barn);
  return barn;
}

export function isStarred(name) {
  return loadBarn().starred.includes(name);
}

export function saveHypofoal(entry) {
  const barn = loadBarn();
  barn.hypofoals = [entry, ...barn.hypofoals.filter((h) => h.foal_name !== entry.foal_name)].slice(0, 40);
  saveBarn(barn);
  return barn;
}

export function saveFavorite(name) {
  const barn = loadBarn();
  barn.favorites = [name, ...barn.favorites.filter((n) => n !== name)].slice(0, 40);
  saveBarn(barn);
  return barn;
}

export function saveAnalyzedSale(entry) {
  const barn = loadBarn();
  barn.analyzed = [entry, ...barn.analyzed.filter((a) => a.id !== entry.id)].slice(0, 40);
  saveBarn(barn);
  return barn;
}
