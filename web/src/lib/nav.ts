/** Navigation par l'adresse (#/...) : le bouton retour du téléphone fonctionne normalement. */
export const go = (path: string) => {
  window.location.hash = path;
};

export const back = (fallback: string) => {
  if (window.history.length > 1) window.history.back();
  else go(fallback);
};
