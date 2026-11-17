import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { go } from "../lib/nav";
import { BRAND, TRUSTED, contactLink } from "../lib/site";
import { fcfa, type Plan } from "../lib/types";

const STEPS = [
  ["Photographiez le défaut", "Ouvrez le rapport du chantier et prenez la photo. Pas de formulaire à remplir."],
  ["Dites ce qui ne va pas", "Une phrase, dictée ou tapée. Le corps de métier, le lieu et la gravité se remplissent tout seuls."],
  ["Envoyez le rapport", "Le PDF part par WhatsApp. Votre client et les artisans l'ouvrent sans créer de compte."],
];

const USES = [
  ["Technicien ou ingénieur indépendant", "Vous faites la visite seul et le client reçoit son rapport avant que vous ayez quitté le chantier."],
  ["Cabinet et bureau d'études", "Les techniciens relèvent les défauts sur plusieurs chantiers, l'ingénieur valide chaque correction photo à l'appui."],
  ["Entreprise de construction", "Avant la réception, vous faites votre propre tour, vous corrigez, et vous gardez la preuve avant et après."],
  ["Promoteur et maître d'ouvrage", "Vous suivez ce qui reste à corriger sur chaque logement avec un simple lien, sans rien installer."],
  ["Agence immobilière", "États des lieux d'entrée et de sortie, avec des photos datées que personne ne conteste."],
];

const FAQ = [
  ["Est-ce que ça marche sans réseau ?", "Oui. Vous continuez à prendre vos photos et vos notes sur le chantier. Tout est gardé sur le téléphone et envoyé dès que la connexion revient. Seul le PDF demande une connexion."],
  ["Que se passe-t-il quand la limite gratuite est atteinte ?", "Rien n'est perdu. Vous pouvez supprimer un ancien rapport pour libérer de la place, ou passer à une offre payante."],
  ["Comment l'assistance IA est-elle facturée ?", "À l'usage, sur un crédit en FCFA. Classer une note coûte une fraction de franc. Votre consommation est affichée dans votre compte, et sans crédit l'application continue de fonctionner."],
  ["Faut-il une formation ?", "Non. Si vous savez envoyer une photo sur WhatsApp, vous savez faire un rapport."],
];

export function Landing() {
  const [plans, setPlans] = useState<Plan[]>([]);
  useEffect(() => {
    api<Plan[]>("/plans").then(setPlans).catch(() => setPlans([]));
  }, []);
  const start = () => go("/inscription");

  return (
    <div className="site">
      <nav className="site-nav">
        <a href="#/" className="brand"><img src="/logo.svg" alt={BRAND} className="wordmark" /></a>
        <div className="site-links">
          <a href="#pour-qui" onClick={(e) => scrollTo(e, "pour-qui")}>Pour qui</a>
          <a href="#offres" onClick={(e) => scrollTo(e, "offres")}>Offres</a>
          <button className="link" onClick={() => go("/connexion")}>Se connecter</button>
          <button className="btn primary" onClick={start}>Commencer</button>
        </div>
      </nav>

      <header className="hero">
        <div className="hero-text">
          <h1>Le rapport de finition, terminé avant de quitter le chantier.</h1>
          <p>
            Une photo et une phrase par défaut. {BRAND} classe, numérote et met en page. Vous envoyez un PDF propre
            par WhatsApp, et vous suivez ce qui a été corrigé.
          </p>
          <div className="hero-cta">
            <button className="btn primary big" onClick={start}>Créer mon premier rapport</button>
            <span className="muted">Gratuit, sans carte bancaire. Prêt en une minute.</span>
          </div>
        </div>
        <Sheet />
      </header>

      <section className="band">
        <h2>Trois gestes, et le rapport est fait</h2>
        <ol className="steps">
          {STEPS.map(([title, text]) => (
            <li key={title}><h3>{title}</h3><p>{text}</p></li>
          ))}
        </ol>
      </section>

      <section id="pour-qui" className="band">
        <h2>Pour tous ceux qui livrent un bâtiment</h2>
        <dl className="uses">
          {USES.map(([who, what]) => (
            <div key={who}><dt>{who}</dt><dd>{what}</dd></div>
          ))}
        </dl>
      </section>

      {plans.length > 0 && (
        <section id="offres" className="band">
          <h2>Des offres simples</h2>
          <p className="lead">Commencez gratuitement, essayez Pro 14 jours sans payer. Paiement par Mobile Money, au mois ou à l'année avec 2 mois offerts.</p>
          <div className="plans">
            {plans.map((p) => {
              const contact = p.key === "entreprise" ? contactLink(`Bonjour, l'offre Entreprise de ${BRAND} m'intéresse.`) : "";
              return (
                <article key={p.key} className={p.recommended ? "plan featured" : "plan"}>
                  {p.recommended && <span className="badge">Recommandé</span>}
                  <h3>{p.label}</h3>
                  <p className="price">{p.price_fcfa === 0 ? "0 FCFA" : fcfa(p.price_fcfa)}</p>
                  <p className="muted small">{p.price_fcfa > 0 ? `par mois, ou ${fcfa(p.price_year_fcfa ?? p.price_fcfa * 10)} par an` : "Sans limite de durée"}</p>
                  <p className="muted">{p.tagline}</p>
                  <ul>{p.features.map((f) => <li key={f}>{f}</li>)}</ul>
                  {contact ? (
                    <a className="btn" href={contact}>Nous contacter</a>
                  ) : (
                    <button className={p.recommended ? "btn primary" : "btn"} onClick={start}>
                      {p.price_fcfa === 0 ? "Commencer" : "Essayer 14 jours"}
                    </button>
                  )}
                </article>
              );
            })}
          </div>
          {plans[0]?.details && (
            <div className="compare-wrap">
              <table className="compare">
                <caption>Ce que comprend chaque offre</caption>
                <thead>
                  <tr><th scope="col"><span className="sr">Fonction</span></th>{plans.map((p) => <th key={p.key} scope="col">{p.label}</th>)}</tr>
                </thead>
                <tbody>
                  {Object.keys(plans[0].details).map((row) => (
                    <tr key={row}>
                      <th scope="row">{row}</th>
                      {plans.map((p) => {
                        const v = p.details?.[row];
                        return (
                          <td key={p.key} className={p.recommended ? "hl" : ""}>
                            {v === true ? <span className="yes" aria-label="Inclus">✓</span> : v === false ? <span className="no" aria-label="Non inclus">—</span> : v}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted small">Au-delà de 20 utilisateurs, nous établissons un devis. Paiement par Mobile Money ; à l'échéance, sans renouvellement, le compte repasse en Gratuit et rien n'est supprimé.</p>
            </div>
          )}
        </section>
      )}

      {TRUSTED.length > 0 && (
        <section className="band">
          <h2>Ils nous font confiance</h2>
          <ul className="trusted">
            {TRUSTED.map((t) => (
              <li key={t.name}>{t.logo ? <img src={t.logo} alt={t.name} /> : t.name}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="band">
        <h2>Questions fréquentes</h2>
        <div className="faq">
          {FAQ.map(([q, a]) => (
            <details key={q}><summary>{q}</summary><p>{a}</p></details>
          ))}
        </div>
      </section>

      <section className="closing">
        <h2>Votre prochaine visite de chantier peut être la dernière faite au carnet.</h2>
        <button className="btn accent big" onClick={start}>Créer mon premier rapport</button>
      </section>

      <footer className="site-foot">
        <span>{BRAND}, rapports de finition assistés pour le bâtiment.</span>
        <span className="foot-links">
          <a href="#/cgu">Conditions d'utilisation</a>
          <a href="#/confidentialite">Confidentialité</a>
          <button className="link" onClick={() => go("/connexion")}>Se connecter</button>
        </span>
      </footer>
    </div>
  );
}

function scrollTo(e: React.MouseEvent, id: string) {
  e.preventDefault(); // l'adresse (#/...) sert déjà à la navigation de l'application
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
}

/** Le produit lui-même en vedette : une feuille de rapport, dont le premier défaut vient d'être corrigé. */
function Sheet() {
  return (
    <div className="sheet" aria-hidden="true">
      <div className="sheet-head">
        <strong>Rapport de finition</strong>
        <span>Villa Odza, Yaoundé</span>
      </div>
      <div className="sheet-bar"><div /></div>
      <ul>
        <li className="fixed">
          <span className="n">1</span>
          <div><b>Fuite sous l'évier de la cuisine</b><small>Plomberie, cuisine</small></div>
          <span className="stamp">Corrigé</span>
        </li>
        <li>
          <span className="n">2</span>
          <div><b>Coulures de peinture sur le mur du salon</b><small>Peinture, salon</small></div>
          <span className="todo">À corriger</span>
        </li>
        <li>
          <span className="n">3</span>
          <div><b>Prise manquante dans la chambre 2</b><small>Électricité, chambre 2</small></div>
          <span className="todo urgent">Urgent</span>
        </li>
      </ul>
      <div className="sheet-foot">1 sur 3 corrigé</div>
    </div>
  );
}
