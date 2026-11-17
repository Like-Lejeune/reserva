import type { Session } from "./types";

const KEY = "reserva.session";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** La session est gardée sur le téléphone : l'application s'ouvre même sans réseau. */
export function getSession(): Session | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}

export function setSession(s: Session | null): void {
  if (s) localStorage.setItem(KEY, JSON.stringify(s));
  else localStorage.removeItem(KEY);
  window.dispatchEvent(new Event("reserva:session"));
}

interface Options {
  method?: string;
  json?: unknown;
  form?: FormData;
  raw?: boolean;
}

export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getSession()?.token;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.json !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: opts.method ?? (opts.json !== undefined || opts.form ? "POST" : "GET"),
      headers,
      body: opts.form ?? (opts.json !== undefined ? JSON.stringify(opts.json) : undefined),
    });
  } catch {
    throw new ApiError(0, "Pas de connexion");
  }
  if (res.status === 401 && token) setSession(null); // session expirée : retour à l'écran de connexion
  if (!res.ok) {
    let detail = `Erreur ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = String(body.detail[0].msg).replace(/^Value error, /, "");
    } catch {
      /* réponse non JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return (opts.raw ? res.blob() : res.json()) as Promise<T>;
}
