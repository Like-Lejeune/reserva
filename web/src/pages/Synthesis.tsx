import { useEffect, useState } from "react";
import { getSession } from "../lib/api";
import { saveSynthesis, useSyncState, writeSynthesis } from "../lib/store";
import type { Project } from "../lib/types";

/**
 * Synthèse en tête du rapport : l'IA la rédige à partir des défauts (état, urgences, priorités,
 * proposition de réception), l'ingénieur la relit et la corrige. Elle figure en tête du PDF.
 */
export function Synthesis({ project, count }: { project: Project; count: number }) {
  const role = getSession()?.user.role ?? "admin";
  const canWrite = role === "admin" || role === "ingenieur";
  const { online } = useSyncState();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(project.summary ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!editing) setText(project.summary ?? "");
  }, [project.summary, editing]);

  if (count === 0 || (!canWrite && !project.summary)) return null;

  async function draft() {
    if (project.summary && !window.confirm("Réécrire la synthèse ? Vos corrections seront remplacées.")) return;
    setBusy(true);
    setMessage("");
    try {
      const res = await writeSynthesis(project.id);
      setMessage(res.notice || "Relisez-la et corrigez-la si besoin : elle figurera en tête du PDF.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Rédaction impossible");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    try {
      await saveSynthesis(project.id, text.trim());
      setEditing(false);
      setMessage("Synthèse enregistrée.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Enregistrement impossible");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card stack synthesis">
      <h2>Synthèse du rapport</h2>
      {editing ? (
        <>
          <textarea rows={10} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row">
            <button className="btn" onClick={() => setEditing(false)} disabled={busy}>Annuler</button>
            <button className="btn primary" onClick={() => void save()} disabled={busy}>Enregistrer</button>
          </div>
        </>
      ) : project.summary ? (
        <>
          <div className="summary-text">
            {project.summary.split("\n").filter((p) => p.trim()).map((p) => <p key={p}>{p}</p>)}
          </div>
          {canWrite && (
            <div className="row">
              <button className="btn" onClick={() => setEditing(true)} disabled={busy}>Corriger</button>
              <button className="btn" onClick={() => void draft()} disabled={busy || !online}>{busy ? "Rédaction…" : "Réécrire"}</button>
            </div>
          )}
        </>
      ) : (
        <>
          <p className="muted">
            L'IA rédige le résumé de la visite à partir de vos défauts : état général, points urgents,
            corps de métier concernés et proposition pour la réception. Vous la relisez avant l'envoi.
          </p>
          <button className="btn primary" onClick={() => void draft()} disabled={busy || !online}>
            {busy ? "Rédaction…" : online ? "Rédiger la synthèse" : "Rédiger la synthèse (connexion nécessaire)"}
          </button>
        </>
      )}
      {message && <p className="muted small">{message}</p>}
    </section>
  );
}
