const API = process.env.NEXT_PUBLIC_API_URL || "";

async function request(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    cache: "no-store",
    credentials: "include",
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    const message = typeof detail === "string"
      ? detail
      : detail?.error === "ambiguous_year"
        ? `Multiple horses named ${detail.name}. Choose a foaling year.`
        : `Request failed (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    err.detail = detail;
    throw err;
  }
  return data;
}

export function apiGet(path) {
  return request(path);
}

export function apiPost(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

export function horseHref(name) {
  return `/horses/${encodeURIComponent(name)}`;
}
