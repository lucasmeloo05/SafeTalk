import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowLeft, LoaderCircle, Server, Users } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { DashboardLayout } from '@/components/dashboard-layout';
import { ServerInvitesPanel } from '@/components/server-invites-panel';
import { ServerChannels } from '@/components/channel-messages';
import { ServerRolesPanel } from '@/components/server-roles-panel';
import { ApiError } from '@/lib/api';
import { useAuth } from '@/context/auth-context';
import { getServer, getServerAuthorizationContext, getServerMember, listServerMembers, SERVER_MEMBER_PAGE_SIZE, type ServerAuthorizationContextResponse, type ServerMemberResponse, type ServerResponse } from '@/services/server-api';

function errorMessage(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 401) return 'Sua sessão expirou. Entre novamente para continuar.';
  if (error.status === 403) return 'A API não autorizou a consulta deste servidor.';
  if (error.status === 404) return 'Servidor indisponível. Confira sua participação e a idade declarada para acesso +18.';
  if (error.status === 422) return error.message;
  return error.message;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

export function ServerDetailsPage() {
  const { serverId: rawServerId } = useParams();
  const serverId = Number(rawServerId);
  return <ServerDetails key={rawServerId} serverId={serverId} />;
}

function ServerDetails({ serverId }: { serverId: number }) {
  const validId = Number.isSafeInteger(serverId) && serverId > 0;
  const { user } = useAuth();
  const requestGeneration = useRef(0);
  const contextRequest = useRef(0);
  const roleEdits = useRef(0);
  const pendingPageEdits = useRef<Map<number, ServerMemberResponse['roles'][number]> | null>(null);
  const [memberToRefresh, setMemberToRefresh] = useState<number | null>(null);
  const [memberRefreshFailed, setMemberRefreshFailed] = useState(false);
  const [server, setServer] = useState<ServerResponse | null>(null);
  const [authorizationContext, setAuthorizationContext] = useState<ServerAuthorizationContextResponse | null>(null);
  const [serverLoading, setServerLoading] = useState(true);
  const [authorizationContextLoading, setAuthorizationContextLoading] = useState(true);
  const [serverError, setServerError] = useState('');
  const [authorizationContextError, setAuthorizationContextError] = useState('');
  const [members, setMembers] = useState<ServerMemberResponse[]>([]);
  const [memberOffset, setMemberOffset] = useState(0);
  const [hasMoreMembers, setHasMoreMembers] = useState(false);
  const [membersLoading, setMembersLoading] = useState(true);
  const [membersError, setMembersError] = useState('');
  const [loadingMore, setLoadingMore] = useState(false);

  const loadFirstMembers = useCallback(async (generation: number) => {
    if (generation !== requestGeneration.current) return;
    setMembersLoading(true);
    setMembersError('');
    try {
      const page = await listServerMembers(serverId);
      if (generation !== requestGeneration.current) return;
      setMembers(page);
      setMemberOffset(0);
      setHasMoreMembers(page.length === SERVER_MEMBER_PAGE_SIZE);
    } catch (error) {
      if (generation === requestGeneration.current) {
        setMembersError(errorMessage(error, 'Não foi possível carregar os membros.'));
      }
    } finally {
      if (generation === requestGeneration.current) setMembersLoading(false);
    }
  }, [serverId]);

  const refreshContext = useCallback(async (generation: number) => {
    if (generation !== requestGeneration.current) return;
    const request = ++contextRequest.current;
    const isCurrent = () => generation === requestGeneration.current && request === contextRequest.current;
    setAuthorizationContextLoading(true);
    try {
      const context = await getServerAuthorizationContext(serverId);
      if (!isCurrent()) return;
      setAuthorizationContext(context);
      setAuthorizationContextError('');
    } catch (error) {
      if (!isCurrent()) return;
      setAuthorizationContextError(errorMessage(error, 'Não foi possível atualizar suas permissões.'));
    } finally {
      if (isCurrent()) setAuthorizationContextLoading(false);
    }
  }, [serverId]);

  useEffect(() => {
    const generation = ++requestGeneration.current;
    const invalidate = () => { ++requestGeneration.current; };
    setServer(null);
    setAuthorizationContext(null);
    setMembers([]);
    setServerError('');
    setAuthorizationContextError('');
    setMembersError('');
    setServerLoading(true);
    setAuthorizationContextLoading(true);
    setMembersLoading(true);
    setLoadingMore(false);
    setMemberOffset(0);
    setHasMoreMembers(false);
    if (!validId) {
      setServerError('Identificador de servidor inválido.');
      setServerLoading(false);
      setAuthorizationContextLoading(false);
      setMembersLoading(false);
      return invalidate;
    }
    getServer(serverId).then(data => { if (generation === requestGeneration.current) setServer(data); })
      .catch(error => { if (generation === requestGeneration.current) setServerError(errorMessage(error, 'Não foi possível carregar o servidor.')); })
      .finally(() => { if (generation === requestGeneration.current) setServerLoading(false); });
    void refreshContext(generation);
    void loadFirstMembers(generation);
    return invalidate;
  }, [serverId, validId, loadFirstMembers, refreshContext]);

  const renderedGeneration = requestGeneration.current;

  const refreshAuthorization = useCallback(() => refreshContext(renderedGeneration), [refreshContext, renderedGeneration]);

  async function refreshAssignedMember(userId: number, generation: number) {
    if (generation !== requestGeneration.current) return;
    setMemberToRefresh(userId);
    setMemberRefreshFailed(false);
    try {
      while (generation === requestGeneration.current) {
        const revision = roleEdits.current;
        const member = await getServerMember(serverId, userId);
        if (generation !== requestGeneration.current) return;
        // Uma edição de cargo já atualizou os nomes e posições exibidos durante este GET.
        if (revision !== roleEdits.current) continue;
        setMembers(current => current.map(row => row.user_id === userId ? member : row));
        setMemberToRefresh(null);
        return;
      }
    } catch {
      if (generation === requestGeneration.current) setMemberRefreshFailed(true);
    }
  }

  async function loadMoreMembers() {
    if (pendingPageEdits.current || !hasMoreMembers || !validId) return;
    const edits = new Map<number, ServerMemberResponse['roles'][number]>();
    pendingPageEdits.current = edits;
    const nextOffset = memberOffset + SERVER_MEMBER_PAGE_SIZE;
    const generation = requestGeneration.current;
    setLoadingMore(true);
    setMembersError('');
    try {
      const next = await listServerMembers(serverId, SERVER_MEMBER_PAGE_SIZE, nextOffset);
      if (generation !== requestGeneration.current) return;
      const page = next.map(member => ({
        ...member,
        roles: member.roles.map(role => edits.get(role.id) ?? role)
          .sort((a, b) => b.position - a.position || a.id - b.id),
      }));
      setMembers(current => [...current, ...page.filter(item => !current.some(existing => existing.user_id === item.user_id))]);
      setMemberOffset(nextOffset);
      setHasMoreMembers(next.length === SERVER_MEMBER_PAGE_SIZE);
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      setMembersError(errorMessage(error, 'Não foi possível carregar mais membros.'));
    } finally {
      if (pendingPageEdits.current === edits) pendingPageEdits.current = null;
      if (generation === requestGeneration.current) setLoadingMore(false);
    }
  }

  return (
    <DashboardLayout title={server?.name ?? 'Detalhes do servidor'} description="Informações e membros ativos deste servidor." headerAction={<Link className="server-secondary-button" to="/servidores"><ArrowLeft size={15} /> Voltar aos servidores</Link>}>
      <section className="server-page">
        {serverLoading ? <div className="server-state" role="status"><LoaderCircle className="spin" size={19} />Carregando servidor…</div>
          : serverError ? <section className="server-panel"><div className="server-state server-state--error" role="alert"><strong>{serverError}</strong><Link className="server-secondary-button" to="/servidores">Voltar à lista</Link></div></section>
            : server && <>
              <section className="server-detail-hero"><span className="server-detail-hero__icon"><Server size={25} /></span><div><span className="dashboard-eyebrow">SERVIDOR</span><h2>{server.name}</h2><p>{server.description || 'Este servidor ainda não possui descrição.'}</p></div><span className="server-membership-badge">{server.owner_id === user?.id ? 'Proprietário' : 'Membro ativo'}</span></section>
              <section className="server-panel" aria-labelledby="server-members-title">
                <header className="server-panel__header"><div><h3 id="server-members-title"><Users size={17} /> Membros ativos</h3><p>Participantes retornados pelo servidor</p></div><span className="server-count-badge">{members.length}{hasMoreMembers ? '+' : ''}</span></header>
                {membersLoading ? <div className="server-state" role="status"><LoaderCircle className="spin" size={19} />Carregando membros…</div>
                  : membersError && members.length === 0 ? <div className="server-state server-state--error" role="alert"><strong>{membersError}</strong><button className="server-secondary-button" type="button" onClick={() => void loadFirstMembers(renderedGeneration)}>Tentar novamente</button></div>
                    : members.length === 0 ? <div className="server-state server-state--empty"><Users size={22} /><strong>Nenhum membro ativo listado</strong></div>
                      : <div className="server-member-list">{members.map(member => <article className="server-member-row" key={member.user_id}><span className="server-member-avatar">{member.username.slice(0, 1).toUpperCase()}</span><span className="server-member-identity"><strong>{member.username}</strong><small>Entrou em {formatDate(member.joined_at)}</small><span className="server-member-roles" aria-label={`Cargos de ${member.username}`}>{member.roles.length > 0 ? member.roles.map(role => <span className="server-member-role-badge" key={role.id}>{role.name} · posição {role.position}</span>) : <small>Sem cargos individuais</small>}</span></span>{member.user_id === server.owner_id && <span className="server-owner-label">Proprietário</span>}</article>)}</div>}
                {memberRefreshFailed && memberToRefresh !== null && <div role="alert" className="server-error">
                  A alteração foi salva, mas não foi possível atualizar a lista de cargos do membro.
                  <button className="server-secondary-button" type="button" onClick={() => void refreshAssignedMember(memberToRefresh, renderedGeneration)}>Atualizar membro novamente</button>
                </div>}
                {membersError && members.length > 0 && <p className="server-error" role="alert">{membersError}</p>}
                {!membersLoading && hasMoreMembers && <div className="server-load-more"><button className="server-secondary-button" type="button" onClick={() => void loadMoreMembers()} disabled={loadingMore}>{loadingMore && <LoaderCircle className="spin" size={15} />}Carregar mais membros</button></div>}
              </section>
              {user && <ServerChannels serverId={server.id} userId={user.id} owner={authorizationContext?.is_owner === true && !authorizationContextLoading && !authorizationContextError} />}
              <ServerRolesPanel
                onRefreshAuthorization={refreshAuthorization}
                serverId={server.id}
                ownerId={server.owner_id}
                onAssignmentChanged={async userId => {
                  const generation = renderedGeneration;
                  if (generation !== requestGeneration.current) return;
                  await Promise.all([
                    refreshAssignedMember(userId, generation),
                    userId === user?.id && refreshContext(generation),
                  ]);
                }}
                onRoleEdited={async updated => {
                  if (renderedGeneration !== requestGeneration.current) return;
                  ++roleEdits.current;
                  pendingPageEdits.current?.set(updated.id, { id: updated.id, name: updated.name, position: updated.position });
                  setMembers(current => current.map(member => ({
                    ...member,
                    roles: member.roles.map(role => role.id === updated.id ? updated : role)
                      .sort((a, b) => b.position - a.position || a.id - b.id),
                  })));
                  await refreshContext(requestGeneration.current);
                }}
                members={members}
                membersLoading={membersLoading}
                assignmentRefreshPending={memberToRefresh !== null}
                authorizationContext={authorizationContext}
                authorizationContextLoading={authorizationContextLoading}
                authorizationContextError={authorizationContextError}
                everyonePermissions={server.everyone_permissions}
                onEveryoneSaved={async permissions => {
                  if (renderedGeneration !== requestGeneration.current) return;
                  setServer(current => current?.id === server.id ? { ...current, everyone_permissions: permissions } : current);
                  await refreshContext(renderedGeneration);
                }}
              />
              {authorizationContextError && <button disabled={authorizationContextLoading} className="server-secondary-button" type="button" onClick={() => void refreshContext(renderedGeneration)}>Atualizar contexto de autorização novamente</button>}
              <ServerInvitesPanel
                serverId={server.id}
                authorized={!authorizationContextLoading && !authorizationContextError && Boolean(
                  authorizationContext?.is_owner || authorizationContext?.effective_permissions.includes('manage_invites')
                )}
                checking={authorizationContextLoading}
                onRefreshAuthorization={refreshAuthorization}
              />
            </>}
      </section>
    </DashboardLayout>
  );
}
