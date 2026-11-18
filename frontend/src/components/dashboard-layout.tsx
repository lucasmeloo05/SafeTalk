import type { ReactNode } from 'react';
import {
  ChevronRight,
  LogOut,
  MessageCircle,
  MessagesSquare,
  ShieldCheck,
  Users,
} from 'lucide-react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '@/context/auth-context';

type DashboardLayoutProps = {
  title: string;
  description: string;
  children: ReactNode;
  headerAction?: ReactNode;
};

export function DashboardLayout({ title, description, children, headerAction }: DashboardLayoutProps) {
  const { user, signOut } = useAuth();
  const location = useLocation();
  if (!user) return null;
  const initial = user.username.slice(0, 1).toUpperCase();

  return (
    <div className="dashboard-shell">
      <aside className="dashboard-sidebar" aria-label="Navegação principal">
        <Link className="dashboard-brand" to="/app" aria-label="SafeTalk, início">
          <span className="dashboard-brand__mark"><MessageCircle size={19} strokeWidth={2.2} /></span>
          <span className="dashboard-brand__name">safe<span>talk</span></span>
        </Link>

        <div className="dashboard-sidebar__section-label">ESPAÇO PESSOAL</div>
        <nav className="dashboard-nav" aria-label="Seções">
          <NavLink to="/app" end className={({ isActive }) => `dashboard-nav__link${isActive ? ' is-active' : ''}`}>
            <MessagesSquare size={18} strokeWidth={1.8} />
            <span>Conversas</span>
            {location.pathname === '/app' && <span className="dashboard-nav__active-mark" aria-hidden="true" />}
          </NavLink>
          <NavLink to="/pessoas" className={({ isActive }) => `dashboard-nav__link${isActive ? ' is-active' : ''}`}>
            <Users size={18} strokeWidth={1.8} />
            <span>Pessoas</span>
            {location.pathname === '/pessoas' && <span className="dashboard-nav__active-mark" aria-hidden="true" />}
          </NavLink>
          <NavLink to="/moderacao" className={({ isActive }) => `dashboard-nav__link${isActive ? ' is-active' : ''}`}>
            <ShieldCheck size={18} strokeWidth={1.8} />
            <span>Moderação</span>
            {location.pathname === '/moderacao' && <span className="dashboard-nav__active-mark" aria-hidden="true" />}
          </NavLink>
        </nav>

        <div className="dashboard-sidebar__grow" />

        <div className="dashboard-sidebar__tip">
          <span className="dashboard-sidebar__tip-icon"><ShieldCheck size={16} /></span>
          <div><strong>Um espaço mais seguro</strong><p>Privacidade e cuidado em cada conversa.</p></div>
        </div>

        <div className="dashboard-account">
          <span className="dashboard-avatar" aria-hidden="true">{initial}</span>
          <div className="dashboard-account__identity"><strong>{user.username}</strong><span>{user.email}</span></div>
          <button className="dashboard-account__logout" type="button" onClick={signOut} aria-label="Sair da conta" title="Sair"><LogOut size={17} /></button>
        </div>
      </aside>

      <main className="dashboard-main">
        <header className="dashboard-header">
          <div className="dashboard-header__heading">
            <div className="dashboard-breadcrumb"><span>SAFETALK</span><ChevronRight size={13} /><span>ESPAÇO PESSOAL</span></div>
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
          <div className="dashboard-header__actions">
            <span className="dashboard-session"><span /> Sessão protegida</span>
            {headerAction}
          </div>
        </header>

        <div className="dashboard-content">
          {children}
          <footer className="dashboard-footer">
            <span><ShieldCheck size={15} /> Sua conta está conectada com segurança.</span>
            <span className="dashboard-footer__product"><ShieldCheck size={14} /> SafeTalk · espaço pessoal</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
