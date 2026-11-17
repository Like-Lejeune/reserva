import { go } from "../lib/nav";
import { BRAND, LEGAL, LEGAL_DRAFT } from "../lib/site";

const blank = (value: string, what: string) => value || `[${what} à compléter]`;

type Section = [title: string, paragraphs: string[]];

/** Conditions d'utilisation. Modèle de départ : à faire relire par un juriste avant la mise en ligne. */
const TERMS: Section[] = [
  ["Objet", [
    `${BRAND} est un service en ligne qui aide à établir des rapports de finition de chantier : relevé des défauts avec photos, mise en page d'un rapport PDF, suivi des corrections. Il est édité par ${blank(LEGAL.company, "raison sociale")}, ${blank(LEGAL.address, "adresse")}.`,
    "Créer un compte vaut acceptation des présentes conditions.",
  ]],
  ["Compte", [
    "Le compte est créé avec un nom, un numéro de téléphone ou une adresse e-mail, et un mot de passe. Vous êtes responsable de la confidentialité de votre mot de passe et de l'usage fait de votre compte.",
    "Dans un espace d'équipe, le responsable de l'espace ajoute et retire les membres et choisit leur rôle.",
  ]],
  ["Offres et paiement", [
    "L'offre gratuite est limitée en nombre de rapports et en espace de stockage. Les offres payantes, leurs prix et leurs limites sont ceux affichés sur le site au moment du paiement.",
    "Le paiement se fait par Mobile Money, pour un mois ou un an. Il n'y a pas de prélèvement automatique : à l'échéance, sans nouveau paiement, le compte repasse à l'offre gratuite. Aucune donnée n'est supprimée à cette occasion ; seules les limites de l'offre gratuite s'appliquent aux nouveaux ajouts.",
    "L'assistance par intelligence artificielle est facturée à l'usage sur un crédit prépayé, dont le détail de consommation est consultable dans le compte.",
    "[Politique de remboursement à définir.]",
  ]],
  ["Vos contenus", [
    "Les rapports, photos et notes que vous enregistrez vous appartiennent. Vous nous autorisez seulement à les stocker et à les traiter pour vous fournir le service.",
    "Vous garantissez avoir le droit d'enregistrer ces contenus, notamment les photos prises chez vos clients et les coordonnées des artisans.",
    "Le lien de partage d'un rapport permet à toute personne qui le détient de consulter ce rapport pendant 30 jours. Ne le transmettez qu'aux personnes concernées.",
  ]],
  ["Votre responsabilité professionnelle", [
    `${BRAND} est un outil d'aide. Le classement proposé automatiquement (corps de métier, lieu, gravité, travail à faire) peut être erroné : il vous appartient de le vérifier avant d'envoyer un rapport.`,
    "Vous restez seul responsable du contenu des rapports que vous émettez, de leur exactitude et de leurs conséquences contractuelles.",
  ]],
  ["Usage interdit", [
    "Il est interdit d'utiliser le service pour enregistrer des contenus illicites, de tenter d'accéder aux données d'autres utilisateurs, ou de perturber son fonctionnement. Un compte peut être suspendu en cas de manquement.",
  ]],
  ["Disponibilité", [
    "Nous faisons notre possible pour que le service soit disponible, sans pouvoir le garantir en permanence. L'application permet de continuer à travailler sans connexion ; les données sont envoyées au retour du réseau.",
  ]],
  ["Fin du service et modifications", [
    "Vous pouvez cesser d'utiliser le service à tout moment et demander la suppression de votre compte. Ces conditions peuvent évoluer ; les utilisateurs sont informés des changements importants.",
    "Droit applicable et tribunaux compétents : [à compléter].",
  ]],
];

/** Politique de confidentialité. Décrit ce que l'application fait réellement des données. */
const PRIVACY: Section[] = [
  ["Qui est responsable de vos données", [
    `${blank(LEGAL.company, "Raison sociale")}, ${blank(LEGAL.address, "adresse")}. Contact : ${blank(LEGAL.email, "adresse e-mail de contact")}.`,
  ]],
  ["Les données que nous enregistrons", [
    "Votre compte : nom, numéro de téléphone ou adresse e-mail, mot de passe (enregistré sous forme chiffrée irréversible, jamais en clair).",
    "Vos rapports : noms de chantiers et de clients, descriptions des défauts, lieux, photos, statuts de correction, ainsi que les noms et numéros des artisans que vous ajoutez.",
    "Vos paiements : montant, date, opérateur et numéro Mobile Money utilisé. Nous ne recevons ni ne conservons aucun code secret de paiement.",
    "Votre consommation : espace de stockage utilisé, nombre de rapports, appels à l'assistance par intelligence artificielle et leur coût.",
    "Votre logo et vos coordonnées professionnelles, si vous les renseignez.",
  ]],
  ["À quoi elles servent", [
    "À fournir le service : enregistrer vos rapports, produire les PDF, synchroniser vos appareils, gérer votre abonnement et votre crédit, vous prévenir d'une échéance, et protéger votre compte contre les accès frauduleux.",
    "Nous ne vendons pas vos données et ne les utilisons pas à des fins publicitaires.",
  ]],
  ["Qui d'autre y a accès", [
    "Le prestataire de paiement Mobile Money reçoit le numéro et le montant, pour exécuter le paiement.",
    "Lorsque l'assistance par intelligence artificielle est activée, le texte de vos notes est transmis à un fournisseur de modèles pour être classé. Vos photos ne lui sont pas transmises.",
    "La dictée vocale utilise la reconnaissance vocale de votre téléphone ou de votre navigateur, fournie par son éditeur.",
    "L'hébergeur du service stocke les données pour notre compte.",
    "Toute personne à qui vous transmettez le lien de partage d'un rapport peut consulter ce rapport pendant 30 jours.",
  ]],
  ["Où elles sont conservées et combien de temps", [
    "Sur votre appareil, pour vous permettre de travailler sans connexion, et sur nos serveurs. [Pays d'hébergement à compléter.]",
    "Vos données sont conservées tant que votre compte existe. Supprimer un rapport ou un défaut supprime aussi ses photos. Des sauvegardes sont conservées [durée à compléter].",
  ]],
  ["Vos droits", [
    `Vous pouvez consulter et corriger vos informations dans l'application, et demander l'accès à vos données, leur rectification ou la suppression de votre compte en écrivant à ${blank(LEGAL.email, "adresse e-mail de contact")}.`,
    "Ces droits s'exercent dans le cadre de la législation applicable en matière de protection des données personnelles.",
  ]],
];

export function Legal({ doc }: { doc: "cgu" | "confidentialite" }) {
  const terms = doc === "cgu";
  const sections = terms ? TERMS : PRIVACY;
  return (
    <div className="site">
      <nav className="site-nav">
        <a href="#/" className="brand"><img src="/logo.svg" alt={BRAND} className="wordmark" /></a>
        <div className="site-links">
          <button className="link" onClick={() => go(terms ? "/confidentialite" : "/cgu")}>{terms ? "Confidentialité" : "Conditions d'utilisation"}</button>
        </div>
      </nav>
      <article className="legal">
        <h1>{terms ? "Conditions d'utilisation" : "Politique de confidentialité"}</h1>
        {LEGAL_DRAFT && (
          <p className="notice">
            Modèle provisoire. Ce texte doit être complété et relu par un juriste avant l'ouverture du service au public.
          </p>
        )}
        {sections.map(([title, paragraphs], i) => (
          <section key={title}>
            <h2>{i + 1}. {title}</h2>
            {paragraphs.map((p) => <p key={p}>{p}</p>)}
          </section>
        ))}
      </article>
    </div>
  );
}
