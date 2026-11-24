import { useEffect, useRef, useState } from 'react';
import { DashboardLayout } from '@/components/dashboard-layout';
import { api } from '@/lib/api';
import { tokenStorage } from '@/lib/token-storage';

export function TwoFactorPage() {
  const active = useRef(true);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [recovery, setRecovery] = useState(false);
  const [setup, setSetup] = useState<{ manual_key: string; qr_svg: string } | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api.get<{ enabled: boolean }>('/users/me/2fa', { signal: controller.signal })
      .then(r => { if (!controller.signal.aborted) { setEnabled(r.data.enabled); setError(''); } })
      .catch(() => { if (!controller.signal.aborted) setError('Não foi possível consultar o 2FA. Tente novamente.'); });
    return () => controller.abort();
  }, [reload]);
  async function execute(operation: 'setup' | 'confirm' | 'regenerate' | 'disable') {
    if (busy) return;
    if (operation === 'disable' && !window.confirm('Desativar a proteção por segundo fator?')) return;
    if (operation === 'regenerate' && !window.confirm('Invalidar os códigos de recuperação anteriores?')) return;
    setBusy(true); setError(''); setCodes([]);
    try {
      const { data } = await api.post('/users/me/2fa/' + operation,
        operation === 'setup' ? { password } : { password, code, recovery });
      if (!active.current) return;
      if (operation === 'setup') setSetup(data);
      else {
        if (data.access_token) tokenStorage.set(data.access_token);
        setEnabled(operation !== 'disable'); setSetup(null); setCodes(data.recovery_codes ?? []);
        setCode(''); setPassword('');
      }
    } catch (cause) { if (active.current) setError(cause instanceof Error ? cause.message : 'Não foi possível concluir.'); }
    finally { if (active.current) setBusy(false); }
  }
  return <DashboardLayout title="Autenticação em dois fatores" description="Proteja seu acesso com um aplicativo autenticador.">
    <section className="server-panel channel-workspace">
      {enabled === null ? <p>Consultando configuração…</p> : <p>{enabled ? '2FA ativo' : '2FA desativado'}</p>}
      {error && <p role="alert">{error}<button onClick={() => setReload(n => n + 1)}>Consultar novamente</button></p>}
      <form className="server-create-form" onSubmit={e => { e.preventDefault(); void execute(enabled ? 'regenerate' : setup ? 'confirm' : 'setup'); }}>
        <label className="server-field">Senha atual<input type="password" required autoComplete="current-password" maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
        {setup && <>
          <img alt="QR Code para configurar o autenticador" src={'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(setup.qr_svg)} width={240} />
          <p>Chave manual: <code>{setup.manual_key}</code></p>
          <p>Confirme em até dez minutos. A chave será exibida somente nesta configuração.</p>
        </>}
        {(enabled || setup) && <>
          <label className="server-field">Código<input required autoComplete="one-time-code" maxLength={64} value={code} onChange={e => setCode(e.target.value)} /></label>
          {enabled && <label><input type="checkbox" checked={recovery} onChange={e => setRecovery(e.target.checked)} />Utilizar código de recuperação</label>}
        </>}
        <button className="server-primary-button" disabled={busy || enabled === null}>{busy ? 'Processando…' : enabled ? 'Regenerar códigos' : setup ? 'Confirmar ativação' : 'Configurar 2FA'}</button>
        {enabled && <button type="button" className="server-danger-button" disabled={busy || !password || !code} onClick={() => void execute('disable')}>Desativar 2FA</button>}
      </form>
      {codes.length > 0 && <div role="status"><p>Guarde estes códigos em local seguro. Cada código funciona uma vez. Eles não serão exibidos novamente.</p>
        <ul>{codes.map(value => <li key={value}><code>{value}</code></li>)}</ul>
        <button onClick={() => setCodes([])}>Já guardei os códigos</button>
      </div>}
    </section>
  </DashboardLayout>;
}
