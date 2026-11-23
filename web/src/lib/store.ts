/**
 * Données locales (IndexedDB) + synchronisation.
 *
 * Tout ce que l'utilisateur fait est d'abord enregistré sur le téléphone, puis envoyé au serveur
 * dès qu'il y a du réseau. Les identifiants sont créés ici : renvoyer deux fois ne crée pas de doublon.
 */
import { useEffect, useState } from "react";
import { api, ApiError, getSession, setSession } from "./api";
import { inDays, type Defect, type Photo, type Project } from "./types";

type StoreName = "projects" | "defects" | "photos";

let dbPromise: Promise<IDBDatabase> | null = null;
let dbOwner = "";

function openDb(): Promise<IDBDatabase> {
  const owner = getSession()?.org.id ?? "anonyme";
  if (dbPromise && dbOwner === owner) return dbPromise;
  dbOwner = owner;
  // Une base par compte : deux personnes sur le même téléphone ne voient pas les rapports de l'autre.
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(`reserva-${owner}`, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      db.createObjectStore("projects", { keyPath: "id" });
      db.createObjectStore("defects", { keyPath: "id" }).createIndex("project_id", "project_id");
      db.createObjectStore("photos", { keyPath: "id" }).createIndex("reserve_id", "reserve_id");
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

function run<T>(store: StoreName, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const req = fn(db.transaction(store, mode).objectStore(store));
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      }),
  );
}

const getAll = <T,>(store: StoreName) => run<T[]>(store, "readonly", (s) => s.getAll());
const getOne = <T,>(store: StoreName, id: string) => run<T | undefined>(store, "readonly", (s) => s.get(id));
const put = (store: StoreName, value: unknown) => run(store, "readwrite", (s) => s.put(value));
const del = (store: StoreName, id: string) => run(store, "readwrite", (s) => s.delete(id));
const byIndex = <T,>(store: StoreName, index: string, key: string) =>
  run<T[]>(store, "readonly", (s) => s.index(index).getAll(key));

// ---------- abonnements : les écrans se rafraîchissent quand les données changent ----------

const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export interface SyncState {
  online: boolean;
  syncing: boolean;
  pending: number;
  error: string;
  /** Limite de l'offre atteinte (stockage, nombre de rapports) : message à montrer avec le lien vers les offres. */
  limit: string;
}
let state: SyncState = { online: navigator.onLine, syncing: false, pending: 0, error: "", limit: "" };
const setState = (patch: Partial<SyncState>) => {
  state = { ...state, ...patch };
  emit();
};

/** Relit `load` à chaque changement des données locales. */
export function useLive<T>(load: () => Promise<T>, deps: unknown[]): T | undefined {
  const [value, setValue] = useState<T>();
  useEffect(() => {
    let alive = true;
    const refresh = () => load().then((v) => alive && setValue(v));
    refresh();
    listeners.add(refresh);
    return () => {
      alive = false;
      listeners.delete(refresh);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return value;
}

export function useSyncState(): SyncState {
  const [s, setS] = useState(state);
  useEffect(() => {
    const l = () => setS(state);
    listeners.add(l);
    return () => void listeners.delete(l);
  }, []);
  return s;
}

// ---------- lecture ----------

export async function listProjects(): Promise<(Project & { total: number; done: number })[]> {
  const [projects, defects] = await Promise.all([getAll<Project>("projects"), getAll<Defect>("defects")]);
  return projects
    .filter((p) => !p.deleted)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map((p) => {
      const mine = defects.filter((d) => d.project_id === p.id && !d.deleted);
      return { ...p, total: mine.length, done: mine.filter((d) => d.status === "levee").length };
    });
}

export const getProject = (id: string) => getOne<Project>("projects", id);
export const getDefect = (id: string) => getOne<Defect>("defects", id);

export async function listDefects(projectId: string): Promise<Defect[]> {
  const rows = await byIndex<Defect>("defects", "project_id", projectId);
  return rows
    .filter((d) => !d.deleted)
    .sort((a, b) => (a.number || 1e9) - (b.number || 1e9) || a.updated_at.localeCompare(b.updated_at));
}

export const listPhotos = (defectId: string) => byIndex<Photo>("photos", "reserve_id", defectId);

// ---------- écriture (toujours locale d'abord) ----------

export async function createProject(name: string, client = "", location = ""): Promise<Project> {
  const p: Project = { id: crypto.randomUUID(), name, client, location, created_at: new Date().toISOString(), dirty: true };
  await put("projects", p);
  emit();
  void sync();
  return p;
}

/** Supprime un rapport, ses défauts et ses photos. La place est rendue au compte. */
export async function deleteProject(id: string): Promise<void> {
  const p = await getOne<Project>("projects", id);
  if (!p) return;
  await put("projects", { ...p, deleted: true, dirty: true });
  emit();
  void sync();
}

async function dropLocalProject(id: string): Promise<void> {
  for (const d of await byIndex<Defect>("defects", "project_id", id)) {
    for (const ph of await byIndex<Photo>("photos", "reserve_id", d.id)) await del("photos", ph.id);
    await del("defects", d.id);
  }
  await del("projects", id);
}

/** Rédige la synthèse du rapport sur le serveur (connexion nécessaire), puis la garde ici. */
export async function writeSynthesis(projectId: string): Promise<{ summary: string; provider: string; notice: string }> {
  await sync(); // la synthèse doit tenir compte de ce qui vient d'être saisi
  const res = await api<{ summary: string; provider: string; notice: string; balance_fcfa: number }>(
    `/projects/${projectId}/synthesis`, { method: "POST" });
  rememberBalance(res.balance_fcfa);
  const p = await getOne<Project>("projects", projectId);
  if (p) await put("projects", { ...p, summary: res.summary });
  emit();
  return res;
}

export async function saveSynthesis(projectId: string, summary: string): Promise<void> {
  await api(`/projects/${projectId}`, { method: "PATCH", json: { summary } });
  const p = await getOne<Project>("projects", projectId);
  if (p) await put("projects", { ...p, summary });
  emit();
}

export async function saveDefect(d: Defect): Promise<void> {
  await put("defects", { ...d, updated_at: new Date().toISOString(), dirty: true });
  emit();
  void sync();
}

export function newDefect(projectId: string): Defect {
  return {
    id: crypto.randomUUID(),
    project_id: projectId,
    number: 0,
    location: "",
    lot: "autre",
    description: "",
    action: "",
    severity: "mineure",
    status: "ouverte",
    transcript: "",
    updated_at: new Date().toISOString(),
  };
}

/** Réduit la photo à 1600 px avant de la garder : moins de mémoire, moins de données mobiles. */
async function shrink(file: Blob): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const out = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.8));
    return out ?? file;
  } catch {
    return file;
  }
}

export async function addPhoto(defectId: string, kind: Photo["kind"], file: Blob): Promise<void> {
  const photo: Photo = { id: crypto.randomUUID(), reserve_id: defectId, kind, blob: await shrink(file), uploaded: false };
  await put("photos", photo);
  emit();
  void sync();
}

/** Image affichable. Les photos prises sur un autre appareil sont téléchargées une fois puis gardées. */
export async function photoBlob(photo: Photo): Promise<Blob | null> {
  if (photo.blob) return photo.blob;
  try {
    const blob = await api<Blob>(`/media/${photo.id}`, { raw: true });
    await put("photos", { ...photo, blob });
    return blob;
  } catch {
    return null;
  }
}

// ---------- synchronisation ----------

async function countPending(): Promise<number> {
  const [p, d, ph] = await Promise.all([getAll<Project>("projects"), getAll<Defect>("defects"), getAll<Photo>("photos")]);
  return p.filter((x) => x.dirty).length + d.filter((x) => x.dirty).length + ph.filter((x) => !x.uploaded).length;
}

let running: Promise<void> | null = null;
let again = false;

/** Envoie ce qui attend, puis récupère ce qui a changé. Sans réseau, ne fait rien : on réessaiera. */
export function sync(): Promise<void> {
  if (running) {
    again = true;
    return running;
  }
  running = doSync().finally(() => {
    running = null;
    if (again) {
      again = false;
      void sync();
    }
  });
  return running;
}

async function doSync(): Promise<void> {
  if (!getSession()) return;
  if (!navigator.onLine) {
    setState({ online: false, pending: await countPending() });
    return;
  }
  setState({ online: true, syncing: true, error: "", limit: "" });
  try {
    await push();
    await pull();
    setState({ syncing: false, pending: await countPending() });
  } catch (e) {
    const offline = e instanceof ApiError && e.status === 0;
    setState({
      syncing: false,
      online: !offline,
      pending: await countPending(),
      error: offline || !(e instanceof Error) ? "" : e.message,
    });
  }
}

type Draft = Pick<Defect, "location" | "lot" | "description" | "action" | "severity"> & { due_in_days: number };
interface AiAnswer {
  draft: Draft;
  drafts?: Draft[];
  balance_fcfa: number;
}

function rememberBalance(balance_fcfa: number) {
  const s = getSession();
  if (s) localStorage.setItem("reserva.session", JSON.stringify({ ...s, org: { ...s.org, balance_fcfa } }));
}

async function push(): Promise<void> {
  const waiting = new Set<string>(); // rapports pas encore acceptés par le serveur
  for (const p of (await getAll<Project>("projects")).filter((x) => x.dirty)) {
    try {
      if (p.deleted) {
        await api(`/projects/${p.id}`, { method: "DELETE" });
        await dropLocalProject(p.id);
        continue;
      }
      await api("/projects", { json: { id: p.id, name: p.name, client: p.client, location: p.location } });
      await put("projects", { ...p, dirty: false });
    } catch (e) {
      // Limite de l'offre : le rapport reste sur le téléphone, rien n'est perdu, on le signale.
      if (e instanceof ApiError && e.status === 402) {
        waiting.add(p.id);
        setState({ limit: e.message });
      } else throw e;
    }
  }

  const dirty = (await getAll<Defect>("defects")).filter((x) => x.dirty && !waiting.has(x.project_id));
  // Aide IA : la note dictée devient un ou plusieurs défauts complets (lieu, corps de métier, description
  // propre, travail à faire, gravité, délai) avant l'envoi.
  for (const d of dirty.filter((x) => x.needs_ai && x.transcript.trim() && !x.deleted)) {
    try {
      const { draft, drafts, balance_fcfa } = await api<AiAnswer>("/ai/structure", { json: { text: d.transcript } });
      Object.assign(d, {
        lot: draft.lot,
        severity: draft.severity,
        location: d.location || draft.location,
        action: d.action || draft.action,
        description: draft.description || d.description,
        due_date: d.due_date || inDays(draft.due_in_days),
        needs_ai: false,
      });
      await put("defects", d);
      // La note en décrivait plusieurs : chacun devient un défaut (sans photo), envoyé au passage suivant.
      for (const extra of (drafts ?? []).slice(1)) {
        await put("defects", {
          ...newDefect(d.project_id),
          location: extra.location, lot: extra.lot, description: extra.description, action: extra.action,
          severity: extra.severity, due_date: inDays(extra.due_in_days), dirty: true,
        } satisfies Defect);
        again = true;
      }
      rememberBalance(balance_fcfa);
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) throw e; // réseau coupé : on réessaiera tout
      d.needs_ai = false; // l'IA n'a pas pu aider : la note part telle quelle, modifiable à la main
    }
  }
  if (dirty.length) {
    const res = await api<{ results: { id: string; result: string; number?: number; detail?: string }[] }>("/sync/push", {
      json: {
        reserves: dirty.map((d) => ({
          id: d.id, project_id: d.project_id, location: d.location, lot: d.lot, description: d.description,
          action: d.action, severity: d.severity, status: d.status, transcript: d.transcript,
          due_date: d.due_date ?? null, updated_at: d.updated_at, deleted: !!d.deleted,
        })),
      },
    });
    for (const r of res.results) {
      const d = dirty.find((x) => x.id === r.id)!;
      if (r.result === "rejected") setState({ error: r.detail ?? "Une modification a été refusée" });
      // Modifié pendant l'envoi : on garde la version la plus récente, elle partira au prochain passage.
      const current = await getOne<Defect>("defects", d.id);
      if (current && current.updated_at !== d.updated_at) {
        await put("defects", { ...current, number: r.number ?? current.number });
        again = true;
        continue;
      }
      if (d.deleted && r.result !== "rejected") await del("defects", d.id);
      else await put("defects", { ...d, number: r.number ?? d.number, dirty: false });
    }
  }

  for (const ph of (await getAll<Photo>("photos")).filter((x) => !x.uploaded && x.blob)) {
    const form = new FormData();
    form.append("reserve_id", ph.reserve_id);
    form.append("kind", ph.kind);
    form.append("file", ph.blob!, `${ph.id}.jpg`);
    try {
      await api(`/media/${ph.id}`, { method: "PUT", form });
      await put("photos", { ...ph, uploaded: true });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) await del("photos", ph.id); // défaut supprimé entre-temps
      else if (e instanceof ApiError && e.status === 402) {
        setState({ limit: e.message }); // stockage plein : les photos restent sur le téléphone
        break;
      } else throw e;
    }
  }

  // Photo sans note : une fois la photo sur le serveur, l'IA décrit le défaut qu'elle montre.
  for (const d of (await getAll<Defect>("defects")).filter((x) => x.needs_photo_ai && !x.dirty && !x.deleted)) {
    const photos = await byIndex<Photo>("photos", "reserve_id", d.id);
    if (photos.some((ph) => !ph.uploaded)) continue;
    try {
      const res = await api<{ reserve: ServerDefect; balance_fcfa: number }>(`/ai/reserves/${d.id}/describe`, { method: "POST" });
      const { media: _media, ...fields } = res.reserve;
      const current = await getOne<Defect>("defects", d.id);
      if (current && !current.dirty) await put("defects", { ...current, ...fields, needs_photo_ai: false, dirty: false });
      rememberBalance(res.balance_fcfa);
    } catch (e) {
      if (e instanceof ApiError && e.status === 0) throw e;
      // Pas d'IA de vision, ou pas de crédit : on n'insiste pas, l'ingénieur complète à la main.
      await put("defects", { ...d, needs_photo_ai: false });
    }
  }
}

interface ServerDefect extends Defect {
  media: { id: string; reserve_id: string; kind: string }[];
}

async function pull(): Promise<void> {
  const me = await api<{ user: NonNullable<ReturnType<typeof getSession>>["user"]; org: NonNullable<ReturnType<typeof getSession>>["org"] }>("/me");
  const s = getSession();
  if (s) localStorage.setItem("reserva.session", JSON.stringify({ ...s, ...me }));

  const remote = await api<Project[]>("/projects");
  const localProjects = await getAll<Project>("projects");
  for (const p of localProjects) if (!p.dirty && !remote.some((r) => r.id === p.id)) await dropLocalProject(p.id);
  for (const p of remote) {
    if (localProjects.find((x) => x.id === p.id)?.deleted) continue; // suppression en attente d'envoi
    await put("projects", { id: p.id, name: p.name, client: p.client, location: p.location, summary: p.summary ?? "",
                            created_at: p.created_at, dirty: false });
    const server = await api<ServerDefect[]>(`/projects/${p.id}/reserves`);
    const local = await byIndex<Defect>("defects", "project_id", p.id);
    for (const d of local) if (!d.dirty && !server.some((r) => r.id === d.id)) await del("defects", d.id);
    const photos = await getAll<Photo>("photos");
    for (const { media, ...d } of server) {
      if (!local.find((x) => x.id === d.id)?.dirty) await put("defects", { ...d, dirty: false });
      for (const m of media) {
        if ((m.kind === "photo_avant" || m.kind === "photo_apres") && !photos.some((x) => x.id === m.id)) {
          await put("photos", { id: m.id, reserve_id: m.reserve_id, kind: m.kind, uploaded: true } satisfies Photo);
        }
      }
    }
  }
}

export function logout(): void {
  dbPromise = null;
  setSession(null);
}

window.addEventListener("online", () => void sync());
window.addEventListener("offline", () => setState({ online: false }));
