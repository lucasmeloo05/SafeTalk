import { useEffect, useState } from 'react';
import { api, ApiError } from '@/lib/api';

type BlockedUser = { id: number; username: string };
const pageSize = 20;
const errorText = (error: unknown) => error instanceof ApiError ? error.message : 'Não foi possível concluir a operação.';

type BlockButtonProps = {
  id: number;
  name: string;
  onBlocked: () => void;
  disabled?: boolean;
  onBusyChange?: (busy: boolean) => void;
};

export function BlockButton({ id, name, onBlocked, disabled, onBusyChange }: BlockButtonProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function block() {
    if (!window.confirm(`Bloquear ${name}? A amizade ou solicitação será encerrada.`)) return;
    onBusyChange?.(true);
    setBusy(true);
    setError('');
    try {
      await api.put(`/social/blocks/${id}`);
      onBlocked();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); onBusyChange?.(false); }
  }
  return <><button className="social-button" disabled={disabled || busy} onClick={block}>Bloquear</button>{error && <span role="alert">{error}</span>}</>;
}

export function BlockedUsers({ onUnblocked }: { onUnblocked: () => void }) {
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [users, setUsers] = useState<BlockedUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true);
    setUsers([]);
    setError('');
    api.get<BlockedUser[]>('/social/blocks', { params: { limit: pageSize, offset } })
      .then(({ data }) => {
        if (!active) return;
        if (!data.length && offset > 0) setOffset(offset - pageSize);
        else setUsers(data);
      }).catch(cause => { if (active) setError(errorText(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [offset, revision]);
  async function unblock(id: number) {
    setBusy(true);
    setError('');
    try {
      await api.delete(`/social/blocks/${id}`);
      setRevision(value => value + 1);
      onUnblocked();
    } catch (cause) { setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  return <section aria-label="Usuários bloqueados"><h3>Usuários bloqueados</h3>
    {error && <p role="alert">{error}</p>}
    {loading ? <p>Carregando bloqueios…</p> : users.map(user =>
      <p key={user.id}>{user.username} <button disabled={busy} onClick={() => unblock(user.id)}>Desbloquear</button></p>)}
    {!loading && !error && !users.length && <p>Nenhum usuário bloqueado.</p>}
    {offset > 0 && <button disabled={loading || busy} onClick={() => setOffset(offset - pageSize)}>Anterior</button>}
    {users.length === pageSize && <button disabled={loading || busy} onClick={() => setOffset(offset + pageSize)}>Próxima</button>}
  </section>;
}
