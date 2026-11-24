import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { LoaderCircle, Plus, Shield, Trash2, UserRoundCog } from 'lucide-react';
import { ApiError } from '@/lib/api';
import {
  assignServerRoleToMember,
  createServerRole,
  deleteServerRole,
  listServerRoles,
  getServerRole,
  getServer,
  removeServerRoleFromMember,
  SERVER_PERMISSION_KEYS,
  updateServerRole,
  updateEveryonePermissions,
  type ServerAuthorizationContextResponse,
  type ServerMemberResponse,
  type ServerPermissionKey,
  type ServerRolePermissions,
  type ServerRoleResponse,
  type ServerRoleUpdatePayload,
} from '@/services/server-api';

const permissionLabels: Record<ServerPermissionKey, string> = {
  kick_members: 'Expulsar membros',
  ban_members: 'Banir membros',
  unban_members: 'Revogar banimentos',
  manage_invites: 'Gerenciar convites',
  manage_roles: 'Gerenciar cargos',
  mention_everyone: 'Mencionar todos',
};

function emptyPermissions(): Record<ServerPermissionKey, boolean> {
  return Object.fromEntries(SERVER_PERMISSION_KEYS.map(key => [key, false])) as Record<ServerPermissionKey, boolean>;
}

function permissionsFor(role: ServerRoleResponse): Record<ServerPermissionKey, boolean> {
  return Object.fromEntries(
    SERVER_PERMISSION_KEYS.map(key => [key, role.permissions[key] === true]),
  ) as Record<ServerPermissionKey, boolean>;
}

function roleErrorMessage(error: unknown, fallback: string) {
  if (!(error instanceof ApiError)) return fallback;
  if (error.status === 401) return 'Sua sessão expirou. Entre novamente para continuar.';
  if (error.status === 403) return error.message || 'A API não autorizou esta operação.';
  if (error.status === 404) return error.message || 'Servidor, cargo ou membro não encontrado.';
  if (error.status === 409) return error.message || 'A operação conflita com o estado atual do cargo.';
  if (error.status === 422) return error.message || 'Confira os campos e as permissões informadas.';
  return error.message || fallback;
}

function permissionsConflict(error: unknown) {
  return error instanceof ApiError && error.status === 409 && typeof error.detail === 'object' &&
    error.detail !== null && 'code' in error.detail && error.detail.code === 'permissions_conflict';
}

const conflictNotice = 'As permissões foram alteradas em outra sessão. Carregue a configuração atual e revise seu rascunho antes de salvar.';

function rebasePermissions(base: ServerRolePermissions, draft: ServerRolePermissions, latest: ServerRolePermissions) {
  const result = emptyPermissions();
  for (const key of SERVER_PERMISSION_KEYS) {
    const edited = (draft[key] === true) !== (base[key] === true);
    result[key] = (edited ? draft[key] : latest[key]) === true;
  }
  return result;
}

function EveryoneEditor({ serverId, current, authorized, onForbidden, onSaved }: {
  authorized: boolean;
  onForbidden: (error: unknown) => void;
  serverId: number;
  current: ServerRolePermissions;
  onSaved: (permissions: ServerRolePermissions) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ServerRolePermissions | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const pending = useRef(false);
  const [base, setBase] = useState<ServerRolePermissions>({});
  const [conflict, setConflict] = useState(false);

  async function reload() {
    if (!authorized || !draft || pending.current) return;
    pending.current = true;
    setSaving(true);
    try {
      const latest = (await getServer(serverId)).everyone_permissions;
      await onSaved(latest);
      setDraft(rebasePermissions(base, draft, latest));
      setBase(latest);
      setError('');
      setConflict(false);
    } catch (cause) {
      setError(roleErrorMessage(cause, 'Não foi possível carregar as permissões atuais.'));
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!authorized || !draft || pending.current || conflict) return;
    pending.current = true;
    setSaving(true);
    setError('');
    try {
      const result = await updateEveryonePermissions(serverId, draft, base);
      await onSaved(result.everyone_permissions);
      setDraft(null);
      setSaved(true);
    } catch (cause) {
      setConflict(permissionsConflict(cause));
      onForbidden(cause);
      setError(permissionsConflict(cause) ? conflictNotice : roleErrorMessage(cause, 'Não foi possível salvar as permissões de @everyone.'));
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  return <>
    {draft ? <form onSubmit={save}>
      <fieldset className="server-permission-fieldset" disabled={saving || !authorized}>
        <legend>Editar permissões de @everyone</legend>
        <div className="server-permission-grid">{SERVER_PERMISSION_KEYS.map(key =>
          <label className="server-permission-option" key={key}>
            <input type="checkbox" checked={draft[key] === true}
              onChange={event => setDraft({ ...draft, [key]: event.target.checked })} />
            {permissionLabels[key]}
          </label>
        )}</div>
        <div className="server-role-form-actions">
          <button className="server-primary-button" type="submit" disabled={conflict}>{saving ? 'Salvando…' : 'Salvar permissões'}</button>
          {conflict && <button type="button" className="server-secondary-button" onClick={() => void reload()}>Carregar configuração atual</button>}
          <button className="server-secondary-button" type="button" onClick={() => { setDraft(null); setError(''); }}>Cancelar</button>
        </div>
      </fieldset>
    </form> : <button className="server-secondary-button" type="button" disabled={!authorized} onClick={() => { setSaved(false); setConflict(false); setBase({ ...current }); setDraft({ ...current }); }}>Editar permissões de @everyone</button>}
    {error && <p className="server-error" role="alert">{error}</p>}
    {saved && <p className="server-success" role="status">Permissões de @everyone salvas.</p>}
  </>;
}

export function ServerRolesPanel({
  serverId,
  ownerId,
  onRoleEdited,
  onEveryoneSaved,
  onAssignmentChanged,
  members,
  membersLoading,
  assignmentRefreshPending,
  authorizationContext,
  authorizationContextLoading,
  authorizationContextError,
  onRefreshAuthorization,
  everyonePermissions,
}: {
  serverId: number;
  ownerId: number;
  onEveryoneSaved: (permissions: ServerRolePermissions) => Promise<void>;
  onRoleEdited: (role: ServerRoleResponse) => Promise<void>;
  onAssignmentChanged: (userId: number) => Promise<void>;
  members: ServerMemberResponse[];
  membersLoading: boolean;
  assignmentRefreshPending: boolean;
  authorizationContext: ServerAuthorizationContextResponse | null;
  authorizationContextLoading: boolean;
  authorizationContextError: string;
  onRefreshAuthorization: () => Promise<void>;
  everyonePermissions: Partial<Record<ServerPermissionKey, boolean>>;
}) {
  const generationRef = useRef(0);
  const listRequest = useRef(0);
  const roleReadSequence = useRef(0);
  const listedIds = useRef(new Set<number>());
  const individualReads = useRef(new Map<number, ServerRoleResponse>());
  const [roles, setRoles] = useState<ServerRoleResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [mutationError, setMutationError] = useState('');
  const [success, setSuccess] = useState('');
  const [originalRole, setOriginalRole] = useState<ServerRoleResponse | null>(null);
  const [roleConflict, setRoleConflict] = useState(false);
  const editingRoleId = originalRole?.id ?? null;
  const [roleName, setRoleName] = useState('');
  const [roleDescription, setRoleDescription] = useState('');
  const [rolePosition, setRolePosition] = useState('1');
  const [permissions, setPermissions] = useState<Record<ServerPermissionKey, boolean>>(emptyPermissions);
  const [saving, setSaving] = useState(false);
  const [deletingRoleId, setDeletingRoleId] = useState<number | null>(null);
  const [confirmDeleteRoleId, setConfirmDeleteRoleId] = useState<number | null>(null);
  const [selectedMemberId, setSelectedMemberId] = useState('');
  const [selectedRoleId, setSelectedRoleId] = useState('');
  const [assignmentBusy, setAssignmentBusy] = useState(false);
  const [assignmentFeedback, setAssignmentFeedback] = useState('');

  const orderedRoles = useMemo(
    () => [...roles].sort((a, b) => b.position - a.position || a.id - b.id),
    [roles],
  );
  const contextReady = !authorizationContextLoading && !authorizationContextError;
  const isOwner = contextReady && authorizationContext?.is_owner === true;
  const canManage = contextReady && (isOwner || authorizationContext?.has_manage_roles_permission === true);
  const level = authorizationContext?.highest_role_position ?? 0;
  const grants = authorizationContext?.effective_permissions ?? [];
  const canManageRole = (role: ServerRoleResponse) =>
    canManage && !role.is_system_role && (isOwner || role.position < level);
  const canTarget = (member: ServerMemberResponse) =>
    isOwner || (member.user_id !== ownerId && (member.user_id === authorizationContext?.user_id ||
      member.roles.every(role => role.position < level)));
  const holders = (roleId: number) => members.filter(member => member.roles.some(role => role.id === roleId));
  const canEdit = (role: ServerRoleResponse) => canManageRole(role) && holders(role.id).every(canTarget);
  const canDelete = (role: ServerRoleResponse) => canManageRole(role) && holders(role.id).length === 0;
  const assignableRoles = orderedRoles.filter(canManageRole);
  const target = members.find(member => member.user_id === Number(selectedMemberId) && canTarget(member));
  const selectedRole = assignableRoles.find(role => role.id === Number(selectedRoleId));
  const assigned = target?.roles.some(role => role.id === selectedRole?.id);
  const mayAssign = target && selectedRole && !assigned && (isOwner ||
    SERVER_PERMISSION_KEYS.every(key => selectedRole.permissions[key] !== true || grants.includes(key) ||
      everyonePermissions[key] === true || roles.some(role => role.permissions[key] === true &&
        target.roles.some(held => held.id === role.id))));
  const mayRemove = Boolean(target && selectedRole && assigned);
  const editingRole = roles.find(role => role.id === editingRoleId);
  const showForm = canManage && (editingRoleId === null ? isOwner || level > 1 : editingRole && canEdit(editingRole));
  const highestRole = orderedRoles[0];

  function refreshIfForbidden(error: unknown) {
    if (error instanceof ApiError && error.status === 403) void onRefreshAuthorization();
  }

  const loadRoles = useCallback(async () => {
    const generation = generationRef.current;
    const request = ++roleReadSequence.current;
    listRequest.current = request;
    individualReads.current.clear();
    const current = () => generation === generationRef.current && request === listRequest.current;
    setLoading(true);
    setLoadError('');
    try {
      const data = await listServerRoles(serverId);
      if (!current()) return;
      listedIds.current = new Set(data.map(role => role.id));
      setRoles(data.map(role => individualReads.current.get(role.id) ?? role));
    } catch (error) {
      if (!current() || individualReads.current.size > 0) return;
      setLoadError(roleErrorMessage(error, 'Não foi possível carregar os cargos. Tente novamente.'));
    } finally {
      if (current()) setLoading(false);
    }
  }, [serverId]);

  useEffect(() => {
    generationRef.current += 1;
    setRoles([]);
    setMutationError('');
    setSuccess('');
    setRoleConflict(false);
    setOriginalRole(null);
    void loadRoles();
    return () => { generationRef.current += 1; };
  }, [loadRoles]);

  function resetForm() {
    setRoleConflict(false);
    setOriginalRole(null);
    setRoleName('');
    setRoleDescription('');
    setRolePosition(String(isOwner ? (highestRole?.position ?? 0) + 1 : 1));
    setPermissions(emptyPermissions());
  }

  function beginEdit(role: ServerRoleResponse) {
    setRoleConflict(false);
    setOriginalRole(role);
    setRoleName(role.name);
    setRoleDescription(role.description ?? '');
    setRolePosition(String(role.position));
    setPermissions(permissionsFor(role));
    setMutationError('');
    setSuccess('');
  }

  async function reloadEditedRole() {
    if (!originalRole || saving) return;
    const generation = generationRef.current;
    const request = ++roleReadSequence.current;
    const current = () => generation === generationRef.current && request > listRequest.current &&
      listedIds.current.has(originalRole.id);
    setSaving(true);
    try {
      const latest = await getServerRole(serverId, originalRole.id);
      if (!current()) return;
      individualReads.current.set(latest.id, latest);
      setRoles(current => current.map(role => role.id === latest.id ? latest : role));
      setPermissions(rebasePermissions(permissionsFor(originalRole), permissions, permissionsFor(latest)));
      if (roleName === originalRole.name) setRoleName(latest.name);
      if (roleDescription === (originalRole.description ?? '')) setRoleDescription(latest.description ?? '');
      if (Number(rolePosition) === originalRole.position) setRolePosition(String(latest.position));
      setOriginalRole(latest);
      await onRoleEdited(latest);
      if (!current()) return;
      setMutationError('');
      setRoleConflict(false);
    } catch (cause) {
      if (current()) setMutationError(roleErrorMessage(cause, 'Não foi possível carregar o cargo atual.'));
    } finally {
      if (generation === generationRef.current) setSaving(false);
    }
  }

  async function handleSaveRole(event: FormEvent) {
    event.preventDefault();
    if (!showForm || saving || roleConflict || (!isOwner && Number(rolePosition) >= level)) return;
    const normalizedName = roleName.trim();
    const position = Number(rolePosition);
    if (!normalizedName || normalizedName.length > 50) {
      setMutationError('O nome do cargo deve ter entre 1 e 50 caracteres.');
      return;
    }
    if (!Number.isSafeInteger(position) || position < 1) {
      setMutationError('A posição deve ser um inteiro maior ou igual a 1.');
      return;
    }

    const payload = {
      name: normalizedName,
      description: roleDescription.trim() || null,
      position,
      permissions: { ...permissions } as ServerRolePermissions,
    };
    setSaving(true);
    setMutationError('');
    setSuccess('');
    try {
      if (!originalRole) {
        await createServerRole(serverId, payload);
        setSuccess('Cargo criado.');
      } else {
        const currentRole = roles.find(role => role.id === editingRoleId);
        if (!currentRole || currentRole.is_system_role) {
          setMutationError('Este cargo não pode ser editado.');
          return;
        }
        const changes: ServerRoleUpdatePayload = {};
        if (roleName !== originalRole.name && normalizedName !== originalRole.name) changes.name = normalizedName;
        if (roleDescription !== (originalRole.description ?? '') && payload.description !== originalRole.description) {
          changes.description = payload.description;
        }
        if (position !== originalRole.position) changes.position = position;
        if (SERVER_PERMISSION_KEYS.some(key => permissions[key] !== (originalRole.permissions[key] === true))) {
          changes.permissions = payload.permissions;
        }
        if (Object.keys(changes).length === 0) {
          resetForm();
          return;
        }
        const updated = changes.permissions
          ? await updateServerRole(serverId, originalRole.id, changes, permissionsFor(originalRole))
          : await updateServerRole(serverId, originalRole.id, changes);
        await onRoleEdited(updated);
        setSuccess('Cargo atualizado.');
      }
      resetForm();
      await loadRoles();
    } catch (error) {
      setRoleConflict(permissionsConflict(error));
      refreshIfForbidden(error);
      setMutationError(permissionsConflict(error) ? conflictNotice : roleErrorMessage(error, 'Não foi possível salvar o cargo.'));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteRole(roleId: number) {
    if (!roles.some(role => role.id === roleId && canDelete(role))) return;
    setDeletingRoleId(roleId);
    setMutationError('');
    setSuccess('');
    try {
      await deleteServerRole(serverId, roleId);
      setConfirmDeleteRoleId(null);
      setSuccess('Cargo excluído.');
      await loadRoles();
    } catch (error) {
      setMutationError(roleErrorMessage(error, 'Não foi possível excluir o cargo.'));
      refreshIfForbidden(error);
    } finally {
      setDeletingRoleId(null);
    }
  }

  async function handleAssignment(action: 'assign' | 'remove') {
    const userId = Number(selectedMemberId);
    const roleId = Number(selectedRoleId);
    if ((action === 'assign' ? !mayAssign : !mayRemove) || assignmentBusy || assignmentRefreshPending) return;
    const generation = generationRef.current;
    setAssignmentBusy(true);
    setAssignmentFeedback('');
    setMutationError('');
    try {
      if (action === 'assign') await assignServerRoleToMember(serverId, userId, roleId);
      else await removeServerRoleFromMember(serverId, userId, roleId);
    } catch (error) {
      if (generation !== generationRef.current) return;
      const failure = action === 'assign' ? 'Não foi possível atribuir o cargo.' : 'Não foi possível remover o cargo.';
      setMutationError([failure, roleErrorMessage(error, '')].filter(Boolean).join(' '));
      refreshIfForbidden(error);
      setAssignmentBusy(false);
      return;
    }
    if (generation !== generationRef.current) return;
    setAssignmentFeedback(action === 'assign' ? 'A atribuição foi confirmada pela API.' : 'A remoção foi confirmada pela API.');
    try {
      await onAssignmentChanged(userId);
    } finally {
      if (generation === generationRef.current) setAssignmentBusy(false);
    }
  }

  return (
    <section className="server-panel" aria-labelledby="server-roles-title">
      <header className="server-panel__header"><div><h3 id="server-roles-title"><Shield size={17} /> Cargos e permissões</h3><p>Permissões de cargos individuais são combinadas por união.</p></div></header>
      <div className="server-role-hierarchy-note">
        {highestRole ? <span>Maior posição cadastrada: <strong>{highestRole.name}</strong> · nível {highestRole.position}</span> : <span>Ainda não há cargos individuais; o nível hierárquico de membros sem cargos é zero.</span>}
        <small>@everyone é implícito e não aparece como cargo atribuído.</small>
        {authorizationContextLoading && <small role="status">Carregando seu contexto de autorização…</small>}
          {authorizationContextError && <small role="alert">{authorizationContextError}</small>}
            {authorizationContext && <>
              {!contextReady && <small>Último contexto confirmado</small>}
              <small>{authorizationContext.is_owner ? 'Seu contexto: proprietário, com autoridade especial independente dos cargos.' : `Sua maior posição individual: ${authorizationContext.highest_role_position}.`}</small>
              <small>Permissões efetivas: {authorizationContext.effective_permissions.length > 0 ? authorizationContext.effective_permissions.map(permission => permissionLabels[permission]).join(', ') : 'nenhuma permissão explícita'}.</small>
            </>}
      </div>
      {!isOwner && <div className="server-role-limitation" role="note">{canManage ? 'Administrador de cargos. Você pode gerenciar cargos abaixo da sua posição individual.' : 'Consulta de cargos. Os controles de gerenciamento estão indisponíveis.'}</div>}
      {mutationError && <p className="server-error" role="alert">{mutationError}</p>}
      {success && <p className="server-success" role="status">{success}</p>}

      {roleConflict && showForm && <button type="button" disabled={saving} onClick={() => void reloadEditedRole()}>Carregar configuração atual</button>}
      {showForm && <form className="server-create-form server-role-form" onSubmit={event => void handleSaveRole(event)}>
        <header><div><h4>{editingRoleId === null ? 'Criar cargo' : 'Editar cargo'}</h4><p>Posição maior representa hierarquia superior. O proprietário não depende de cargo para administrar.</p></div></header>
        <div className="server-role-form-grid">
          <label className="server-field"><span>Nome do cargo</span><input disabled={saving} value={roleName} onChange={event => setRoleName(event.target.value)} required maxLength={50} /></label>
          <label className="server-field"><span>Posição</span><input type="number" min="1" max={isOwner ? undefined : level - 1} step="1" disabled={saving} value={rolePosition} onChange={event => setRolePosition(event.target.value)} required /></label>
        </div>
        <label className="server-field"><span>Descrição <small>(opcional)</small></span><textarea disabled={saving} value={roleDescription} onChange={event => setRoleDescription(event.target.value)} maxLength={255} rows={2} /></label>
        <fieldset disabled={saving} className="server-permission-fieldset"><legend>Permissões deste cargo</legend><div className="server-permission-grid">
          {SERVER_PERMISSION_KEYS.map(key => <label key={key} className="server-permission-option"><input type="checkbox" disabled={!isOwner && !grants.includes(key) && editingRole?.permissions[key] !== true} checked={permissions[key]} onChange={event => setPermissions(current => ({ ...current, [key]: event.target.checked }))} /><span>{permissionLabels[key]}</span></label>)}
        </div></fieldset>
        <div className="server-role-form-actions"><button className="server-primary-button" type="submit" disabled={saving || roleConflict}>{saving ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />}{editingRoleId === null ? 'Criar cargo' : 'Salvar alterações'}</button>{editingRoleId !== null && <button className="server-secondary-button" type="button" onClick={resetForm} disabled={saving}>Cancelar edição</button>}</div>
      </form>}

      {loading ? <div className="server-state" role="status"><LoaderCircle className="spin" size={18} />Carregando cargos…</div>
        : loadError ? <div className="server-state server-state--error" role="alert"><strong>{loadError}</strong><button className="server-secondary-button" type="button" onClick={() => void loadRoles()}>Tentar novamente</button></div>
          : orderedRoles.length === 0 ? <div className="server-state server-state--empty"><Shield size={21} /><strong>Nenhum cargo individual configurado</strong></div>
            : <div className="server-role-list">{orderedRoles.map((role, index) => <article className="server-role-card" key={role.id}>
              <div className="server-role-card__header"><div><span className="server-role-position">POSIÇÃO {role.position}{index === 0 ? ' · MAIOR NÍVEL' : ''}</span><h4>{role.name}{role.is_system_role && <small className="server-system-role-badge">Sistema</small>}</h4><p>{role.description || 'Sem descrição'}</p></div>{canManageRole(role) && <div className="server-role-card__actions"><button className="server-secondary-button" type="button" disabled={saving || !canEdit(role)} onClick={() => beginEdit(role)}>Editar</button>{confirmDeleteRoleId === role.id ? <><button className="server-danger-button" type="button" onClick={() => void handleDeleteRole(role.id)} disabled={deletingRoleId === role.id}>{deletingRoleId === role.id && <LoaderCircle className="spin" size={14} />}Confirmar exclusão</button><button className="server-secondary-button" type="button" onClick={() => setConfirmDeleteRoleId(null)} disabled={deletingRoleId === role.id}>Cancelar</button></> : <button className="server-danger-button" type="button" disabled={!canDelete(role)} aria-label={`Excluir ${role.name}`} onClick={() => { setConfirmDeleteRoleId(role.id); setMutationError(''); }}><Trash2 size={14} />Excluir</button>}</div>}</div>
              <div className="server-role-permissions">{SERVER_PERMISSION_KEYS.filter(key => role.permissions[key] === true).length ? SERVER_PERMISSION_KEYS.filter(key => role.permissions[key] === true).map(key => <span className="server-permission-badge" key={key}>{permissionLabels[key]}</span>) : <span className="server-permission-none">Sem permissões explícitas</span>}</div>
            </article>)}</div>}

      {assignmentFeedback && <p className="server-success" role="status">{assignmentFeedback}</p>}
      {canManage && <section className="server-role-assignment" aria-labelledby="server-role-assignment-title">
        <header><div><h4 id="server-role-assignment-title"><UserRoundCog size={16} /> Atribuir ou remover cargo</h4><p>Selecione um membro ativo listado nesta página e um cargo individual.</p></div></header>
        <div className="server-role-assignment-grid">
          <label className="server-field"><span>Membro ativo</span><select value={selectedMemberId} onChange={event => setSelectedMemberId(event.target.value)} disabled={membersLoading || members.length === 0}><option value="">Selecione um membro</option>{members.filter(canTarget).map(member => <option key={member.user_id} value={member.user_id}>{member.username} · ID {member.user_id}</option>)}</select></label>
          <label className="server-field"><span>Cargo individual</span><select value={selectedRoleId} onChange={event => setSelectedRoleId(event.target.value)} disabled={loading || assignableRoles.length === 0}><option value="">Selecione um cargo</option>{assignableRoles.map(role => <option key={role.id} value={role.id}>{role.name} · posição {role.position}</option>)}</select></label>
        </div>
        <p className="server-role-limitation">As atribuições existentes são exibidas na lista de membros.</p>
        <div className="server-role-form-actions"><button className="server-primary-button" type="button" onClick={() => void handleAssignment('assign')} disabled={!mayAssign || assignmentBusy || assignmentRefreshPending || loading}>{assignmentBusy && <LoaderCircle className="spin" size={14} />}Atribuir</button><button className="server-secondary-button" type="button" onClick={() => void handleAssignment('remove')} disabled={!mayRemove || assignmentBusy || assignmentRefreshPending || loading}>Remover</button></div>
      </section>}

      <section className="server-everyone-note" aria-labelledby="server-everyone-title">
        <h4 id="server-everyone-title">Permissões de @everyone</h4>
        <p>Estado atual das permissões conhecidas. Elas se aplicam a todos os membros e se somam às permissões dos cargos individuais.</p>
        <div className="server-everyone-permissions" aria-label="Permissões atuais de @everyone">
          {SERVER_PERMISSION_KEYS.map(key => <span key={key} className={everyonePermissions[key] === true ? 'is-enabled' : 'is-disabled'}>
            {permissionLabels[key]}: {everyonePermissions[key] === true ? 'Ativa' : 'Inativa'}
          </span>)}
        </div>
        {authorizationContext?.is_owner && <EveryoneEditor key={serverId} serverId={serverId} current={everyonePermissions} authorized={isOwner} onForbidden={refreshIfForbidden} onSaved={onEveryoneSaved} />}
      </section>
    </section>
  );
}
