"use client";

import { apiGet, apiPost } from "./api";
import { applyRemoteBarn, loadBarn } from "./barn";

export function loadUser() {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(sessionStorage.getItem("crossr-user") || "null");
  } catch {
    return null;
  }
}

function setUser(user) {
  if (user) sessionStorage.setItem("crossr-user", JSON.stringify(user));
  else sessionStorage.removeItem("crossr-user");
  window.dispatchEvent(new Event("crossr-auth"));
}

export async function refreshAuth() {
  try {
    const data = await apiGet("/api/auth/me");
    const user = data.user || null;
    setUser(user);
    if (user && data.preferences) applyRemoteBarn(data.preferences);
    return { user, preferences: data.preferences };
  } catch {
    setUser(null);
    return { user: null, preferences: null };
  }
}

export async function registerAccount({ email, username, password }) {
  const data = await apiPost("/api/auth/register", {
    email,
    username,
    password,
    preferences: loadBarn(),
  });
  setUser(data.user);
  if (data.preferences) applyRemoteBarn(data.preferences);
  return data;
}

export async function signInAccount({ identifier, password }) {
  const data = await apiPost("/api/auth/login", {
    identifier,
    password,
    preferences: loadBarn(),
  });
  setUser(data.user);
  if (data.preferences) applyRemoteBarn(data.preferences);
  return data;
}

export async function signOutAccount() {
  try {
    await apiPost("/api/auth/logout", {});
  } catch {
    /* still clear local session */
  }
  setUser(null);
}
