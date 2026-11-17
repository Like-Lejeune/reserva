import { useEffect, useState } from "react";
import { getSession } from "./lib/api";
import { go } from "./lib/nav";
import { BRAND } from "./lib/site";
import { sync, useSyncState } from "./lib/store";
import { Account } from "./pages/Account";
import { AddDefect } from "./pages/AddDefect";
import { Artisans } from "./pages/Artisans";
import { Forgot } from "./pages/Forgot";
import { Legal } from "./pages/Legal";
import { Workspace } from "./pages/Workspace";
import { Admin } from "./pages/Admin";
import { DefectPage } from "./pages/DefectPage";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { Report } from "./pages/Report";
import { Reports } from "./pages/Reports";

function useHash(): string[] {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const l = () => setHash(window.location.hash);
    window.addEventListener("hashchange", l);
    return () => window.removeEventListener("hashchange", l);
  }, []);
  return hash.replace(/^#\/?/, "").split("/").filter(Boolean);
}

/** Jours avant la fin de l'offre payante (null = pas d'échéance). */
function daysLeft(until?: string | null): number | null {
  if (!until) return null;
  return Math.max(0, Math.floor((new Date(until).getTime() - Date.now()) / 86_400_000));
}

function SyncBar() {
  const s = useSyncState();
  const org = getSession()?.org;
  const left = daysLeft(org?.plan_until);
  if (s.limit)
    return (
      <div className="syncbar warn">
        {s.limit} <button className="inline" onClick={() => go("/compte")}>Voir les offres</button>
      </div>
    );
  if (s.error) return <div className="syncbar warn">{s.error}</div>;
  if (!s.online)
    return (
      <div className="syncbar">
        Hors connexion{s.pending ? `, ${s.pending} élément(s) seront envoyés au retour du réseau` : ", vous pouvez continuer"}
      </div>
    );
  if (s.syncing) return <div className="syncbar">Envoi en cours…</div>;
  if (left !== null && left <= 7)
    return (
      <div className="syncbar soon">
        Votre offre {org?.plan_label} se termine {left === 0 ? "aujourd'hui" : `dans ${left} jour${left > 1 ? "s" : ""}`}.{" "}
        <button className="inline" onClick={() => go("/compte")}>Renouveler</button>
      </div>
    );
  return null;
}

/**
 * Trois espaces dans le même site :
 * - visiteur : le site vitrine, puis l'inscription ;
 * - utilisateur : ses rapports (colonne de navigation sur ordinateur, plein écran sur téléphone) ;
 * - équipe de la plateforme : l'administration.
 */
export function App() {
  const [session, setSession] = useState(getSession());
  const route = useHash();

  useEffect(() => {
    const l = () => setSession(getSession());
    window.addEventListener("reserva:session", l);
    return () => window.removeEventListener("reserva:session", l);
  }, []);

  useEffect(() => {
    if (!session) return;
    void sync();
    const timer = setInterval(() => void sync(), 60_000);
    return () => clearInterval(timer);
  }, [session?.token]); // eslint-disable-line react-hooks/exhaustive-deps

  if (route[0] === "cgu") return <Legal doc="cgu" />;
  if (route[0] === "confidentialite") return <Legal doc="confidentialite" />;

  if (!session) {
    if (route[0] === "mot-de-passe") return <Forgot />;
    if (route[0] === "connexion") return <Login mode="login" />;
    if (route[0] === "inscription") return <Login mode="register" />;
    return <Landing />;
  }

  const staff = !!session.user.is_staff;
  let page;
  let section = "rapports";
  if (route[0] === "r" && route[1] && route[2] === "ajouter") page = <AddDefect projectId={route[1]} />;
  else if (route[0] === "r" && route[1] && route[2] === "artisans") page = <Artisans projectId={route[1]} />;
  else if (route[0] === "r" && route[1]) page = <Report projectId={route[1]} />;
  else if (route[0] === "espace") (page = <Workspace />), (section = "compte");
  else if (route[0] === "d" && route[1]) page = <DefectPage defectId={route[1]} />;
  else if (route[0] === "compte") (page = <Account />), (section = "compte");
  else if (route[0] === "admin" && staff) (page = <Admin />), (section = "admin");
  else page = <Reports />;

  const item = (key: string, path: string, label: string) => (
    <button className={section === key ? "on" : ""} onClick={() => go(path)}>{label}</button>
  );

  return (
    <div className="shell">
      <aside className="side">
        <a href="#/" className="brand"><img src="/icon.svg" alt="" />{BRAND}</a>
        <nav>
          {item("rapports", "/", "Mes rapports")}
          {item("compte", "/compte", "Mon compte")}
          {staff && item("admin", "/admin", "Administration")}
        </nav>
        <div className="side-foot">
          <strong>{session.user.name}</strong>
          <span>Offre {session.org.plan_label ?? "Gratuit"}</span>
        </div>
      </aside>
      <div className="content">
        <SyncBar />
        {page}
      </div>
    </div>
  );
}
