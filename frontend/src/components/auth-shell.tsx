import type { ReactNode } from "react";
import { ArrowUpRight, LockKeyhole, MessageCircle, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

type AuthShellProps = {
  children: ReactNode;
  mode: "login" | "register";
};

export function AuthShell({ children, mode }: AuthShellProps) {
  return (
    <main className="auth-shell">
      <aside className="brand-panel" aria-label="Sobre o SafeTalk">
        <div className="brand-panel__glow brand-panel__glow--one" />
        <div className="brand-panel__glow brand-panel__glow--two" />
        <div className="brand-panel__grid" />
        <div className="brand-panel__content">
          <Link to="/login" className="brand-lockup" aria-label="SafeTalk início">
            <span className="brand-lockup__mark"><MessageCircle size={21} strokeWidth={2.3} /></span>
            <span>safe<span>talk</span></span>
          </Link>

          <section className="brand-story">
            <div className="eyebrow"><span className="eyebrow__line" /> COMUNICAÇÃO COM CONFIANÇA</div>
            <h1>Converse com<br />mais <em>tranquilidade.</em></h1>
            <p>Um espaço pensado para aproximar pessoas com privacidade, cuidado e segurança em cada conversa.</p>

            <div className="chat-preview" aria-hidden="true">
              <div className="chat-preview__top">
                <div className="chat-preview__avatar">M</div>
                <div className="chat-preview__person"><strong>Marina Costa</strong><span>online agora</span></div>
                <span className="chat-preview__secure"><LockKeyhole size={13} /> privado</span>
              </div>
              <div className="chat-preview__messages">
                <div className="chat-bubble chat-bubble--received">Oi! Como foi seu dia?</div>
                <div className="chat-bubble chat-bubble--sent">Foi ótimo. Que bom falar com você ✨<small>14:32 <span>✓✓</span></small></div>
                <div className="chat-bubble chat-bubble--received">Também gosto desse nosso espaço :)</div>
              </div>
              <div className="chat-preview__input"><span>Escreva uma mensagem...</span><span className="chat-preview__send"><ArrowUpRight size={15} /></span></div>
            </div>
          </section>

          <div className="brand-panel__bottom">
            <div className="trust-mark"><ShieldCheck size={17} /><span>Seu espaço. Suas conversas. Seu ritmo.</span></div>
            <span className="brand-panel__version">SAFETALK · 2026</span>
          </div>
        </div>
      </aside>

      <section className="form-panel">
        <div className="form-panel__topline">
          <span>{mode === "login" ? "Ainda não tem conta?" : "Já faz parte do SafeTalk?"}</span>
          <Link className="topline-link" to={mode === "login" ? "/cadastro" : "/login"}>
            {mode === "login" ? "Criar conta" : "Entrar"}<ArrowUpRight size={15} />
          </Link>
        </div>
        <div className="form-panel__inner">{children}</div>
        <footer className="form-panel__footer">
          <span>© 2026 SafeTalk</span>
          <span className="footer-dot" />
          <span>Feito para conversas melhores</span>
        </footer>
      </section>
    </main>
  );
}
