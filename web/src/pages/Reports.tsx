import { useState, type FormEvent } from "react";
import { go } from "../lib/nav";
import { getSession } from "../lib/api";
import { createProject, listProjects, useLive } from "../lib/store";

/** Accueil : la liste des rapports et un bouton pour en créer un. Seul le nom est demandé. */
export function Reports() {
  const projects = useLive(listProjects, []);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [client, setClient] = useState("");
  const user = getSession()?.user;

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    const p = await createProject(name.trim(), client.trim());
    go(`/r/${p.id}`);
  }

  return (
    <main>
      <header className="top">
        <div>
          <h1>Mes rapports</h1>
          <p className="muted">Bonjour {user?.name.split(" ")[0]}</p>
        </div>
        <button className="icon-btn" onClick={() => go("/compte")} aria-label="Mon compte">
          {user?.name.slice(0, 1).toUpperCase()}
        </button>
      </header>

      {adding ? (
        <form onSubmit={create} className="card stack">
          <label>
            Nom du chantier
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex. Villa Odza" autoFocus required />
          </label>
          <label>
            Client <span className="muted">(facultatif)</span>
            <input value={client} onChange={(e) => setClient(e.target.value)} />
          </label>
          <div className="row">
            <button type="button" className="btn" onClick={() => setAdding(false)}>
              Annuler
            </button>
            <button className="btn primary">Créer</button>
          </div>
        </form>
      ) : (
        <button className="btn primary big" onClick={() => setAdding(true)}>
          + Nouveau rapport
        </button>
      )}

      {projects?.length === 0 && !adding && (
        <p className="empty">Aucun rapport pour l'instant. Créez-en un, puis ajoutez vos photos de défauts.</p>
      )}

      <ul className="list">
        {projects?.map((p) => (
          <li key={p.id}>
            <button className="card item" onClick={() => go(`/r/${p.id}`)}>
              <div className="grow">
                <strong>{p.name}</strong>
                <span className="muted">
                  {p.total === 0 ? "Aucun défaut noté" : `${p.done} sur ${p.total} corrigé${p.done > 1 ? "s" : ""}`}
                </span>
                {p.total > 0 && (
                  <div className="bar">
                    <div style={{ width: `${(100 * p.done) / p.total}%` }} />
                  </div>
                )}
              </div>
              <span className="chev">›</span>
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
