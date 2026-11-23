import { useEffect, useRef, useState } from "react";
import { getSession } from "../lib/api";
import { back } from "../lib/nav";
import { PhotoView } from "../lib/PhotoView";
import { addPhoto, getDefect, listPhotos, saveDefect, useLive } from "../lib/store";
import { isDone, isLate, LOTS, SEVERITIES, shortDate, STATUS_LABELS, type Defect, type Severity } from "../lib/types";

/** Détail d'un défaut : le corriger (avec photo « après »), ou ajuster ce que l'IA a rempli. */
export function DefectPage({ defectId }: { defectId: string }) {
  const data = useLive(async () => ({ defect: await getDefect(defectId), photos: await listPhotos(defectId) }), [defectId]);
  const [form, setForm] = useState<Defect | null>(null);
  const [editing, setEditing] = useState(false);
  const after = useRef<HTMLInputElement>(null);
  const before = useRef<HTMLInputElement>(null);

  const defect = data?.defect;
  useEffect(() => {
    if (defect && !editing) setForm(defect);
  }, [defect, editing]);

  if (!data) return null;
  if (!defect || !form || defect.deleted)
    return (
      <main>
        <p className="empty">Défaut introuvable.</p>
        <button className="btn" onClick={() => back("/")}>Retour</button>
      </main>
    );

  const home = `/r/${defect.project_id}`;
  const avant = data.photos.filter((p) => p.kind === "photo_avant");
  const apres = data.photos.filter((p) => p.kind === "photo_apres");
  // Seul, ou ingénieur dans une équipe : « corrigé » est définitif. Technicien d'équipe : à vérifier.
  const role = getSession()?.user.role ?? "admin";
  const doneStatus = role === "technicien" ? "levee_declaree" : "levee";
  const waiting = defect.status === "levee_declaree";

  async function markFixed(file?: File) {
    if (!file || !defect) return;
    await addPhoto(defect.id, "photo_apres", file);
    await saveDefect({ ...defect, status: doneStatus });
  }

  async function saveEdit() {
    await saveDefect({ ...form!, needs_ai: false });
    setEditing(false);
  }

  async function remove() {
    if (!window.confirm("Supprimer ce défaut du rapport ?")) return;
    await saveDefect({ ...defect!, deleted: true });
    back(home);
  }

  const set = <K extends keyof Defect>(key: K, value: Defect[K]) => setForm({ ...form, [key]: value });

  return (
    <main>
      <header className="top">
        <button className="back" onClick={() => back(home)} aria-label="Retour">‹</button>
        <div className="grow">
          <h1>{defect.number ? `Défaut n° ${defect.number}` : "Défaut"}</h1>
          <span className={`chip s-${defect.status}`}>{STATUS_LABELS[defect.status]}</span>
        </div>
      </header>

      <div className="photos">
        <figure>
          {avant[0] ? <PhotoView photo={avant[0]} /> : <button className="ph add" onClick={() => before.current?.click()}>+ Photo</button>}
          <figcaption>Avant</figcaption>
        </figure>
        {apres[0] && (
          <figure>
            <PhotoView photo={apres[0]} />
            <figcaption>Après</figcaption>
          </figure>
        )}
      </div>
      <input ref={before} type="file" accept="image/*" capture="environment" hidden
             onChange={(e) => e.target.files?.[0] && void addPhoto(defect.id, "photo_avant", e.target.files[0])} />
      <input ref={after} type="file" accept="image/*" capture="environment" hidden onChange={(e) => void markFixed(e.target.files?.[0])} />

      {editing ? (
        <div className="card stack">
          <label>
            Description
            <textarea rows={3} value={form.description} onChange={(e) => set("description", e.target.value)} />
          </label>
          <label>
            Lieu
            <input value={form.location} onChange={(e) => set("location", e.target.value)} placeholder="Ex. Cuisine" />
          </label>
          <label>
            Corps de métier
            <select value={form.lot} onChange={(e) => set("lot", e.target.value)}>
              {Object.entries(LOTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <div>
            Gravité
            <div className="seg">
              {(Object.keys(SEVERITIES) as Severity[]).map((s) => (
                <button key={s} className={form.severity === s ? "on" : ""} onClick={() => set("severity", s)}>{SEVERITIES[s]}</button>
              ))}
            </div>
          </div>
          <label>
            Travail à faire
            <textarea rows={2} value={form.action} onChange={(e) => set("action", e.target.value)} />
          </label>
          <label>
            À corriger avant le
            <input type="date" value={(form.due_date ?? "").slice(0, 10)} onChange={(e) => set("due_date", e.target.value || null)} />
          </label>
          <div className="row">
            <button className="btn" onClick={() => setEditing(false)}>Annuler</button>
            <button className="btn primary" onClick={saveEdit}>Enregistrer</button>
          </div>
        </div>
      ) : (
        <div className="card stack">
          <p className="desc">{defect.description || (defect.needs_photo_ai ? "Description en attente : l'IA lira la photo une fois envoyée" : "Sans description")}</p>
          <dl>
            <dt>Corps de métier</dt><dd>{defect.needs_ai ? "Classement en attente de connexion" : LOTS[defect.lot] ?? defect.lot}</dd>
            {defect.location && (<><dt>Lieu</dt><dd>{defect.location}</dd></>)}
            <dt>Gravité</dt><dd>{SEVERITIES[defect.severity]}</dd>
            {defect.action && (<><dt>Travail à faire</dt><dd>{defect.action}</dd></>)}
            {defect.due_date && !isDone(defect.status) && (
              <><dt>À corriger avant le</dt><dd className={isLate(defect) ? "error" : ""}>{shortDate(defect.due_date)}{isLate(defect) ? ", en retard" : ""}</dd></>
            )}
          </dl>
          <button className="btn" onClick={() => setEditing(true)}>Modifier</button>
        </div>
      )}

      {!editing && (
        <div className="stack">
          {isDone(defect.status) ? (
            <button className="btn" onClick={() => saveDefect({ ...defect, status: "ouverte" })}>Rouvrir : ce n'est pas corrigé</button>
          ) : waiting && role === "technicien" ? (
            <p className="muted">En attente de vérification par l'ingénieur.</p>
          ) : waiting ? (
            <>
              <button className="btn primary big" onClick={() => saveDefect({ ...defect, status: "levee" })}>✓ Valider la correction</button>
              <button className="btn" onClick={() => saveDefect({ ...defect, status: "refusee" })}>Refuser : à reprendre</button>
            </>
          ) : (
            <>
              <button className="btn primary big" onClick={() => after.current?.click()}>✓ C'est corrigé : prendre la photo</button>
              <p className="muted small">La photo « après » sert de preuve dans le rapport.</p>
            </>
          )}
          <button className="link danger" onClick={remove}>Supprimer ce défaut</button>
        </div>
      )}
    </main>
  );
}
