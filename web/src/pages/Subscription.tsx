import { useCallback, useEffect, useRef, useState } from "react";
import { api, getSession } from "../lib/api";
import { contactLink } from "../lib/site";
import { fcfa, type Plan } from "../lib/types";

export interface Sub {
  plan: string; plan_label: string; paid: boolean; source: string; period: string;
  until: string | null; days_left: number | null; expires_soon: boolean;
  trial_available: boolean; trial_days: number; payments_enabled: boolean;
  payments: PaymentRow[];
}
interface PaymentRow { id: string; kind: string; label: string; amount_fcfa: number; status: string; message: string; created_at: string }
interface Operator { code: string; name: string }
interface Quote {
  plan_label: string; period_label: string; base_fcfa: number; discount_fcfa: number; promo_code: string;
  prorata_fcfa: number; amount_fcfa: number; renewal: boolean; starts_at: string; ends_at: string;
}

const date = (iso: string) => new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
const STATUS: Record<string, string> = { reussi: "Payé", echoue: "Échoué", en_attente: "En attente" };

/**
 * Suit un paiement Mobile Money : après l'envoi, l'utilisateur valide sur son téléphone ;
 * on interroge le serveur toutes les 3 secondes jusqu'à la réponse (3 minutes au plus).
 */
function usePayment(onPaid: () => void) {
  const [state, setState] = useState<{ phase: "idle" | "sending" | "waiting" | "paid" | "failed"; message: string }>({ phase: "idle", message: "" });
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const follow = useCallback((id: string, tries: number) => {
    timer.current = window.setTimeout(async () => {
      try {
        const p = await api<PaymentRow>(`/payments/${id}`);
        if (p.status === "reussi") return setState({ phase: "paid", message: "Paiement reçu. Merci !" }), onPaid();
        if (p.status === "echoue") return setState({ phase: "failed", message: p.message || "Le paiement n'a pas abouti." });
      } catch {
        /* réseau instable : on réessaie */
      }
      if (tries >= 60) return setState({ phase: "failed", message: "Pas encore de confirmation. Si vous avez validé, l'offre s'activera toute seule dans quelques minutes." });
      follow(id, tries + 1);
    }, 3000);
  }, [onPaid]);

  const pay = useCallback(async (path: string, body: unknown) => {
    setState({ phase: "sending", message: "" });
    try {
      const p = await api<PaymentRow>(path, { json: body });
      if (p.status === "reussi") return setState({ phase: "paid", message: "Paiement reçu. Merci !" }), onPaid();
      if (p.status === "echoue") return setState({ phase: "failed", message: p.message || "Le paiement n'a pas abouti." });
      setState({ phase: "waiting", message: "" });
      follow(p.id, 0);
    } catch (e) {
      setState({ phase: "failed", message: e instanceof Error ? e.message : "Le paiement n'a pas pu être lancé." });
    }
  }, [follow, onPaid]);

  return { ...state, pay, reset: () => setState({ phase: "idle", message: "" }) };
}

/** Opérateur + numéro Mobile Money, communs à l'abonnement et à la recharge. */
function PayFields({ operators, operator, setOperator, phone, setPhone }: {
  operators: Operator[]; operator: string; setOperator: (v: string) => void; phone: string; setPhone: (v: string) => void;
}) {
  return (
    <>
      <label>
        Opérateur
        <select value={operator} onChange={(e) => setOperator(e.target.value)}>
          {operators.map((o) => <option key={o.code} value={o.code}>{o.name}</option>)}
        </select>
      </label>
      <label>
        Numéro Mobile Money
        <input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" placeholder="6XX XX XX XX" />
      </label>
    </>
  );
}

function PayStatus({ phase, message }: { phase: string; message: string }) {
  if (phase === "waiting") return <p className="notice">Validez le paiement sur votre téléphone. Cette page se met à jour toute seule.</p>;
  if (phase === "paid") return <p className="notice ok">{message}</p>;
  if (phase === "failed") return <p className="error">{message}</p>;
  return null;
}

function useOperators(enabled: boolean) {
  const [operators, setOperators] = useState<Operator[]>([]);
  useEffect(() => {
    if (enabled) api<Operator[]>("/payments/operators").then(setOperators).catch(() => setOperators([]));
  }, [enabled]);
  return operators;
}

const defaultPhone = () => {
  const login = getSession()?.user.login ?? "";
  return /^\d+$/.test(login) ? login : "";
};

/** Mon abonnement : où j'en suis, changer ou renouveler, payer par Mobile Money, mes paiements. */
export function SubscriptionCard({ plans, onChange }: { plans: Plan[]; onChange: () => void }) {
  const [sub, setSub] = useState<Sub | null>(null);
  const [period, setPeriod] = useState<"mois" | "an">("mois");
  const [chosen, setChosen] = useState("");
  const [promo, setPromo] = useState("");
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteError, setQuoteError] = useState("");
  const [operator, setOperator] = useState("");
  const [phone, setPhone] = useState(defaultPhone);

  const load = useCallback(() => {
    api<Sub>("/subscription").then(setSub).catch(() => setSub(null));
  }, []);
  useEffect(load, [load]);

  const paid = useCallback(() => {
    setChosen(""); // le panneau de paiement se referme, le message de confirmation reste
    load();
    onChange();
  }, [load, onChange]);
  const payment = usePayment(paid);
  const operators = useOperators(!!sub?.payments_enabled);
  useEffect(() => {
    if (!operator && operators[0]) setOperator(operators[0].code);
  }, [operators, operator]);

  // Le prix affiché vient toujours du serveur : remise, déduction des jours déjà payés, dates.
  const refreshQuote = useCallback(async (plan: string, code: string) => {
    setQuoteError("");
    try {
      setQuote(await api<Quote>("/subscription/quote", { json: { plan, period, promo_code: code } }));
    } catch (e) {
      setQuote(null);
      setQuoteError(e instanceof Error ? e.message : "Prix indisponible");
    }
  }, [period]);
  useEffect(() => {
    if (chosen) void refreshQuote(chosen, promo);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chosen, period]);

  if (!sub) return null;
  const busy = payment.phase === "sending" || payment.phase === "waiting";

  async function trial(plan: string) {
    try {
      await api("/subscription/trial", { json: { plan } });
      paid();
    } catch (e) {
      setQuoteError(e instanceof Error ? e.message : "Essai indisponible");
    }
  }

  return (
    <div className="card stack">
      <h2>Mon abonnement</h2>
      <div className={`offer ${sub.expires_soon ? "warn" : sub.paid ? "current" : ""}`}>
        <div className="row between">
          <strong>Offre {sub.plan_label}{sub.source === "essai" ? " (essai gratuit)" : ""}</strong>
          {sub.days_left !== null && <span>{sub.days_left === 0 ? "Dernier jour" : `${sub.days_left} jour${sub.days_left > 1 ? "s" : ""} restant${sub.days_left > 1 ? "s" : ""}`}</span>}
        </div>
        <span className="muted small">
          {sub.until
            ? `Valable jusqu'au ${date(sub.until)}. Sans renouvellement, votre compte repasse en Gratuit et rien n'est supprimé.`
            : sub.paid ? "Sans date de fin." : "Gratuit, sans limite de durée."}
        </span>
      </div>

      <div className="seg">
        <button className={period === "mois" ? "on" : ""} onClick={() => setPeriod("mois")}>Mensuel</button>
        <button className={period === "an" ? "on" : ""} onClick={() => setPeriod("an")}>Annuel, 2 mois offerts</button>
      </div>

      {plans.filter((p) => p.price_fcfa > 0).map((p) => {
        const price = period === "an" ? p.price_year_fcfa ?? p.price_fcfa * 10 : p.price_fcfa;
        const mine = p.key === sub.plan;
        return (
          <div key={p.key} className={`offer ${chosen === p.key ? "picked" : ""}`}>
            <div className="row between">
              <strong>{p.label}</strong>
              <span>{fcfa(price)} par {period}</span>
            </div>
            <span className="muted small">{p.features.slice(0, 3).join(", ")}</span>
            <div className="row">
              <button className="btn" onClick={() => (payment.reset(), setChosen(chosen === p.key ? "" : p.key))} disabled={busy}>
                {mine ? "Renouveler" : "Choisir"}
              </button>
              {sub.trial_available && (
                <button className="btn" onClick={() => void trial(p.key)} disabled={busy}>Essayer {sub.trial_days} jours</button>
              )}
            </div>
          </div>
        );
      })}

      {chosen && (
        <div className="pay stack">
          {quote && (
            <dl className="bill">
              <dt>Offre {quote.plan_label}, {quote.period_label}</dt><dd>{fcfa(quote.base_fcfa)}</dd>
              {quote.discount_fcfa > 0 && (<><dt>Code {quote.promo_code}</dt><dd>- {fcfa(quote.discount_fcfa)}</dd></>)}
              {quote.prorata_fcfa > 0 && (<><dt>Déjà payé sur l'offre en cours</dt><dd>- {fcfa(quote.prorata_fcfa)}</dd></>)}
              <dt className="total">À payer</dt><dd className="total">{fcfa(quote.amount_fcfa)}</dd>
            </dl>
          )}
          {quote && <span className="muted small">{quote.renewal ? "Prolonge votre offre" : "Valable"} du {date(quote.starts_at)} au {date(quote.ends_at)}.</span>}
          <div className="row promo">
            <input value={promo} onChange={(e) => setPromo(e.target.value)} placeholder="Code promo (facultatif)" />
            <button className="btn" onClick={() => void refreshQuote(chosen, promo)} disabled={busy}>Appliquer</button>
          </div>
          {quoteError && <p className="error">{quoteError}</p>}
          {sub.payments_enabled && operators.length > 0 ? (
            <>
              <PayFields operators={operators} operator={operator} setOperator={setOperator} phone={phone} setPhone={setPhone} />
              <button className="btn primary big" disabled={busy || !quote || !phone.trim()}
                      onClick={() => void payment.pay("/subscription/checkout", { plan: chosen, period, phone, operator, promo_code: quote?.promo_code ?? "" })}>
                {payment.phase === "sending" ? "Envoi…" : quote ? `Payer ${fcfa(quote.amount_fcfa)}` : "Payer"}
              </button>
            </>
          ) : (
            <Unavailable label={quote?.plan_label ?? chosen} />
          )}
        </div>
      )}
      <PayStatus phase={payment.phase} message={payment.message} />

      {sub.payments.length > 0 && (
        <details>
          <summary>Mes paiements</summary>
          <ul className="payments">
            {sub.payments.map((p) => (
              <li key={p.id}>
                <span>{new Date(p.created_at).toLocaleDateString("fr-FR")}<br /><span className="muted small">{p.label}</span></span>
                <span className="num">{fcfa(p.amount_fcfa)}<br /><span className={`small st-${p.status}`}>{STATUS[p.status] ?? p.status}</span></span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Unavailable({ label }: { label: string }) {
  const link = contactLink(`Bonjour, je souhaite activer l'offre ${label}. Mon identifiant : ${getSession()?.user.login ?? ""}`);
  return link
    ? <a className="btn" href={link}>Nous contacter pour activer cette offre</a>
    : <p className="muted small">Le paiement en ligne n'est pas encore disponible. Contactez-nous pour activer cette offre.</p>;
}

/** Recharge du crédit IA par Mobile Money. */
export function Topup({ enabled, onPaid }: { enabled: boolean; onPaid: () => void }) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState(2000);
  const [operator, setOperator] = useState("");
  const [phone, setPhone] = useState(defaultPhone);
  const payment = usePayment(onPaid);
  const operators = useOperators(enabled && open);
  useEffect(() => {
    if (!operator && operators[0]) setOperator(operators[0].code);
  }, [operators, operator]);
  if (!enabled) return null;
  const busy = payment.phase === "sending" || payment.phase === "waiting";

  if (!open) return <button className="btn" onClick={() => setOpen(true)}>Recharger mon crédit IA</button>;
  return (
    <div className="pay stack">
      <div className="seg">
        {[1000, 2000, 5000].map((a) => (
          <button key={a} className={amount === a ? "on" : ""} onClick={() => setAmount(a)}>{fcfa(a)}</button>
        ))}
      </div>
      <PayFields operators={operators} operator={operator} setOperator={setOperator} phone={phone} setPhone={setPhone} />
      <button className="btn primary" disabled={busy || !phone.trim() || !operator}
              onClick={() => void payment.pay("/billing/topup", { amount_fcfa: amount, phone, operator })}>
        {payment.phase === "sending" ? "Envoi…" : `Recharger ${fcfa(amount)}`}
      </button>
      <PayStatus phase={payment.phase} message={payment.message} />
    </div>
  );
}
