import { useCallback, useEffect, useState } from "react";
import { api, getSession } from "../lib/api";
import { go } from "../lib/nav";
import { logout, sync, useSyncState } from "../lib/store";
import { bytes, fcfa, type Plan, type Usage } from "../lib/types";
import { SubscriptionCard, Topup } from "./Subscription";

/** Une jauge : ce qui est utilisé, sur ce qui est permis. Passe à l'orange à 80 %, au rouge à 100 %. */
function Meter({ label, used, limit, format = String }: { label: string; used: number; limit: number | null; format?: (n: number) => string }) {
  const ratio = limit ? Math.min(1, used / limit) : 0;
  const level = ratio >= 1 ? "full" : ratio >= 0.8 ? "high" : "";
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <strong>{format(used)}{limit ? ` sur ${format(limit)}` : ""}</strong>
      </div>
      {limit ? <div className={`bar ${level}`}><div style={{ width: `${Math.max(2, ratio * 100)}%` }} /></div> : <span className="muted small">Illimité</span>}
      {level === "full" && <span className="error small">Limite atteinte</span>}
    </div>
  );
}

/** Mon compte : mon offre, mes compteurs de consommation, les autres offres, me déconnecter. */
export function Account() {
  const session = getSession();
  const { pending, online } = useSyncState();
  const [usage, setUsage] = useState<Usage | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);

  const reload = useCallback(() => {
    api<Usage>("/account/usage").then(setUsage).catch(() => setUsage(null));
    api<Plan[]>("/plans").then(setPlans).catch(() => setPlans([]));
    void sync(); // met à jour l'offre affichée partout (colonne, bandeau)
  }, []);
  useEffect(() => {
    api<Usage>("/account/usage").then(setUsage).catch(() => setUsage(null));
    api<Plan[]>("/plans").then(setPlans).catch(() => setPlans([]));
  }, [pending]);

  if (!session) return null;

  function quit() {
    if (pending && !window.confirm(`${pending} élément(s) ne sont pas encore envoyés. Ils resteront sur cet appareil. Se déconnecter ?`)) return;
    logout();
    go("/");
  }

  return (
    <main>
      <header className="top">
        <button className="back" onClick={() => go("/")} aria-label="Retour">‹</button>
        <h1>Mon compte</h1>
      </header>

      <div className="card stack">
        <div className="row between">
          <div className="grow">
            <strong>{session.user.name}</strong>
            <span className="muted">{session.user.login}</span>
          </div>
          <span className="chip plan-chip">Offre {usage?.plan.label ?? session.org.plan_label ?? "Gratuit"}</span>
        </div>
      </div>

      {usage ? (
        <>
          <div className="card stack">
            <h2>Ma consommation</h2>
            <Meter label="Photos stockées" used={usage.storage.used_bytes} limit={usage.storage.limit_bytes} format={bytes} />
            <Meter label="Rapports" used={usage.reports.used} limit={usage.reports.limit} />
            {(usage.members.limit ?? 2) > 1 && <Meter label="Membres" used={usage.members.used} limit={usage.members.limit} />}
            <div className="stats">
              <div><strong>{usage.defects}</strong><span>défauts notés</span></div>
              <div><strong>{usage.defects_fixed}</strong><span>corrigés</span></div>
              <div><strong>{usage.photos}</strong><span>photos</span></div>
            </div>
          </div>

          <div className="card stack">
            <h2>Assistance IA</h2>
            <div className="meter-head">
              <span>Crédit restant</span>
              <strong className="balance">{fcfa(Math.max(0, usage.ai.balance_fcfa))}</strong>
            </div>
            <div className="stats">
              <div><strong>{usage.ai.month.calls}</strong><span>notes classées ce mois</span></div>
              <div><strong>{usage.ai.month.spent_fcfa.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} F</strong><span>dépensés ce mois</span></div>
              <div><strong>{usage.ai.total.spent_fcfa.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} F</strong><span>depuis le début</span></div>
            </div>
            <span className="muted small">
              Le crédit sert quand l'IA classe vos notes. À zéro, l'application continue de fonctionner avec un classement plus simple.
            </span>
            <Topup enabled={usage.subscription.payments_enabled} onPaid={reload} />
          </div>
        </>
      ) : (
        <p className="muted">{online ? "Chargement de votre consommation…" : "Vos compteurs s'afficheront au retour de la connexion."}</p>
      )}

      {plans.length > 0 && usage && <SubscriptionCard plans={plans} onChange={reload} />}

      <button className="btn" onClick={() => go("/espace")}>Mon espace : logo, coordonnées, équipe</button>
      {session.user.is_staff && <button className="btn" onClick={() => go("/admin")}>Administration de la plateforme</button>}
      <button className="btn" onClick={quit}>Se déconnecter</button>
    </main>
  );
}
