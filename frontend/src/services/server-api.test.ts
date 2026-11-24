import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/api';
import {
  acceptServerInvite,
  assignServerRoleToMember,
  createServer,
  createServerInvite,
  createServerRole,
  deleteServerRole,
  getServer,
  getServerAuthorizationContext,
  listServerInvites,
  listServerMembers,
  listServerRoles,
  listServers,
  revokeServerInvite,
  removeServerRoleFromMember,
  updateServerRole,
  updateEveryonePermissions,
} from '@/services/server-api';

describe('server-api', () => {
  afterEach(() => vi.restoreAllMocks());

  it('substitui @everyone com seis booleanos na raiz e descarta chaves desconhecidas', async () => {
    const response = { server_id: 3, everyone_permissions: { manage_invites: true } };
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: response });
    const input = { manage_invites: true, legacy: true };
    await expect(updateEveryonePermissions(3, input, { manage_roles: true })).resolves.toEqual(response);
    expect(patch).toHaveBeenCalledWith('/servers/3/everyone-permissions', {
      kick_members: false, ban_members: false, unban_members: false,
      manage_invites: true, manage_roles: false, mention_everyone: false,
    }, { headers: { 'X-Expected-Permissions': JSON.stringify({
      kick_members: false, ban_members: false, unban_members: false,
      manage_invites: false, manage_roles: true, mention_everyone: false,
    }) } });
  });

  it('envia a base original no cabeçalho do PATCH de permissões de cargo', async () => {
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: {} });
    const payload = { permissions: { kick_members: true } };
    await updateServerRole(3, 5, payload, { manage_roles: true });
    expect(patch).toHaveBeenCalledWith('/servers/3/roles/5', payload, {
      headers: { 'X-Expected-Permissions': JSON.stringify({
        kick_members: false, ban_members: false, unban_members: false,
        manage_invites: false, manage_roles: true, mention_everyone: false,
      }) },
    });
  });

  it('consulta a lista autenticada de servidores', async () => {
    const data = [{ id: 3, owner_id: 8, name: 'Equipe', description: null, created_at: '2026-01-01', updated_at: '2026-01-01', everyone_permissions: {} }];
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data });
    await expect(listServers()).resolves.toEqual(data);
    expect(get).toHaveBeenCalledWith('/servers/');
  });

  it('cria servidor com os campos aceitos pelo schema', async () => {
    const data = { id: 3, owner_id: 8, name: 'Equipe', description: 'Projeto', created_at: '2026-01-01', updated_at: '2026-01-01', everyone_permissions: {} };
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data });
    await expect(createServer({ name: 'Equipe', description: 'Projeto' })).resolves.toEqual(data);
    expect(post).toHaveBeenCalledWith('/servers/', { name: 'Equipe', description: 'Projeto' });
  });

  it('consulta detalhes e membros usando paginação existente', async () => {
    const server = { id: 3, owner_id: 8, name: 'Equipe', description: null, created_at: '2026-01-01', updated_at: '2026-01-01', everyone_permissions: { manage_invites: true } };
    const members = [{ user_id: 8, username: 'owner', joined_at: '2026-01-01', roles: [{ id: 2, name: 'Moderador', position: 4 }] }];
    const get = vi.spyOn(api, 'get').mockResolvedValueOnce({ data: server }).mockResolvedValueOnce({ data: members });
    await expect(getServer(3)).resolves.toEqual(server);
    await expect(listServerMembers(3, 20, 40)).resolves.toEqual(members);
    expect(get).toHaveBeenNthCalledWith(1, '/servers/3');
    expect(get).toHaveBeenNthCalledWith(2, '/servers/3/members', { params: { limit: 20, offset: 40 } });
  });

  it('consulta o contexto de autorização do usuário autenticado no servidor', async () => {
    const context = {
      server_id: 3,
      user_id: 8,
      is_owner: false,
      highest_role_position: 4,
      effective_permissions: ['manage_roles' as const, 'manage_invites' as const],
      has_manage_roles_permission: true,
    };
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: context });

    await expect(getServerAuthorizationContext(3)).resolves.toEqual(context);
    expect(get).toHaveBeenCalledWith('/servers/3/authorization-context');
  });

  it('usa os contratos reais de criação, listagem, revogação e aceite de convites', async () => {
    const created = { id: 21, server_id: 3, created_at: '2026-01-01T00:00:00Z', expires_at: null, max_uses: 2, uses_count: 0, revoked_at: null, token: 'one-time-token' };
    const invites = [{ id: 21, server_id: 3, created_at: '2026-01-01T00:00:00Z', expires_at: null, max_uses: 2, uses_count: 0, revoked_at: null }];
    const membership = { server_id: 3, user_id: 8, status: 'ACTIVE' as const, joined_at: '2026-01-01T00:00:00Z', left_at: null };
    const post = vi.spyOn(api, 'post').mockResolvedValueOnce({ data: created }).mockResolvedValueOnce({ data: membership });
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: invites });
    const remove = vi.spyOn(api, 'delete').mockResolvedValue({ data: undefined });

    await expect(createServerInvite(3, { expires_at: '2026-02-01T00:00:00Z', max_uses: 2 })).resolves.toEqual(created);
    await expect(listServerInvites(3, 20, 40)).resolves.toEqual(invites);
    await expect(revokeServerInvite(3, 21)).resolves.toBeUndefined();
    await expect(acceptServerInvite(3, 'one-time-token')).resolves.toEqual(membership);

    expect(post).toHaveBeenNthCalledWith(1, '/servers/3/invites', { expires_at: '2026-02-01T00:00:00Z', max_uses: 2 });
    expect(get).toHaveBeenCalledWith('/servers/3/invites', { params: { limit: 20, offset: 40 } });
    expect(remove).toHaveBeenCalledWith('/servers/3/invites/21');
    expect(post).toHaveBeenNthCalledWith(2, '/servers/3/invites/accept', { token: 'one-time-token' });
  });

  it('usa os métodos e caminhos reais de cargos e atribuições de membros', async () => {
    const role = { id: 5, server_id: 3, name: 'Ajudante', description: null, permissions: { manage_invites: true }, position: 2, is_default: false, is_system_role: false, created_at: '2026-01-01T00:00:00Z' };
    const get = vi.spyOn(api, 'get').mockResolvedValue({ data: [role] });
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: role });
    const patch = vi.spyOn(api, 'patch').mockResolvedValue({ data: role });
    const put = vi.spyOn(api, 'put').mockResolvedValue({ data: undefined });
    const remove = vi.spyOn(api, 'delete').mockResolvedValue({ data: undefined });

    await expect(listServerRoles(3)).resolves.toEqual([role]);
    await expect(createServerRole(3, { name: 'Ajudante', position: 2, permissions: { manage_invites: true } })).resolves.toEqual(role);
    await expect(updateServerRole(3, 5, { position: 3 })).resolves.toEqual(role);
    await expect(deleteServerRole(3, 5)).resolves.toBeUndefined();
    await expect(assignServerRoleToMember(3, 8, 5)).resolves.toBeUndefined();
    await expect(removeServerRoleFromMember(3, 8, 5)).resolves.toBeUndefined();

    expect(get).toHaveBeenCalledWith('/servers/3/roles');
    expect(post).toHaveBeenCalledWith('/servers/3/roles', { name: 'Ajudante', position: 2, permissions: { manage_invites: true } });
    expect(patch).toHaveBeenCalledWith('/servers/3/roles/5', { position: 3 });
    expect(remove).toHaveBeenNthCalledWith(1, '/servers/3/roles/5');
    expect(put).toHaveBeenCalledWith('/servers/3/members/8/roles/5');
    expect(remove).toHaveBeenNthCalledWith(2, '/servers/3/members/8/roles/5');
  });
});
