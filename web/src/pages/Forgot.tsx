import { useState, type FormEvent } from "react";
import { api, setSession } from "../lib/api";
import { go } from "../lib/nav";
import { contactLink } from "../lib/site";
import type { Session } from "../lib/types";

/** Mot de passe oublié : on demande un code (SMS ou e-mail), puis on choisit un nouveau mot de passe. */
export function Forgot() {
  const [step, setStep] = useState<"ask" | "code">("ask");
  const [login, setLogin] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [delivery, setDelivery] = useState("");
  const [minutes, setMinutes] = useState(15);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Une erreur est survenue");
    } finally {
      setBusy(false);
    }
  }

  const ask = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const res = await api<{ delivery: string; minutes: number }>("/auth/forgot", { json: { login } });
      setDelivery(res.delivery);
      setMinutes(res.minutes);
      setStep("code");
    });
  };

  const reset = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const session = await api<Session>("/auth/reset", { json: { login, code, password } });
      go("/");
      setSession(session);
    });
  };

  const help = contactLink(`Bonjour, j'ai oublié mon mot de passe Reserva. Mon identifiant : ${login}`);

  return (
    <main className="login">
      <h1>Mot de passe oublié</h1>
      {step === "ask" ? (
        <form onSubmit={ask} className="card stack">
          <label>
            Téléphone ou e-mail du compte
            <input value={login} onChange={(e) => setLogin(e.target.value)} required autoComplete="username" inputMode="email" />
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn primary" disabled={busy}>{busy ? "Un instant…" : "Recevoir un code"}</button>
        </form>
      ) : (
        <form onSubmit={reset} className="card stack">
          <p className="notice">
            {delivery === "sms" && `Si ce numéro a un compte, un code vient d'y être envoyé par SMS. Il est valable ${minutes} minutes.`}
            {delivery === "email" && `Si cette adresse a un compte, un code vient d'y être envoyé. Il est valable ${minutes} minutes.`}
            {delivery === "aucun" && "L'envoi automatique du code n'est pas encore disponible. Contactez-nous : nous vous donnerons un code après vérification."}
          </p>
          {delivery === "aucun" && help && <a className="btn" href={help}>Nous contacter sur WhatsApp</a>}
          <label>
            Code à 6 chiffres
            <input value={code} onChange={(e) => setCode(e.target.value)} required inputMode="numeric" autoComplete="one-time-code" maxLength={8} />
          </label>
          <label>
            Nouveau mot de passe
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} autoComplete="new-password" />
            <small className="muted">6 caractères minimum</small>
          </label>
          {error && <p className="error">{error}</p>}
          <button className="btn primary" disabled={busy}>{busy ? "Un instant…" : "Changer mon mot de passe"}</button>
          <button type="button" className="link" onClick={() => (setStep("ask"), setError(""))}>Demander un nouveau code</button>
        </form>
      )}
      <button className="link quiet" onClick={() => go("/connexion")}>Retour à la connexion</button>
    </main>
  );
}
