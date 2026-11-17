import { useRef, useState } from "react";
import { back } from "../lib/nav";
import { canDictate, dictate } from "../lib/speech";
import { addPhoto, newDefect, saveDefect } from "../lib/store";

/**
 * Ajouter un défaut : une photo, une phrase (dictée ou tapée), Enregistrer.
 * Le lot, le lieu, la gravité et le travail à faire sont remplis par l'IA à l'envoi ; tout reste modifiable.
 */
export function AddDefect({ projectId }: { projectId: string }) {
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [note, setNote] = useState("");
  const [listening, setListening] = useState(false);
  const [saving, setSaving] = useState(false);
  const stop = useRef<() => void>(() => {});
  const camera = useRef<HTMLInputElement>(null);

  function pick(file?: File) {
    if (!file) return;
    if (preview) URL.revokeObjectURL(preview);
    setPhoto(file);
    setPreview(URL.createObjectURL(file));
  }

  function toggleMic() {
    if (listening) return stop.current();
    setListening(true);
    stop.current = dictate(
      (text) => setNote((n) => (n ? `${n} ${text}` : text)),
      () => setListening(false),
    );
  }

  async function save(another: boolean) {
    if (!photo && !note.trim()) return;
    setSaving(true);
    stop.current();
    const d = newDefect(projectId);
    d.transcript = note.trim();
    d.description = note.trim();
    d.needs_ai = !!note.trim();
    await saveDefect(d);
    if (photo) await addPhoto(d.id, "photo_avant", photo);
    if (another) {
      if (preview) URL.revokeObjectURL(preview);
      setPhoto(null);
      setPreview("");
      setNote("");
      setSaving(false);
    } else back(`/r/${projectId}`);
  }

  const empty = !photo && !note.trim();

  return (
    <main>
      <header className="top">
        <button className="back" onClick={() => back(`/r/${projectId}`)} aria-label="Retour">‹</button>
        <h1>Nouveau défaut</h1>
      </header>

      <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={(e) => pick(e.target.files?.[0])} />
      <button className={`photo-zone ${preview ? "has" : ""}`} onClick={() => camera.current?.click()}>
        {preview ? <img src={preview} alt="" /> : <span>📷<br />Prendre la photo</span>}
      </button>

      <label>
        Qu'est-ce qui ne va pas ?
        <textarea
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Ex. Fuite sous l'évier de la cuisine"
        />
      </label>
      {canDictate && (
        <button className={`btn ${listening ? "rec" : ""}`} onClick={toggleMic}>
          {listening ? "■ Arrêter la dictée" : "🎤 Dicter"}
        </button>
      )}
      <p className="muted small">Le corps de métier, le lieu et la gravité sont remplis automatiquement. Vous pourrez les corriger.</p>

      <div className="stack">
        <button className="btn primary big" onClick={() => save(false)} disabled={empty || saving}>Enregistrer</button>
        <button className="btn" onClick={() => save(true)} disabled={empty || saving}>Enregistrer et ajouter un autre</button>
      </div>
    </main>
  );
}
