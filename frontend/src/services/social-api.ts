import { api } from '@/lib/api';

export type RelationshipStatus = 'NONE' | 'REQUEST_SENT' | 'REQUEST_RECEIVED' | 'FRIENDS';
export type UserDiscovery = {
  id: number;
  username: string;
  relationship_status: RelationshipStatus;
  friendship_id: number | null;
};
export type SocialListItem = {
  friendship_id: number;
  user_id: number;
  username: string;
  created_at: string;
};
export type SocialActionResponse = SocialListItem & {
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'CANCELLED' | 'REMOVED';
  responded_at: string | null;
};
export type SocialPage = { items: SocialListItem[]; total: number; limit: number; offset: number };
export type PrivacySettings = {
  allow_messages_from_strangers: boolean;
  allow_friend_requests: boolean;
};

export const SOCIAL_PAGE_SIZE = 20;

export async function searchUsers(query: string, limit = SOCIAL_PAGE_SIZE, offset = 0) {
  const response = await api.get<{ items: UserDiscovery[]; total: number; limit: number; offset: number }>(
    '/users/search', { params: { query, limit, offset } },
  );
  return response.data;
}
export async function listSocial(
  path: 'friends' | 'requests/received' | 'requests/sent',
  limit = SOCIAL_PAGE_SIZE,
  offset = 0,
) {
  const response = await api.get<SocialPage>(`/social/${path}`, { params: { limit, offset } });
  return response.data;
}
export async function sendFriendRequest(recipientId: number) {
  const response = await api.post<SocialActionResponse>('/social/requests', { recipient_id: recipientId });
  return response.data;
}
export async function acceptFriendRequest(id: number) {
  const response = await api.post<SocialActionResponse>(`/social/requests/${id}/accept`);
  return response.data;
}
export async function rejectFriendRequest(id: number) {
  const response = await api.post<SocialActionResponse>(`/social/requests/${id}/reject`);
  return response.data;
}
export async function cancelFriendRequest(id: number) {
  const response = await api.delete<SocialActionResponse>(`/social/requests/${id}`);
  return response.data;
}
export async function removeFriend(userId: number) {
  const response = await api.delete<SocialActionResponse>(`/social/friends/${userId}`);
  return response.data;
}
export async function getPrivacySettings() {
  const response = await api.get<PrivacySettings>('/users/me/privacy');
  return response.data;
}
export async function updatePrivacySettings(changes: Partial<PrivacySettings>) {
  const response = await api.patch<PrivacySettings>('/users/me/privacy', changes);
  return response.data;
}
