import { api } from '@/lib/api';

export const SERVER_PERMISSION_KEYS = [
  'kick_members',
  'ban_members',
  'unban_members',
  'manage_invites',
  'manage_roles',
  'mention_everyone',
] as const;

export type ServerPermissionKey = (typeof SERVER_PERMISSION_KEYS)[number];
export type ServerRolePermissions = Partial<Record<ServerPermissionKey, boolean>>;

export type ServerResponse = {
  is_adult?: boolean;
  id: number;
  owner_id: number;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
  everyone_permissions: Partial<Record<ServerPermissionKey, boolean>>;
};

export type ServerCreatePayload = {
  is_adult?: boolean;
  name: string;
  description?: string | null;
};

export type ServerMemberResponse = {
  user_id: number;
  username: string;
  joined_at: string;
  roles: ServerMemberRoleSummary[];
};

export type ServerMemberRoleSummary = {
  id: number;
  name: string;
  position: number;
};

export type ServerAuthorizationContextResponse = {
  server_id: number;
  user_id: number;
  is_owner: boolean;
  highest_role_position: number;
  effective_permissions: ServerPermissionKey[];
  has_manage_roles_permission: boolean;
};

export type ServerInviteCreatePayload = {
  expires_at?: string | null;
  max_uses?: number | null;
};

/** The raw token is returned only by invite creation and must not be persisted. */
export type ServerInviteCreatedResponse = {
  id: number;
  server_id: number;
  created_at: string;
  expires_at: string | null;
  max_uses: number | null;
  uses_count: number;
  revoked_at: string | null;
  token: string;
};

/** Listing responses deliberately omit the raw token and its stored hash. */
export type ServerInviteResponse = {
  id: number;
  server_id: number;
  created_at: string;
  expires_at: string | null;
  max_uses: number | null;
  uses_count: number;
  revoked_at: string | null;
};

export type ServerInviteMembershipResponse = {
  server_id: number;
  user_id: number;
  status: 'ACTIVE' | 'LEFT';
  joined_at: string;
  left_at: string | null;
};

export type ServerRoleResponse = {
  id: number;
  server_id: number;
  name: string;
  description: string | null;
  permissions: Record<string, unknown>;
  position: number;
  is_default: boolean;
  is_system_role: boolean;
  created_at: string;
};

export type ServerRoleCreatePayload = {
  name: string;
  description?: string | null;
  position: number;
  permissions?: ServerRolePermissions;
};

export type ServerRoleUpdatePayload = {
  name?: string;
  description?: string | null;
  position?: number;
  permissions?: ServerRolePermissions;
};

export const SERVER_INVITE_PAGE_SIZE = 20;

export const SERVER_MEMBER_PAGE_SIZE = 20;

export type ServerEveryonePermissionsResponse = {
  server_id: number;
  everyone_permissions: ServerRolePermissions;
};

function expectedPermissionHeaders(base: ServerRolePermissions) {
  const flags = Object.fromEntries(SERVER_PERMISSION_KEYS.map(key => [key, base[key] === true]));
  return { headers: { 'X-Expected-Permissions': JSON.stringify(flags) } };
}

export async function updateEveryonePermissions(serverId: number, permissions: ServerRolePermissions, base: ServerRolePermissions) {
  const payload = Object.fromEntries(SERVER_PERMISSION_KEYS.map(key => [key, permissions[key] === true]));
  const response = await api.patch<ServerEveryonePermissionsResponse>(
    `/servers/${serverId}/everyone-permissions`, payload, expectedPermissionHeaders(base),
  );
  return response.data;
}

export async function listServers(): Promise<ServerResponse[]> {
  const response = await api.get<ServerResponse[]>('/servers/');
  return response.data;
}

export async function createServer(payload: ServerCreatePayload): Promise<ServerResponse> {
  const response = await api.post<ServerResponse>('/servers/', payload);
  return response.data;
}

export async function getServer(serverId: number): Promise<ServerResponse> {
  const response = await api.get<ServerResponse>(`/servers/${serverId}`);
  return response.data;
}

export async function getServerAuthorizationContext(
  serverId: number,
): Promise<ServerAuthorizationContextResponse> {
  const response = await api.get<ServerAuthorizationContextResponse>(
    `/servers/${serverId}/authorization-context`,
  );
  return response.data;
}

export async function getServerMember(serverId: number, userId: number): Promise<ServerMemberResponse> {
  const response = await api.get<ServerMemberResponse>(`/servers/${serverId}/members/${userId}`);
  return response.data;
}

export async function listServerMembers(
  serverId: number,
  limit = SERVER_MEMBER_PAGE_SIZE,
  offset = 0,
): Promise<ServerMemberResponse[]> {
  const response = await api.get<ServerMemberResponse[]>(
    `/servers/${serverId}/members`,
    { params: { limit, offset } },
  );
  return response.data;
}

export async function createServerInvite(
  serverId: number,
  payload: ServerInviteCreatePayload = {},
): Promise<ServerInviteCreatedResponse> {
  const response = await api.post<ServerInviteCreatedResponse>(
    `/servers/${serverId}/invites`,
    payload,
  );
  return response.data;
}

export async function listServerInvites(
  serverId: number,
  limit = SERVER_INVITE_PAGE_SIZE,
  offset = 0,
): Promise<ServerInviteResponse[]> {
  const response = await api.get<ServerInviteResponse[]>(
    `/servers/${serverId}/invites`,
    { params: { limit, offset } },
  );
  return response.data;
}

export async function revokeServerInvite(serverId: number, inviteId: number): Promise<void> {
  await api.delete(`/servers/${serverId}/invites/${inviteId}`);
}

export async function acceptServerInvite(
  serverId: number,
  token: string,
): Promise<ServerInviteMembershipResponse> {
  const response = await api.post<ServerInviteMembershipResponse>(
    `/servers/${serverId}/invites/accept`,
    { token },
  );
  return response.data;
}

export async function listServerRoles(serverId: number): Promise<ServerRoleResponse[]> {
  const response = await api.get<ServerRoleResponse[]>(`/servers/${serverId}/roles`);
  return response.data;
}

export async function createServerRole(
  serverId: number,
  payload: ServerRoleCreatePayload,
): Promise<ServerRoleResponse> {
  const response = await api.post<ServerRoleResponse>(`/servers/${serverId}/roles`, payload);
  return response.data;
}

export async function getServerRole(serverId: number, roleId: number) {
  const response = await api.get<ServerRoleResponse>(`/servers/${serverId}/roles/${roleId}`);
  return response.data;
}

export async function updateServerRole(
  serverId: number,
  roleId: number,
  payload: ServerRoleUpdatePayload,
  base?: ServerRolePermissions,
): Promise<ServerRoleResponse> {
  const path = `/servers/${serverId}/roles/${roleId}`;
  if (payload.permissions !== undefined) {
    if (!base) throw new Error('A edição de permissões exige a configuração original.');
    const response = await api.patch<ServerRoleResponse>(path, payload, expectedPermissionHeaders(base));
    return response.data;
  }
  const response = await api.patch<ServerRoleResponse>(path, payload);
  return response.data;
}

export async function deleteServerRole(serverId: number, roleId: number): Promise<void> {
  await api.delete(`/servers/${serverId}/roles/${roleId}`);
}

export async function assignServerRoleToMember(
  serverId: number,
  userId: number,
  roleId: number,
): Promise<void> {
  await api.put(`/servers/${serverId}/members/${userId}/roles/${roleId}`);
}

export async function removeServerRoleFromMember(
  serverId: number,
  userId: number,
  roleId: number,
): Promise<void> {
  await api.delete(`/servers/${serverId}/members/${userId}/roles/${roleId}`);
}
