import { useCallback, useLayoutEffect, useRef, useState, type FormEvent } from 'react';
import { Check, Copy, LoaderCircle, Plus, ShieldAlert, Ticket } from 'lucide-react';
import { ApiError } from '@/lib/api';
import {
  createServerInvite,
  listServerInvites,
  revokeServerInvite,
  SERVER_INVITE_PAGE_SIZE,
  type ServerInviteCreatedResponse,
  type ServerInviteResponse,
} from '@/services/server-api';

function inviteErrorMessage(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 401) return 'Sua sessão expirou. Entre novamente para continuar.';
  if (error.status === 403) return 'Somente o proprietário ou um membro com manage_invites pode gerenciar convites.';
  if (error.status === 404) return 'Servidor ou convite não encontrado, ou sua participação não está ativa.';
  if (error.status === 409) return error.message || 'O convite não pode ser revogado neste estado.';
  if (error.status === 422) return error.message || 'Confira os dados informados.';
  return error.message || fallback;
}

function formatDate(value: string | null) {
  if (!value) return 'Sem expiração';
  return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export function ServerInvitesPanel({ serverId, authorized, checking, onRefreshAuthorization }: {
  serverId: number;
  authorized: boolean;
  checking: boolean;
  onRefreshAuthorization: () => Promise<void>;
}) {
  const generationRef = useRef(0);
  const [invites, setInvites] = useState<ServerInviteResponse[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadError, setLoadError] = useState('');
  const listRequest = useRef(0);
  const [refusal, setRefusal] = useState('');
  const [listDenied, setListDenied] = useState(false);
  const pauseListAfterDenial = useRef(false);
  const canManageInvites = authorized && !checking && !listDenied;
  const [expiresAt, setExpiresAt] = useState('');
  const [maxUses, setMaxUses] = useState('');
  const [creating, setCreating] = useState(false);
  const pendingCreation = useRef<symbol | null>(null);
  const canReloadInvites = useRef(false);
  const [createError, setCreateError] = useState('');
  const [createdInvite, setCreatedInvite] = useState<ServerInviteCreatedResponse | null>(null);
  const [revokeConfirmation, setRevokeConfirmation] = useState<number | null>(null);
  const [revokingId, setRevokingId] = useState<number | null>(null);
  const pendingRevocation = useRef<number | null>(null);
  const [revokedId, setRevokedId] = useState<number | null>(null);
  const [revokeError, setRevokeError] = useState('');
  const [copied, setCopied] = useState(false);
  const copyRequest = useRef(0);
  const [copyError, setCopyError] = useState('');

  const refuse = useCallback((operation: string) => {
    setRefusal(operation + ' Somente o proprietário ou um membro com manage_invites pode gerenciar convites.');
    void onRefreshAuthorization();
  }, [onRefreshAuthorization]);

  const loadInvites = useCallback(async (nextOffset = 0, append = false) => {
    const generation = generationRef.current;
    const request = ++listRequest.current;
    const current = () => generation === generationRef.current && request === listRequest.current;
    if (append) setLoadingMore(true);
    else setLoading(true);
    setLoadError('');
    try {
      const data = await listServerInvites(serverId, SERVER_INVITE_PAGE_SIZE, nextOffset);
      if (!current()) return;
      setListDenied(false);
      setInvites(previous => append ? [...previous, ...data.filter(item => !previous.some(existing => existing.id === item.id))] : data);
      setOffset(nextOffset);
      setHasMore(data.length === SERVER_INVITE_PAGE_SIZE);
    } catch (error) {
      if (!current()) return;
      if (error instanceof ApiError && error.status === 403) {
        pauseListAfterDenial.current = true;
        setListDenied(true);
        refuse('Consulta de convites recusada.');
      } else setLoadError(inviteErrorMessage(error, 'Não foi possível carregar os convites. Tente novamente.'));
    } finally {
      if (current()) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [serverId, refuse]);

  useLayoutEffect(() => {
    // ServerDetails is keyed by server. Revalidation only invalidates reads.
    return () => {
      pendingCreation.current = null;
      pendingRevocation.current = null;
      ++copyRequest.current;
    };
  }, [serverId]);

  useLayoutEffect(() => {
    canReloadInvites.current = canManageInvites;
    if (!canManageInvites) ++copyRequest.current;
  }, [canManageInvites]);

  useLayoutEffect(() => {
    if (authorized && !pauseListAfterDenial.current) void loadInvites();
    setLoadingMore(false);
    return () => { ++generationRef.current; };
  }, [authorized, loadInvites]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!canManageInvites || pendingCreation.current !== null) return;
    const uses = maxUses.trim() ? Number(maxUses) : undefined;
    if (uses !== undefined && (!Number.isSafeInteger(uses) || uses <= 0)) {
      setCreateError('O limite de usos deve ser um inteiro positivo.');
      return;
    }
    let expiration: string | undefined;
    if (expiresAt) {
      const parsed = new Date(expiresAt);
      if (Number.isNaN(parsed.getTime())) {
        setCreateError('Informe uma data de expiração válida.');
        return;
      }
      expiration = parsed.toISOString();
    }

    const operation = Symbol();
    pendingCreation.current = operation;
    setRefusal('');
    setCreating(true);
    setCreateError('');
    setCreatedInvite(null);
    ++copyRequest.current;
    setCopyError('');
    setCopied(false);
    try {
      const created = await createServerInvite(serverId, {
        ...(expiration ? { expires_at: expiration } : {}),
        ...(uses !== undefined ? { max_uses: uses } : {}),
      });
      if (pendingCreation.current !== operation) return;
      setCreatedInvite(created);
      setExpiresAt('');
      setMaxUses('');
      if (canReloadInvites.current) void loadInvites();
    } catch (error) {
      if (pendingCreation.current !== operation) return;
      if (error instanceof ApiError && error.status === 403) refuse('Criação de convite recusada.');
      else if (!(error instanceof ApiError) || error.status === undefined) {
        setCreateError('Não foi possível confirmar a criação. O convite pode ter sido criado. Consulte a lista antes de tentar novamente.');
      } else setCreateError(inviteErrorMessage(error, 'Não foi possível criar o convite.'));
    } finally {
      if (pendingCreation.current === operation) {
        pendingCreation.current = null;
        setCreating(false);
      }
    }
  }

  async function handleRevoke(inviteId: number) {
    if (!canManageInvites || pendingRevocation.current !== null) return;
    pendingRevocation.current = inviteId;
    setRevokedId(null);
    setRefusal('');
    setRevokingId(inviteId);
    setRevokeError('');
    try {
      await revokeServerInvite(serverId, inviteId);
      if (pendingRevocation.current !== inviteId) return;
      setRevokedId(inviteId);
      setRevokeConfirmation(null);
      if (canReloadInvites.current) void loadInvites();
    } catch (error) {
      if (pendingRevocation.current !== inviteId) return;
      if (error instanceof ApiError && error.status === 403) refuse('Revogação de convite recusada.');
      else setRevokeError(inviteErrorMessage(error, 'Não foi possível revogar o convite. Tente novamente.'));
    } finally {
      if (pendingRevocation.current === inviteId) {
        pendingRevocation.current = null;
        setRevokingId(null);
      }
    }
  }

  async function copyToken() {
    if (!canManageInvites || !createdInvite) return;
    const request = ++copyRequest.current;
    setCopied(false);
    setCopyError('');
    if (!navigator.clipboard) {
      setCopyError('A cópia automática não está disponível neste navegador. Selecione e copie o token exibido.');
      return;
    }
    try {
      await navigator.clipboard.writeText(createdInvite.token);
      if (request === copyRequest.current) setCopied(true);
    } catch {
      if (request === copyRequest.current) setCopyError('Não foi possível copiar automaticamente. Selecione e copie o token exibido.');
    }
  }

  return (
    <section className="server-panel" aria-labelledby="server-invites-title">
      <header className="server-panel__header"><div><h3 id="server-invites-title"><Ticket size={17} /> Convites</h3><p>Tokens são exibidos somente uma vez, após a criação.</p></div></header>
      {createdInvite && !canManageInvites && <p role="status">Criação do convite confirmada pelo servidor.</p>}
      {canManageInvites && createdInvite && <div className="server-invite-created" role="status">
        <div><strong>Convite criado</strong><p>Compartilhe o ID do servidor e este token. A listagem não permite recuperá-lo depois.</p></div>
        <p>{createdInvite.max_uses === null ? 'Sem limite de utilizações' : createdInvite.max_uses === 1 ? 'Uma utilização' : `Até ${createdInvite.max_uses} utilizações`}</p>
        <dl><div><dt>ID do servidor</dt><dd>{createdInvite.server_id}</dd></div><div className="server-invite-token"><dt>Token do convite</dt><dd><code>{createdInvite.token}</code><button className="server-secondary-button" type="button" onClick={() => void copyToken()} aria-label="Copiar token do convite">{copied ? <Check size={14} /> : <Copy size={14} />}{copied ? 'Copiado' : 'Copiar'}</button></dd></div></dl>
      </div>}
      {refusal && <div className="server-state server-state--error" role="alert"><ShieldAlert size={20} /><strong>{refusal}</strong></div>}
      {createError && <p className="server-error" role="alert">{createError}</p>}
      {canManageInvites && createdInvite && copyError && <p className="server-error" role="alert">{copyError}</p>}
      {revokedId !== null && <p role="status">Revogação do convite #{revokedId} confirmada pelo servidor.</p>}
      {revokeError && <p className="server-error" role="alert">{revokeError}</p>}
      {!canManageInvites ? <div>
        {checking ? <p>Verificando acesso aos convites…</p> : <>
          {!authorized && <p>Gerenciamento de convites indisponível para o contexto atual.</p>}
          {listDenied && loadError && <p role="alert">{loadError}</p>}
          <button type="button" className="server-secondary-button" disabled={listDenied && authorized && loading} onClick={() => {
            pauseListAfterDenial.current = false;
            setRefusal('');
            if (authorized && listDenied) void loadInvites();
            else void onRefreshAuthorization();
          }}>Verificar acesso aos convites</button>
        </>}
      </div> : <>
        <form className="server-create-form" onSubmit={event => void handleCreate(event)}>
          <div className="server-invite-form-grid">
            <label className="server-field"><span>Expiração <small>(opcional)</small></span><input type="datetime-local" value={expiresAt} onChange={event => setExpiresAt(event.target.value)} /></label>
            <label className="server-field"><span>Limite de utilizações <small>(opcional)</small></span><input type="number" min="1" step="1" value={maxUses} onChange={event => setMaxUses(event.target.value)} placeholder="Sem limite" /></label>
          </div>
          <button className="server-primary-button" type="submit" disabled={creating}>{creating ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} Criar convite</button>
        </form>

        <div className="server-invite-list-heading"><div><h4>Convites existentes</h4><p>Metadados não incluem o token nem seu hash.</p></div><button type="button" className="server-secondary-button" onClick={() => void loadInvites()} disabled={loading}>Atualizar</button></div>
        {loading ? <div className="server-state" role="status"><LoaderCircle className="spin" size={18} />Carregando convites…</div>
          : loadError ? <div className="server-state server-state--error" role="alert"><strong>{loadError}</strong><button className="server-secondary-button" type="button" onClick={() => void loadInvites()}>Tentar novamente</button></div>
            : invites.length === 0 ? <div className="server-state server-state--empty"><Ticket size={21} /><strong>Nenhum convite criado</strong></div>
              : <div className="server-invite-list">{invites.map(invite => <article className="server-invite-row" key={invite.id}>
                <div className="server-invite-meta"><strong>Convite #{invite.id}</strong><span>Criado em {formatDate(invite.created_at)}</span><span>{invite.expires_at ? `Expira em ${formatDate(invite.expires_at)}` : 'Sem expiração'}</span><span>Usos: {invite.uses_count}{invite.max_uses === null ? ' (sem limite)' : ` de ${invite.max_uses}`}</span></div>
                <div className="server-invite-actions">{invite.revoked_at ? <span className="server-invite-revoked">Revogado em {formatDate(invite.revoked_at)}</span> : revokeConfirmation === invite.id ? <><span>Revogar este convite?</span><button className="server-danger-button" type="button" onClick={() => void handleRevoke(invite.id)} disabled={revokingId === invite.id}>{revokingId === invite.id && <LoaderCircle className="spin" size={14} />}Confirmar</button><button className="server-secondary-button" type="button" onClick={() => setRevokeConfirmation(null)} disabled={revokingId === invite.id}>Cancelar</button></> : <button className="server-danger-button" type="button" disabled={revokingId !== null} onClick={() => { setRevokeError(''); setRevokeConfirmation(invite.id); }}>Revogar</button>}</div>
              </article>)}</div>}
        {!loading && hasMore && <div className="server-load-more"><button className="server-secondary-button" type="button" disabled={loadingMore} onClick={() => void loadInvites(offset + SERVER_INVITE_PAGE_SIZE, true)}>{loadingMore && <LoaderCircle className="spin" size={14} />}Carregar mais convites</button></div>}
      </>}
    </section>
  );
}
