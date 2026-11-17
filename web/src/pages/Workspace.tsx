import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, getSession } from "../lib/api";
import { go } from "../lib/nav";
import { sync } from "../lib/store";
import type { Role, User } from "../lib/types";

interface OrgInfo {
  name: string; address: string; phone: string; email: string; registration_no: string;
  has_logo: boolean; plan: string; plan_label: string;
}
interface Member extends User { active: boolean }

const ROLES: Record<Role, string> = {
  technicien: "Technicien : relève les défauts",
  ingenieur: "Ingénieur : valide les corrections, envoie les rapports",
  lecteur: "Lecteur : consulte seulement",
  admin: "Responsable : gère l'espace et l'abonnement",
};

/** Mon espace : ce qui apparaît en tête des rapports PDF (logo, coordonnées), et l'équipe. */
export function Workspace() {
  const me = getSession()?.user;
  const isAdmin = me?.role === "admin";
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [logo, setLogo] = useState("");
  const [members, setMembers] = useState<Member[]>([]);
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  const [memberError, setMemberError] = useState("");
  const [form, setForm] = useState({ name: "", login: "", password: "", role: "technicien" as Role });
  const file = useRef<HTMLInputElement>(null);

  const loadLogo = useCallback(async () => {
    try {
      const blob = await api<Blob>("/org/logo", { raw: true });
      setLogo((old) => (old && URL.revokeObjectURL(old), URL.createObjectURL(blob)));
    } catch {
      setLogo("");
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const res = await api<{ org: OrgInfo }>("/me");
      setOrg(res.org);
      setMembers(await api<Member[]>("/org/members"));
      if (res.org.has_logo) void loadLogo();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chargement impossible");
    }
  }, [loadLogo]);
  useEffect(() => void load(), [load]);

  if (!org) return <main><p className="muted">{error || "Chargement…"}</p></main>;
  const paid = org.plan !== "gratuit";
  const set = (key: keyof OrgInfo, value: string) => (setSaved(""), setOrg({ ...org, [key]: value }));

  async function save(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("/org", { method: "PATCH", json: { name: org!.name, address: org!.address, phone: org!.phone, email: org!.email, registration_no: org!.registration_no } });
      setSaved("Enregistré.");
      void sync();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Enregistrement impossible");
    }
  }

  async function upload(picked?: File) {
    if (!picked) return;
    setError("");
    const body = new FormData();
    body.append("file", picked);
    try {
      await api("/org/logo", { method: "PUT", form: body });
      await loadLogo();
      setOrg({ ...org!, has_logo: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Envoi du logo impossible");
    }
  }

  async function addMember(e: FormEvent) {
    e.preventDefault();
    setMemberError("");
    try {
      await api("/org/members", { json: form });
      setForm({ name: "", login: "", password: "", role: "technicien" });
      await load();
    } catch (err) {
      setMemberError(err instanceof Error ? err.message : "Ajout impossible");
    }
  }

  async function remove(m: Member) {
    if (!window.confirm(`Retirer ${m.name} de l'espace ? Cette personne ne pourra plus se connecter.`)) return;
    try {
      await api(`/org/members/${m.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setMemberError(err instanceof Error ? err.message : "Retrait impossible");
    }
  }

  return (
    <main>
      <header className="top">
        <button className="back" onClick={() => go("/compte")} aria-label="Retour">‹</button>
        <h1>Mon espace</h1>
      </header>

      <form onSubmit={save} className="card stack">
        <h2>En-tête de mes rapports</h2>
        {!paid && (
          <p className="notice">
            Votre logo et vos coordonnées apparaissent sur le PDF à partir de l'offre Pro.{" "}
            <button type="button" className="inline" onClick={() => go("/compte")}>Voir les offres</button>
          </p>
        )}
        <div className="logo-row">
          {logo ? <img src={logo} alt="Logo" className="org-logo" /> : <div className="org-logo ph">Logo</div>}
          {isAdmin && <button type="button" className="btn" onClick={() => file.current?.click()}>{logo ? "Changer le logo" : "Ajouter un logo"}</button>}
          <input ref={file} type="file" accept="image/*" hidden onChange={(e) => void upload(e.target.files?.[0])} />
        </div>
        <label>Nom affiché<input value={org.name} onChange={(e) => set("name", e.target.value)} disabled={!isAdmin} required /></label>
        <label>Téléphone<input value={org.phone} onChange={(e) => set("phone", e.target.value)} disabled={!isAdmin} inputMode="tel" /></label>
        <label>E-mail<input value={org.email} onChange={(e) => set("email", e.target.value)} disabled={!isAdmin} inputMode="email" /></label>
        <label>Adresse<input value={org.address} onChange={(e) => set("address", e.target.value)} disabled={!isAdmin} placeholder="Quartier, ville" /></label>
        <label>
          Numéro d'inscription ou d'agrément <span className="muted">(facultatif)</span>
          <input value={org.registration_no} onChange={(e) => set("registration_no", e.target.value)} disabled={!isAdmin} />
        </label>
        {error && <p className="error">{error}</p>}
        {saved && <p className="notice ok">{saved}</p>}
        {isAdmin ? <button className="btn primary">Enregistrer</button> : <p className="muted small">Seul le responsable de l'espace peut modifier ces informations.</p>}
      </form>

      <div className="card stack">
        <h2>Mon équipe</h2>
        <ul className="payments">
          {members.filter((m) => m.active).map((m) => (
            <li key={m.id}>
              <span><strong>{m.name}</strong>{m.id === me?.id ? " (vous)" : ""}<br /><span className="muted small">{m.login}, {ROLES[m.role].split(" :")[0].toLowerCase()}</span></span>
              {isAdmin && m.id !== me?.id && <button className="link danger" onClick={() => void remove(m)}>Retirer</button>}
            </li>
          ))}
        </ul>
        {isAdmin && (
          <form onSubmit={addMember} className="stack">
            <h2>Ajouter une personne</h2>
            <label>Nom<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
            <label>Téléphone ou e-mail<input value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} required inputMode="email" /></label>
            <label>
              Mot de passe provisoire
              <input value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={6} />
              <small className="muted">À lui communiquer. Elle pourra le changer avec « Mot de passe oublié ».</small>
            </label>
            <label>
              Rôle
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                {(["technicien", "ingenieur", "lecteur", "admin"] as Role[]).map((r) => <option key={r} value={r}>{ROLES[r]}</option>)}
              </select>
            </label>
            {memberError && (
              <p className="error">
                {memberError} {memberError.includes("Limite") && <button type="button" className="inline" onClick={() => go("/compte")}>Voir les offres</button>}
              </p>
            )}
            <button className="btn">Ajouter</button>
          </form>
        )}
      </div>
    </main>
  );
}
