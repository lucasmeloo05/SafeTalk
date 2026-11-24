import { useState, type FormEvent } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AuthShell } from "@/components/auth-shell";
import { PasswordField } from "@/components/password-field";
import { useAuth } from "@/context/auth-context";
import { ApiError } from "@/lib/api";

type LoginLocationState = {
  registered?: boolean;
  sessionNotice?: string | null;
  from?: { pathname?: string };
};

export function LoginPage() {
  const { signIn, verifySecondFactor, sessionNotice } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const locationState = location.state as LoginLocationState | null;
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(
    locationState?.registered
      ? "Conta criada. Entre com seu username ou e-mail e senha."
      : locationState?.sessionNotice ?? null,
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [challenge, setChallenge] = useState<string | null>(null);
  const [recovery, setRecovery] = useState(false);
  const visibleNotice = notice ?? sessionNotice;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    setIsSubmitting(true);
    const form = new FormData(event.currentTarget);
    const login = String(form.get("login") ?? "").trim();
    const password = String(form.get("password") ?? "");

    try {
      if (challenge) await verifySecondFactor(challenge, String(form.get("code") ?? ""), recovery);
      else {
        const next = await signIn(login, password);
        if (next) { setChallenge(next); return; }
      }
      navigate(locationState?.from?.pathname || "/app", { replace: true });
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Não foi possível entrar. Tente novamente.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthShell mode="login">
      <div className="auth-heading">
        <span className="heading-icon"><Sparkles size={18} /></span>
        <p className="auth-kicker">BEM-VINDO DE VOLTA</p>
        <h2>Entre na sua conta</h2>
        <p className="auth-subtitle">Suas conversas estão a um passo de distância.</p>
      </div>

      <form className="auth-form" onSubmit={handleSubmit}>
        {!challenge && <><div className="field-group">
          <label className="field-label" htmlFor="login">Usuário ou e-mail</label>
          <input className="field-input" id="login" name="login" type="text" autoComplete="username" placeholder="Como podemos te chamar?" minLength={3} maxLength={255} required />
        </div>
        <PasswordField id="password" label="Senha" autoComplete="current-password" maxLength={128} /></>}
        {challenge && <>
          <label className="field-label">Código {recovery ? "de recuperação" : "do autenticador"}
            <input className="field-input" name="code" required maxLength={64} autoComplete="one-time-code" />
          </label>
          <label><input type="checkbox" checked={recovery} onChange={e => setRecovery(e.target.checked)} />Usar código de recuperação</label>
          <p>O desafio expira em cinco minutos.</p>
          <button type="button" disabled={isSubmitting} onClick={() => { setChallenge(null); setError(null); }}>Reiniciar login</button>
        </>}
        <div className="form-meta"><span className="muted-note">A sessão expira em até 30 minutos.</span></div>
        {visibleNotice && <p className="form-notice" role="status">{visibleNotice}</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Entrando…" : "Entrar no SafeTalk"} {!isSubmitting && <ArrowRight size={17} />}
        </button>
      </form>

      <div className="separator"><span>ou</span></div>
      <p className="switch-copy">Novo por aqui? <Link to="/cadastro">Crie sua conta gratuitamente</Link></p>
      <p className="legal-copy">Ao continuar, você concorda com nossos <a href="#termos">Termos de uso</a> e <a href="#privacidade">Política de privacidade</a>.</p>
    </AuthShell>
  );
}
