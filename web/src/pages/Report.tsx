import { useState } from "react";
import { api } from "../lib/api";
import { go } from "../lib/nav";
import { PhotoView } from "../lib/PhotoView";
import { deleteProject, getProject, listDefects, listPhotos, sync, useLive, useSyncState } from "../lib/store";
import { isDone, isLate, LOTS, SEVERITIES, shortDate, STATUS_LABELS, type Defect, type Photo } from "../lib/types";
import { Synthesis } from "./Synthesis";

async function load(projectId: string) {
  const [project, defects] = await Promise.all([getProject(projectId), listDefects(projectId)]);
  const photos: Record<string, Photo | undefined> = {};
  for (const d of defects) {
    const all = await listPhotos(d.id);
    photos[d.id] = all.find((p) => p.kind === "photo_avant") ?? all[0];
  }
  return { project, defects, photos };
}

/** Un rapport : la liste des défauts, un gros bouton pour en ajouter, et le PDF à partager. */
export function Report({ projectId }: { projectId: string }) {
  const data = useLive(() => load(projectId), [projectId]);
  const { online, pending } = useSyncState();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  if (!data) return null;
  if (!data.project)
    return (
      <main>
        <p className="empty">Rapport introuvable.</p>
        <button className="btn" onClick={() => go("/")}>Retour</button>
      </main>
    );
  const { project, defects, photos } = data;
  const done = defects.filter((d) => isDone(d.status)).length;

  /** Lien du PDF, lisible sans compte pendant 30 jours. */
  async function pdfLink(): Promise<string | null> {
    setMessage("");
    if (!online) {
      setMessage("Le PDF se prépare sur le serveur : il faut une connexion.");
      return null;
    }
    setBusy(true);
    try {
      await sync(); // le PDF doit contenir ce qui vient d'être saisi
      const { url } = await api<{ url: string }>(`/projects/${projectId}/share`, { method: "POST" });
      return `${window.location.origin}/api/public/report.pdf?${url.split("?")[1]}`;
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Impossible de préparer le PDF");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function openPdf() {
    const url = await pdfLink();
    if (url) window.location.href = url;
  }

  async function share() {
    const url = await pdfLink();
    if (!url) return;
    const text = `Rapport de finition — ${project!.name} : ${defects.length - done} défaut(s) à corriger.`;
    if (navigator.share) {
      try {
        await navigator.share({ title: project!.name, text, url });
      } catch {
        /* partage annulé */
      }
    } else {
      window.location.href = `https://wa.me/?text=${encodeURIComponent(`${text}\n${url}`)}`;
    }
  }

  async function remove() {
    if (!window.confirm(`Supprimer le rapport « ${project!.name} » avec ses ${defects.length} défaut(s) et ses photos ?`)) return;
    await deleteProject(projectId);
    go("/");
  }

  return (
    <main className="with-fab">
      <header className="top">
        <button className="back" onClick={() => go("/")} aria-label="Retour">‹</button>
        <div className="grow">
          <h1>{project.name}</h1>
          <p className="muted">
            {defects.length === 0 ? "Aucun défaut noté" : `${done} sur ${defects.length} corrigé${done > 1 ? "s" : ""}`}
            {project.client ? ` · ${project.client}` : ""}
          </p>
        </div>
      </header>

      {defects.length > 0 && (
        <>
          <div className="bar"><div style={{ width: `${(100 * done) / defects.length}%` }} /></div>
          <div className="row">
            <button className="btn" onClick={openPdf} disabled={busy}>Voir le PDF</button>
            <button className="btn primary" onClick={share} disabled={busy}>Partager</button>
          </div>
          <button className="btn" onClick={() => go(`/r/${projectId}/artisans`)}>Artisans : envoyer à chacun ses défauts</button>
          {pending > 0 && online && <p className="muted small">Envoi des dernières saisies…</p>}
          {message && <p className="error">{message}</p>}
        </>
      )}

      <Synthesis project={project} count={defects.length} />

      {defects.length === 0 && (
        <p className="empty">Prenez une photo du premier défaut : appuyez sur le bouton en bas.</p>
      )}

      <ul className="list">
        {defects.map((d) => (
          <li key={d.id}>
            <DefectRow d={d} photo={photos[d.id]} />
          </li>
        ))}
      </ul>

      <button className="link danger" onClick={remove}>Supprimer ce rapport</button>

      <button className="fab" onClick={() => go(`/r/${projectId}/ajouter`)}>+ Ajouter un défaut</button>
    </main>
  );
}

function DefectRow({ d, photo }: { d: Defect; photo?: Photo }) {
  return (
    <button className={`card item ${isDone(d.status) ? "done" : ""}`} onClick={() => go(`/d/${d.id}`)}>
      <PhotoView photo={photo} className="thumb" />
      <div className="grow">
        <strong>{d.description || d.transcript || "Défaut sans description"}</strong>
        <span className="muted">
          {d.number ? `N° ${d.number} · ` : ""}
          {d.needs_ai ? "Classement en attente" : d.needs_photo_ai ? "Lecture de la photo en attente" : LOTS[d.lot] ?? d.lot}
          {d.location ? ` · ${d.location}` : ""}
        </span>
        <span className="chips">
          <span className={`chip s-${d.status}`}>{STATUS_LABELS[d.status]}</span>
          {d.severity !== "mineure" && !isDone(d.status) && <span className={`chip v-${d.severity}`}>{SEVERITIES[d.severity]}</span>}
          {!isDone(d.status) && d.due_date && (
            <span className={`chip ${isLate(d) ? "late" : ""}`}>{isLate(d) ? "En retard, " : ""}avant le {shortDate(d.due_date)}</span>
          )}
          {d.dirty && <span className="chip">Non envoyé</span>}
        </span>
      </div>
    </button>
  );
}
