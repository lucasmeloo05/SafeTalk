import { useEffect, useRef, useState } from 'react';
import { DashboardLayout } from '@/components/dashboard-layout';
import { api } from '@/lib/api';
import type { UserResponse } from '@/services/auth-api';

export function AgeDeclarationPage() {
  const [profile, setProfile] = useState<UserResponse | null>(null);
  const [birthday, setBirthday] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const alive = useRef(false);
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    api.get<UserResponse>('/users/me', { signal: controller.signal }).then(r => {
      if (!controller.signal.aborted) { setProfile(r.data); setError(''); }
    }).catch(() => { if (!controller.signal.aborted) setError('Não foi possível carregar seus dados.'); });
    return () => { controller.abort(); alive.current = false; };
  }, [reload]);
  async function declare() {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const response = await api.post<UserResponse>('/users/me/birth-date', { birth_date: birthday, password });
      if (alive.current) { setProfile(response.data); setPassword(''); }
    } catch (cause) {
      if (alive.current) setError(cause instanceof Error ? cause.message : 'Não foi possível salvar sua declaração.');
    } finally { if (alive.current) setBusy(false); }
  }
  return <DashboardLayout title="Declaração de idade" description="Sua data de nascimento é privada.">
    <section className="server-panel channel-workspace">
      <p>A idade mínima é 14 anos. Servidores +18 exigem pelo menos 18 anos na data do acesso.
        A data é autodeclarada e não representa verificação documental ou comprovação de identidade.</p>
      {error && <p role="alert">{error}<button onClick={() => setReload(n => n + 1)}>Consultar novamente</button></p>}
      {!profile ? <p role="status">Carregando seus dados…</p> : profile.birth_date ? <p role="status">Data de nascimento declarada. A alteração não está disponível nesta versão.</p> :
        <form onSubmit={e => { e.preventDefault(); void declare(); }}>
          <p>Informe sua data uma única vez. Confira antes de confirmar, pois ela não poderá ser alterada.</p>
          <label className="server-field">Data de nascimento<input required type="date" min="1900-01-01" value={birthday} onChange={e => setBirthday(e.target.value)} /></label>
          <label className="server-field">Senha atual<input required type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} /></label>
          <button className="server-primary-button" disabled={busy}>{busy ? 'Salvando…' : 'Confirmar declaração'}</button>
        </form>}
    </section>
  </DashboardLayout>;
}
