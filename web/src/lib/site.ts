/**
 * Réglages du site vitrine. C'est le seul fichier à modifier pour personnaliser la page d'accueil.
 * Les offres et leurs prix, eux, viennent du serveur (backend/app/plans.py).
 */
export const BRAND = "Reserva";

/** Numéro WhatsApp des boutons de contact, chiffres seuls avec l'indicatif. Vide = pas de bouton de contact. */
export const CONTACT_WHATSAPP = "237695249549";

/** Numéros affichés en pied de page (tous joignables sur WhatsApp), et adresse e-mail de contact. */
export const CONTACT_PHONES = [
  { label: "Orange", number: "695 249 549", whatsapp: "237695249549" },
  { label: "MTN", number: "675 659 936", whatsapp: "237675659936" },
];
export const CONTACT_EMAIL = "contact@psikalab.space";

/**
 * Entreprises qui utilisent l'outil. La section « Ils nous font confiance » n'apparaît que si cette
 * liste contient au moins un nom : n'y mettre que de vrais clients, avec leur accord.
 * Exemple : [{ name: "Cabinet Exemple", logo: "/logos/exemple.svg" }]
 */
export const TRUSTED: { name: string; logo?: string }[] = [];

export const contactLink = (message: string) =>
  CONTACT_WHATSAPP ? `https://wa.me/${CONTACT_WHATSAPP}?text=${encodeURIComponent(message)}` : "";

/** Identité de l'éditeur, reprise dans les conditions d'utilisation et la politique de confidentialité. */
export const LEGAL = { company: "PsikaLab", address: "Yaoundé, Cameroun", email: CONTACT_EMAIL };

/** Tant que c'est vrai, les pages légales affichent « modèle provisoire ». Passer à false après relecture par un juriste. */
export const LEGAL_DRAFT = true;
