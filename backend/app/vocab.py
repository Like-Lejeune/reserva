"""Vocabulaire métier : lots, gravités, statuts, et mots-clés pour le classement hors ligne."""

LOTS: dict[str, str] = {
    "gros_oeuvre": "Gros œuvre",
    "maconnerie": "Maçonnerie / enduits",
    "etancheite": "Étanchéité / toiture",
    "menuiserie_bois": "Menuiserie bois",
    "menuiserie_alu": "Menuiserie alu / vitrerie",
    "ferronnerie": "Ferronnerie / métallerie",
    "plomberie": "Plomberie / sanitaire",
    "electricite": "Électricité",
    "carrelage": "Carrelage / revêtements",
    "peinture": "Peinture",
    "faux_plafond": "Faux plafond / staff",
    "climatisation": "Climatisation / ventilation",
    "vrd": "VRD / aménagements extérieurs",
    "nettoyage": "Nettoyage",
    "autre": "Autre",
}

SEVERITIES = {"mineure": "Mineure", "majeure": "Majeure", "bloquante": "Bloquante"}

# ouverte -> levee_declaree (l'entreprise dit avoir corrigé) -> levee (validée) | refusee -> ouverte
STATUSES = {
    "ouverte": "Ouverte",
    "levee_declaree": "Levée déclarée",
    "levee": "Levée",
    "refusee": "Levée refusée",
}
TRANSITIONS: dict[str, set[str]] = {
    "ouverte": {"levee_declaree", "levee"},
    "levee_declaree": {"levee", "refusee"},
    "refusee": {"levee_declaree", "levee"},
    "levee": {"ouverte"},
}

VISIT_KINDS = {"opr": "Opérations préalables à la réception", "reception": "Réception", "levee": "Levée de réserves"}

# Mots-clés (sans accents, minuscules) -> lot. Utilisé par le classeur hors ligne.
LOT_KEYWORDS: dict[str, list[str]] = {
    "plomberie": ["robinet", "fuite", "tuyau", "siphon", "wc", "lavabo", "evier", "douche", "chasse",
                  "evacuation", "plomberie", "sanitaire", "chauffe-eau", "regard"],
    "electricite": ["prise", "interrupteur", "disjoncteur", "cable", "ampoule", "luminaire", "tableau",
                    "electri", "applique", "goulotte", "spot"],
    "carrelage": ["carreau", "carrelage", "faience", "joint", "plinthe", "chape", "revetement"],
    "peinture": ["peinture", "coulure", "retouche", "couche", "ecaill", "tache", "badigeon"],
    "menuiserie_bois": ["porte", "placard", "serrure", "poignee", "charniere", "huisserie", "bois"],
    "menuiserie_alu": ["fenetre", "vitre", "baie", "alu", "coulissant", "moustiquaire", "vitrage"],
    "ferronnerie": ["grille", "garde-corps", "portail", "rampe", "soudure", "antivol", "ferronnerie"],
    "etancheite": ["etancheite", "infiltration", "toiture", "tole", "gouttiere", "terrasse", "humidite"],
    "maconnerie": ["enduit", "crepi", "mur", "agglo", "parpaing", "appui", "seuil"],
    "gros_oeuvre": ["fissure", "poteau", "poutre", "dalle", "beton", "ferraillage", "linteau", "structure"],
    "faux_plafond": ["plafond", "staff", "dalle de plafond", "corniche"],
    "climatisation": ["clim", "split", "vmc", "ventilation", "extracteur"],
    "vrd": ["caniveau", "pave", "cloture", "fosse", "puisard", "voirie", "parking"],
    "nettoyage": ["gravats", "nettoyage", "salete", "dechets", "poussiere"],
}

SEVERITY_KEYWORDS: dict[str, list[str]] = {
    "bloquante": ["danger", "dangereux", "structure", "effondr", "court-circuit", "inondation", "bloquant",
                  "fil denude", "risque"],
    "majeure": ["fuite", "infiltration", "fissure", "ne fonctionne pas", "casse", "manquant", "absent",
                "hors service", "ne ferme pas"],
}

ROOM_KEYWORDS = ["salon", "sejour", "cuisine", "chambre", "salle de bain", "douche", "wc", "toilettes",
                 "couloir", "hall", "balcon", "terrasse", "escalier", "garage", "buanderie", "bureau",
                 "magasin", "toiture", "facade", "cour", "sous-sol", "rez-de-chaussee", "etage"]
