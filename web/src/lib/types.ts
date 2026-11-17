export type Status = "ouverte" | "levee_declaree" | "levee" | "refusee";
export type Severity = "mineure" | "majeure" | "bloquante";
export type Role = "lecteur" | "technicien" | "ingenieur" | "admin";

export interface User {
  id: string;
  name: string;
  login: string;
  role: Role;
  is_staff?: boolean;
}

export interface Org {
  id: string;
  name: string;
  balance_fcfa: number;
  plan?: string;
  plan_label?: string;
  plan_until?: string | null;
}

export interface Session {
  token: string;
  user: User;
  org: Org;
}

/** Un rapport = un chantier. `dirty` : pas encore envoyé au serveur. */
export interface Project {
  id: string;
  name: string;
  client: string;
  location: string;
  created_at: string;
  dirty?: boolean;
  deleted?: boolean;
}

/** Un défaut constaté (une « réserve » dans le rapport PDF). */
export interface Defect {
  id: string;
  project_id: string;
  number: number; // 0 tant que le serveur ne l'a pas numéroté
  location: string;
  lot: string;
  description: string;
  action: string;
  severity: Severity;
  status: Status;
  transcript: string;
  updated_at: string;
  deleted?: boolean;
  dirty?: boolean;
  /** La note attend d'être classée par l'IA (lot, lieu, gravité) à la prochaine connexion. */
  needs_ai?: boolean;
}

export interface Photo {
  id: string;
  reserve_id: string;
  kind: "photo_avant" | "photo_apres";
  blob?: Blob; // absent tant que la photo d'un autre appareil n'a pas été téléchargée
  uploaded: boolean;
}

export const LOTS: Record<string, string> = {
  gros_oeuvre: "Gros œuvre",
  maconnerie: "Maçonnerie / enduits",
  etancheite: "Étanchéité / toiture",
  menuiserie_bois: "Menuiserie bois",
  menuiserie_alu: "Menuiserie alu / vitrerie",
  ferronnerie: "Ferronnerie",
  plomberie: "Plomberie",
  electricite: "Électricité",
  carrelage: "Carrelage",
  peinture: "Peinture",
  faux_plafond: "Faux plafond",
  climatisation: "Climatisation",
  vrd: "Extérieurs / VRD",
  nettoyage: "Nettoyage",
  autre: "Autre",
};

export const SEVERITIES: Record<Severity, string> = {
  mineure: "Mineur",
  majeure: "Important",
  bloquante: "Urgent",
};

// Mots simples à l'écran ; le PDF garde le vocabulaire officiel (réserve, levée).
export const STATUS_LABELS: Record<Status, string> = {
  ouverte: "À corriger",
  levee_declaree: "Corrigé, à vérifier",
  levee: "Corrigé",
  refusee: "À reprendre",
};

export const isDone = (s: Status) => s === "levee";

export interface Plan {
  key: string;
  label: string;
  price_fcfa: number;
  price_year_fcfa?: number;
  tagline: string;
  features: string[];
  recommended?: boolean;
  /** Tableau comparatif : pour chaque ligne, une coche (true), un tiret (false) ou un texte. */
  details?: Record<string, boolean | string>;
}

interface Meter {
  used: number;
  limit: number | null; // null = illimité
}
interface AiUse {
  calls: number;
  spent_fcfa: number;
  tokens: number;
  audio_minutes: number;
}
/** Compteurs de consommation affichés dans « Mon compte ». */
export interface Usage {
  plan: { key: string; label: string; price_fcfa: number };
  storage: { used_bytes: number; limit_bytes: number | null };
  reports: Meter;
  members: Meter;
  defects: number;
  defects_fixed: number;
  photos: number;
  subscription: { payments_enabled: boolean };
  ai: { balance_fcfa: number; month: AiUse; total: AiUse };
}

export const fcfa = (n: number) => `${Math.round(n).toLocaleString("fr-FR")} FCFA`;

export function bytes(n: number): string {
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} Go`;
  return `${(n / 1024 ** 2).toLocaleString("fr-FR", { maximumFractionDigits: n < 10 * 1024 ** 2 ? 1 : 0 })} Mo`;
}
