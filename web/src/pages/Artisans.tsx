import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { go } from "../lib/nav";
import { sync } from "../lib/store";
import { LOTS } from "../lib/types";

interface Company { id: string; name: string; lot: string; contact_name: string; phone: string }
interface Outgoing { company_id: string; company: string; reserve_count: number; message: string; whatsapp_link: string | null }

/**
 * Artisans d'un chantier. Chaque défaut va à l'artisan du même corps de métier ;
 * « Préparer l'envoi » rédige pour chacun le message WhatsApp avec ses défauts et le lien de son PDF.
 */
export function Artisans({ projectId }: { projectId: string }) {
  const [name, setName] = useState("");
  const [companies, setCompanies] = useState<Company[]>([]);
  const [form, setForm] = useState({ name: "", lot: "plomberie", phone: "" });
  const [outgoing, setOutgoing] = useState<Outgoing[] | null>(null);
  const [error, setError] = useState("");
  const [upgrade, setUpgrade] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const p = await api<{ name: string; companies: Company[] }>(`/projects/${projectId}`);
      setName(p.name);
      setCompanies(p.companies);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 0 ? "Les artisans se gèrent avec une connexion." : e instanceof Error ? e.message : "Chargement impossible");
    }
  }, [projectId]);
  useEffect(() => {
    void sync().then(load); // le rapport doit exister sur le serveur
  }, [load]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setUpgrade(false);
    try {
      await action();
    } catch (e) {
      setUpgrade(e instanceof ApiError && e.status === 402);
      setError(e instanceof Error ? e.message : "Action impossible");
    } finally {
      setBusy(false);
    }
  }

  const add = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api(`/projects/${projectId}/companies`, { json: form });
      setForm({ name: "", lot: form.lot, phone: "" });
      setOutgoing(null);
      await load();
    });
  };

  const remove = (c: Company) => {
    if (!window.confirm(`Retirer ${c.name} de ce chantier ? Ses défauts restent dans le rapport.`)) return;
    void run(async () => {
      await api(`/companies/${c.id}`, { method: "DELETE" });
      setOutgoing(null);
      await load();
    });
  };

  const prepare = () =>
    run(async () => {
      await sync(); // les défauts saisis à l'instant doivent partir avec
      setOutgoing(await api<Outgoing[]>(`/projects/${projectId}/dispatch`, { json: { send: false } }));
    });

  return (
    <main>
      <header className="top">
        <button className="back" onClick={() => go(`/r/${projectId}`)} aria-label="Retour">‹</button>
        <div className="grow"><h1>Artisans</h1><p className="muted">{name}</p></div>
      </header>

      {companies.length === 0 && !error && (
        <p className="empty">Ajoutez les artisans du chantier. Chacun recevra les défauts de son corps de métier.</p>
      )}
      <ul className="list">
        {companies.map((c) => (
          <li key={c.id} className="card item">
            <div className="grow">
              <strong>{c.name}</strong>
              <span className="muted">{LOTS[c.lot] ?? c.lot}{c.phone ? `, ${c.phone}` : ", sans numéro"}</span>
            </div>
            <button className="link danger" onClick={() => remove(c)} disabled={busy}>Retirer</button>
          </li>
        ))}
      </ul>

      {companies.length > 0 && <button className="btn primary big" onClick={() => void prepare()} disabled={busy}>Préparer l'envoi des défauts</button>}
      {error && (
        <p className="error">{error} {upgrade && <button className="inline" onClick={() => go("/compte")}>Voir les offres</button>}</p>
      )}

      {outgoing && (
        <div className="card stack">
          <h2>Messages prêts</h2>
          {outgoing.length === 0 && <p className="muted">Aucun défaut à corriger pour ces artisans. Vérifiez que le corps de métier de chaque défaut correspond.</p>}
          {outgoing.map((o) => (
            <div key={o.company_id} className="offer">
              <div className="row between"><strong>{o.company}</strong><span>{o.reserve_count} défaut{o.reserve_count > 1 ? "s" : ""}</span></div>
              <details><summary>Voir le message</summary><pre className="message">{o.message}</pre></details>
              {o.whatsapp_link
                ? <a className="btn primary" href={o.whatsapp_link} target="_blank" rel="noreferrer">Envoyer par WhatsApp</a>
                : <span className="muted small">Ajoutez son numéro pour l'envoyer par WhatsApp.</span>}
            </div>
          ))}
        </div>
      )}

      <form onSubmit={add} className="card stack">
        <h2>Ajouter un artisan</h2>
        <label>Nom<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required placeholder="Ex. Ets Plomberie Nkolo" /></label>
        <label>
          Corps de métier
          <select value={form.lot} onChange={(e) => setForm({ ...form, lot: e.target.value })}>
            {Object.entries(LOTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label>
          Numéro WhatsApp
          <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} inputMode="tel" placeholder="237 6XX XX XX XX" />
          <small className="muted">Avec l'indicatif du pays (237 pour le Cameroun).</small>
        </label>
        <button className="btn" disabled={busy}>Ajouter</button>
      </form>
    </main>
  );
}
