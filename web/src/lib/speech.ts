/**
 * Dictée vocale gratuite : on utilise la reconnaissance vocale du téléphone (Chrome Android, Safari).
 * Si le navigateur ne la propose pas, le bouton micro n'apparaît pas et on tape la note.
 */
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start(): void;
  stop(): void;
}

const Ctor: (new () => Recognition) | undefined =
  (window as unknown as Record<string, new () => Recognition>).SpeechRecognition ??
  (window as unknown as Record<string, new () => Recognition>).webkitSpeechRecognition;

export const canDictate = !!Ctor;

/** Démarre l'écoute. Renvoie la fonction qui l'arrête. */
export function dictate(onText: (text: string) => void, onStop: () => void): () => void {
  if (!Ctor) return () => {};
  const rec = new Ctor();
  rec.lang = "fr-FR";
  rec.continuous = true;
  rec.interimResults = false;
  rec.onresult = (e) => {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) onText(e.results[i][0].transcript.trim());
    }
  };
  rec.onend = onStop;
  rec.onerror = onStop;
  rec.start();
  return () => rec.stop();
}
