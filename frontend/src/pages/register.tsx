import { useState, type FormEvent } from "react";
import { ArrowRight, Check, HeartHandshake } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { AuthShell } from "@/components/auth-shell";
import { PasswordField } from "@/components/password-field";
import { useAuth } from "@/context/auth-context";
import { ApiError } from "@/lib/api";

export function RegisterPage() {
  const { signUp } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    const form = new FormData(event.currentTarget);
    const payload = {
      username: String(form.get("username") ?? "").trim(),
      email: String(form.get("email") ?? "").trim(),
      password: String(form.get("password") ?? ""),
      birth_date: String(form.get("birth_date") ?? ""),
    };

    try {
      await signUp(payload);
      navigate("/login", { replace: true, state: { registered: true } });
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Não foi possível criar a conta. Tente novamente.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <AuthShell mode="register">
      <div className="auth-heading auth-heading--register">
        <span className="heading-icon"><HeartHandshake size={18} /></span>
        <p className="auth-kicker">COMECE POR AQUI</p>
        <h2>Crie sua conta</h2>
        <p className="auth-subtitle">Um bom papo começa com um lugar seguro.</p>
      </div>

      <form className="auth-form auth-form--register" onSubmit={handleSubmit}>
        <div className="field-group">
          <label className="field-label" htmlFor="username">Nome de usuário</label>
          <input className="field-input" id="username" name="username" type="text" autoComplete="username" placeholder="ex.: marina_costa" minLength={3} maxLength={30} pattern="[a-zA-Z0-9_]+" title="Use letras, números e sublinhado." required />
          <span className="field-hint">Use letras, números e _ (3 a 30 caracteres).</span>
        </div>
        <div className="field-group">
          <label className="field-label" htmlFor="email">E-mail</label>
          <input className="field-input" id="email" name="email" type="email" autoComplete="email" placeholder="voce@exemplo.com" maxLength={255} required />
        </div>
        <div className="field-group">
          <label className="field-label" htmlFor="birth_date">Data de nascimento</label>
          <input className="field-input" id="birth_date" name="birth_date" type="date" autoComplete="bday" min="1900-01-01" max={new Date().toISOString().slice(0, 10)} required />
        </div>
        <PasswordField id="password" label="Senha" autoComplete="new-password" minLength={8} maxLength={128} />
        <label className="check-label terms-check"><input type="checkbox" required /><span className="custom-check"><Check size={12} /></span><span>Li e aceito os <a href="#termos">Termos de uso</a> e a <a href="#privacidade">Política de privacidade</a>.</span></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="primary-button" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Criando conta…" : "Criar minha conta"} {!isSubmitting && <ArrowRight size={17} />}
        </button>
      </form>

      <p className="switch-copy switch-copy--register">Já tem uma conta? <Link to="/login">Faça login</Link></p>
    </AuthShell>
  );
}
