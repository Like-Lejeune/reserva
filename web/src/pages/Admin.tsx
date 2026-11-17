import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { bytes, fcfa } from "../lib/types";

interface Day { date: string; count: number }
interface Overview {
  accounts: number; users: number; reports: number; defects: number; photos: number; storage_bytes: number;
  by_plan: Record<string, number>; monthly_revenue_fcfa: number; paying_accounts: number;
  collected_month_fcfa: number; collected_total_fcfa: number; pending_payments: number;
  ai: { calls: number; charged_fcfa: number; cost_fcfa: number; margin_fcfa: number; credit_sold_fcfa: number; credit_given_fcfa: number };
  signups_30d: Day[]; ai_calls_30d: Day[];
}
interface Account {
  id: string; name: string; owner: string; login: string; plan: string; plan_label: string; suspended: boolean;
  balance_fcfa: number; created_at: string; members: number; reports: number; storage_bytes: number;
  storage_limit_bytes: number | null; ai_spent_fcfa: number; plan_until: string | null; plan_source: string;
}
interface Pay {
  id: string; label: string; amount_fcfa: number; status: string; message: string; created_at: string;
  account: string; phone: string; operator: string; reference: string; promo_code: string;
}
interface Promo { code: string; percent_off: number; max_uses: number | null; used: number; expires_at: string | null; usable: boolean }

const PAY_STATUS: Record<string, string> = { reussi: "Payé", echoue: "Échoué", en_attente: "En attente" };
const SOURCES: Record<string, string> = { paiement: "payé", essai: "essai", admin: "accordé" };

const PLAN_LABELS: Record<string, string> = { gratuit: "Gratuit", pro: "Pro", equipe: "Équipe" };
const day = (iso: string) => new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short" });

/** Barres fines sur 30 jours, une seule série : le titre la nomme, le survol donne la valeur du jour. */
function Bars({ title, data, unit }: { title: string; data: Day[]; unit: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.count));
  const total = data.reduce((sum, d) => sum + d.count, 0);
  const shown = hover === null ? null : data[hover];
  return (
    <figure className="chart">
      <figcaption>
        <strong>{title}</strong>
        <span className="muted">{shown ? `${day(shown.date)} : ${shown.count} ${unit}` : `${total} ${unit} sur 30 jours`}</span>
      </figcaption>
      <div className="plot" onMouseLeave={() => setHover(null)}>
        <span className="ymax">{max}</span>
        {data.map((d, i) => (
          <button key={d.date} className={`col ${hover === i ? "on" : ""}`} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)} aria-label={`${day(d.date)} : ${d.count} ${unit}`}>
            <i className={d.count ? "" : "zero"} style={{ height: d.count ? `${Math.max(4, (100 * d.count) / max)}%` : undefined }} />
          </button>
        ))}
      </div>
      <div className="xaxis muted small"><span>{day(data[0].date)}</span><span>{day(data[data.length - 1].date)}</span></div>
    </figure>
  );
}

/** Administration de la plateforme : où en est l'activité, et la gestion de chaque compte. */
export function Admin() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [pays, setPays] = useState<Pay[]>([]);
  const [promos, setPromos] = useState<Promo[]>([]);
  const [promo, setPromo] = useState({ code: "", percent_off: "20", max_uses: "", valid_days: "" });
  const [q, setQ] = useState("");
  const [error, setError] = useState("");
  const [codeInfo, setCodeInfo] = useState("");

  const load = useCallback(async () => {
    try {
      const [o, a, p, c] = await Promise.all([
        api<Overview>("/admin/overview"), api<Account[]>(`/admin/accounts?q=${encodeURIComponent(q)}`),
        api<Pay[]>("/admin/payments"), api<Promo[]>("/admin/promos"),
      ]);
      setOverview(o);
      setAccounts(a);
      setPays(p);
      setPromos(c);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chargement impossible");
    }
  }, [q]);

  useEffect(() => {
    const t = setTimeout(() => void load(), 250);
    return () => clearTimeout(t);
  }, [load]);

  async function act(run: () => Promise<unknown>) {
    try {
      await run();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action impossible");
    }
  }

  // Offre accordée à la main (virement, geste) : on demande la durée. Elle ne compte pas comme revenu.
  const setPlan = (a: Account, plan: string) => {
    let months = 1;
    if (plan !== "gratuit") {
      const answer = window.prompt(`Durée de l'offre accordée à « ${a.name} », en mois (0 = sans échéance) :`, "1");
      if (answer === null) return;
      months = Math.max(0, Math.round(Number(answer) || 0));
    }
    void act(() => api(`/admin/accounts/${a.id}`, { method: "PATCH", json: { plan, months } }));
  };
  // Mot de passe oublié sans SMS ni e-mail : on génère un code à dicter après avoir vérifié l'identité.
  const resetCode = async (a: Account) => {
    if (!window.confirm(`Générer un code de réinitialisation pour « ${a.name} » ? À ne donner qu'après avoir vérifié qu'il s'agit bien du titulaire.`)) return;
    try {
      const res = await api<{ login: string; code: string; minutes: number }>(`/admin/accounts/${a.id}/reset-code`, { method: "POST" });
      setCodeInfo(`Code pour ${res.login} : ${res.code} (valable ${res.minutes} minutes)`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action impossible");
    }
  };
  const settlePay = (p: Pay, success: boolean) => {
    if (!window.confirm(`${success ? "Valider" : "Annuler"} le paiement de ${fcfa(p.amount_fcfa)} de « ${p.account} » ? À faire seulement après vérification chez TrustChange.`)) return;
    void act(() => api(`/admin/payments/${p.id}/settle`, { json: { success } }));
  };
  const addPromo = () =>
    act(async () => {
      await api("/admin/promos", {
        json: { code: promo.code.trim(), percent_off: Number(promo.percent_off), max_uses: promo.max_uses ? Number(promo.max_uses) : null,
                valid_days: promo.valid_days ? Number(promo.valid_days) : null },
      });
      setPromo({ code: "", percent_off: "20", max_uses: "", valid_days: "" });
    });
  const toggle = (a: Account) => {
    if (!a.suspended && !window.confirm(`Suspendre le compte « ${a.name} » ? Il ne pourra plus se connecter.`)) return;
    void act(() => api(`/admin/accounts/${a.id}`, { method: "PATCH", json: { suspended: !a.suspended } }));
  };
  const give = (a: Account) => {
    const amount = Number(window.prompt(`Crédit IA à offrir à « ${a.name} », en FCFA :`, "1000"));
    if (!amount || amount <= 0) return;
    void act(() => api(`/admin/accounts/${a.id}/credit`, { json: { amount_fcfa: Math.round(amount), note: "geste commercial" } }));
  };

  if (error && !overview) return <main className="wide"><h1>Administration</h1><p className="error">{error}</p></main>;
  if (!overview) return null;
  const o = overview;

  return (
    <main className="wide">
      <header className="top"><h1>Administration</h1></header>
      {error && <p className="error">{error}</p>}
      {codeInfo && <p className="notice">{codeInfo} <button className="inline" onClick={() => setCodeInfo("")}>Masquer</button></p>}

      <div className="tiles">
        <div className="tile"><span>Comptes</span><strong>{o.accounts}</strong><small>{o.users} utilisateurs</small></div>
        <div className="tile"><span>Encaissé ce mois</span><strong>{fcfa(o.collected_month_fcfa)}</strong>
          <small>{fcfa(o.collected_total_fcfa)} depuis le début</small></div>
        <div className="tile"><span>Revenu récurrent par mois</span><strong>{fcfa(o.monthly_revenue_fcfa)}</strong>
          <small>{o.paying_accounts} abonné(s) payant(s) ; {Object.entries(o.by_plan).map(([k, n]) => `${n} ${PLAN_LABELS[k] ?? k}`).join(", ")}</small></div>
        <div className="tile"><span>Rapports</span><strong>{o.reports}</strong><small>{o.defects} défauts, {o.photos} photos</small></div>
        <div className="tile"><span>Stockage utilisé</span><strong>{bytes(o.storage_bytes)}</strong><small>toutes offres confondues</small></div>
        <div className="tile"><span>IA facturée</span><strong>{fcfa(o.ai.charged_fcfa)}</strong>
          <small>coût {fcfa(o.ai.cost_fcfa)}, marge {fcfa(o.ai.margin_fcfa)}</small></div>
        <div className="tile"><span>Crédit IA vendu</span><strong>{fcfa(o.ai.credit_sold_fcfa)}</strong><small>{fcfa(o.ai.credit_given_fcfa)} offerts</small></div>
      </div>

      <div className="charts">
        <Bars title="Nouveaux comptes" data={o.signups_30d} unit="compte(s)" />
        <Bars title="Notes classées par l'IA" data={o.ai_calls_30d} unit="appel(s)" />
      </div>

      <div className="card stack">
        <div className="row between">
          <h2>Comptes</h2>
          <input className="search" placeholder="Chercher un nom ou un numéro" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Compte</th><th>Offre</th><th className="num">Rapports</th><th className="num">Stockage</th><th className="num">Crédit IA</th><th>Inscrit le</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id} className={a.suspended ? "off" : ""}>
                  <td><strong>{a.name}</strong><br /><span className="muted small">{a.login}{a.members > 1 ? `, ${a.members} membres` : ""}</span></td>
                  <td>
                    <select value={a.plan} onChange={(e) => void setPlan(a, e.target.value)} aria-label={`Offre de ${a.name}`}>
                      {Object.entries(PLAN_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                    <span className="muted small"><br />{a.plan === "gratuit" ? "" : a.plan_until ? `${SOURCES[a.plan_source] ?? ""} jusqu'au ${day(a.plan_until)}` : "sans échéance"}</span>
                  </td>
                  <td className="num">{a.reports}</td>
                  <td className="num">{bytes(a.storage_bytes)}{a.storage_limit_bytes ? <span className="muted small"><br />sur {bytes(a.storage_limit_bytes)}</span> : null}</td>
                  <td className="num">{fcfa(a.balance_fcfa)}<span className="muted small"><br />{fcfa(a.ai_spent_fcfa)} dépensés</span></td>
                  <td>{day(a.created_at)}</td>
                  <td>
                    <div className="actions">
                      <button className="btn small-btn" onClick={() => give(a)}>Offrir du crédit</button>
                      <button className="btn small-btn" onClick={() => void resetCode(a)}>Code mot de passe</button>
                      <button className="btn small-btn" onClick={() => toggle(a)}>{a.suspended ? "Réactiver" : "Suspendre"}</button>
                    </div>
                  </td>
                </tr>
              ))}
              {accounts.length === 0 && <tr><td colSpan={7} className="muted">Aucun compte ne correspond.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card stack">
        <div className="row between">
          <h2>Paiements</h2>
          <span className="muted">{o.pending_payments} en attente</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Date</th><th>Compte</th><th>Objet</th><th className="num">Montant</th><th>État</th><th>Actions</th></tr></thead>
            <tbody>
              {pays.map((p) => (
                <tr key={p.id}>
                  <td>{day(p.created_at)}</td>
                  <td><strong>{p.account}</strong><br /><span className="muted small">{p.phone}, {p.operator}</span></td>
                  <td>{p.label}{p.promo_code ? <span className="muted small"><br />code {p.promo_code}</span> : null}</td>
                  <td className="num">{fcfa(p.amount_fcfa)}</td>
                  <td><span className={`st-${p.status}`}>{PAY_STATUS[p.status] ?? p.status}</span>{p.message ? <span className="muted small"><br />{p.message}</span> : null}</td>
                  <td>
                    {p.status === "en_attente" && (
                      <div className="actions">
                        <button className="btn small-btn" onClick={() => settlePay(p, true)}>Valider</button>
                        <button className="btn small-btn" onClick={() => settlePay(p, false)}>Annuler</button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {pays.length === 0 && <tr><td colSpan={6} className="muted">Aucun paiement pour l'instant.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card stack">
        <h2>Codes promo</h2>
        <div className="inline-form">
          <label>Code<input value={promo.code} onChange={(e) => setPromo({ ...promo, code: e.target.value })} placeholder="LANCEMENT" /></label>
          <label>Remise en %<input value={promo.percent_off} onChange={(e) => setPromo({ ...promo, percent_off: e.target.value })} inputMode="numeric" /></label>
          <label>Utilisations max<input value={promo.max_uses} onChange={(e) => setPromo({ ...promo, max_uses: e.target.value })} inputMode="numeric" placeholder="Illimité" /></label>
          <label>Valable (jours)<input value={promo.valid_days} onChange={(e) => setPromo({ ...promo, valid_days: e.target.value })} inputMode="numeric" placeholder="Sans fin" /></label>
          <button className="btn primary" onClick={() => void addPromo()} disabled={promo.code.trim().length < 3}>Créer le code</button>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Code</th><th className="num">Remise</th><th className="num">Utilisé</th><th>Fin</th><th>État</th><th>Actions</th></tr></thead>
            <tbody>
              {promos.map((c) => (
                <tr key={c.code} className={c.usable ? "" : "off"}>
                  <td><strong>{c.code}</strong></td>
                  <td className="num">{c.percent_off} %</td>
                  <td className="num">{c.used}{c.max_uses ? ` sur ${c.max_uses}` : ""}</td>
                  <td>{c.expires_at ? day(c.expires_at) : "Sans fin"}</td>
                  <td>{c.usable ? "Utilisable" : "Inactif"}</td>
                  <td>{c.usable && <button className="btn small-btn" onClick={() => void act(() => api(`/admin/promos/${c.code}`, { method: "DELETE" }))}>Désactiver</button>}</td>
                </tr>
              ))}
              {promos.length === 0 && <tr><td colSpan={6} className="muted">Aucun code promo.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </main>
  );
}
