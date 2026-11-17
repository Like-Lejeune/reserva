/**
 * Réglages du site vitrine. C'est le seul fichier à modifier pour personnaliser la page d'accueil.
 * Les offres et leurs prix, eux, viennent du serveur (backend/app/plans.py).
 */
export const BRAND = "Reserva";

/** Numéro WhatsApp commercial, chiffres seuls avec l'indicatif (ex. "237690000000"). Vide = pas de bouton de contact. */
export const CONTACT_WHATSAPP = "";

/**
 * Entreprises qui utilisent l'outil. La section « Ils nous font confiance » n'apparaît que si cette
 * liste contient au moins un nom : n'y mettre que de vrais clients, avec leur accord.
 * Exemple : [{ name: "Cabinet Exemple", logo: "/logos/exemple.svg" }]
 */
export const TRUSTED: { name: string; logo?: string }[] = [];

export const contactLink = (message: string) =>
  CONTACT_WHATSAPP ? `https://wa.me/${CONTACT_WHATSAPP}?text=${encodeURIComponent(message)}` : "";

/** Identité de l'éditeur, reprise dans les conditions d'utilisation et la politique de confidentialité. */
export const LEGAL = { company: "", address: "", email: "" };

/** Tant que c'est vrai, les pages légales affichent « modèle provisoire ». Passer à false après relecture par un juriste. */
export const LEGAL_DRAFT = true;
