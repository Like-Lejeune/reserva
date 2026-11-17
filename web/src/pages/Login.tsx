import { useState, type FormEvent } from "react";
import { api, setSession } from "../lib/api";
import { go } from "../lib/nav";
import { BRAND } from "../lib/site";
import type { Session } from "../lib/types";

/** Un seul écran : trois champs pour créer un compte, deux pour se connecter. */
export function Login({ mode }: { mode: "login" | "register" }) {
  const creating = mode === "register";
  const [name, setName] = useState("");
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session = await api<Session>(creating ? "/auth/register" : "/auth/login", {
        json: creating ? { name, login, password } : { login, password },
      });
      go("/");
      setSession(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Une erreur est survenue");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <img src="/icon.svg" alt="" className="logo" />
      <h1>{BRAND}</h1>
      <p className="muted">Vos rapports de finition, en quelques photos.</p>
      <form onSubmit={submit} className="card stack">
        {creating && (
          <label>
            Votre nom
            <input value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
          </label>
        )}
        <label>
          Téléphone ou e-mail
          <input value={login} onChange={(e) => setLogin(e.target.value)} required autoComplete="username" inputMode="email" />
        </label>
        <label>
          Mot de passe
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
            autoComplete={creating ? "new-password" : "current-password"}
          />
          {creating && <small className="muted">6 caractères minimum</small>}
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn primary" disabled={busy}>
          {busy ? "Un instant…" : creating ? "Commencer" : "Se connecter"}
        </button>
      </form>
      <button className="link" onClick={() => (setError(""), go(creating ? "/connexion" : "/inscription"))}>
        {creating ? "J'ai déjà un compte" : "Créer un compte"}
      </button>
      {!creating && <button className="link" onClick={() => go("/mot-de-passe")}>Mot de passe oublié ?</button>}
      {creating && (
        <p className="muted small">
          En créant un compte, vous acceptez les <a href="#/cgu">conditions d'utilisation</a> et la{" "}
          <a href="#/confidentialite">politique de confidentialité</a>.
        </p>
      )}
      <button className="link quiet" onClick={() => go("/")}>Retour à l'accueil</button>
    </main>
  );
}
