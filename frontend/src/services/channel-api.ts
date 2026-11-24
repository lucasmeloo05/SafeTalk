import { api } from '@/lib/api';
import type { MessageResponse, MessageUpdateEvent } from './conversation-api';

export type Channel = { id: number; server_id: number; name: string; is_read_only: boolean; is_private: boolean; channel_type: 'TEXT' | 'VOICE' };
export type ChannelHistory = { items: MessageResponse[]; has_more: boolean; can_publish: boolean; updates_revision: number };
export type ChannelUpdate = Omit<MessageUpdateEvent, 'event_type'> & { event_type: 'CREATED' | 'UPDATED' | 'DELETED' };
export type ChannelChange = { message: MessageResponse; message_state_revision: number };
const path = (sid: number, cid: number) => `/servers/${sid}/channels/${cid}`;

export const channelApi = {
  async list(sid: number, offset: number, signal: AbortSignal) {
    return (await api.get<Channel[]>(`/servers/${sid}/channels`, { params: { offset, limit: 50 }, signal })).data;
  },
  async policy(sid: number, cid: number, readOnly: boolean) {
    return (await api.patch<Channel>(path(sid, cid), { is_read_only: readOnly })).data;
  },
  async history(sid: number, cid: number, signal: AbortSignal, before_id?: number) {
    return (await api.get<ChannelHistory>(path(sid, cid) + '/messages', { params: { before_id }, signal })).data;
  },
  async updates(sid: number, cid: number, after_revision: number, signal: AbortSignal) {
    return (await api.get<{ items: ChannelUpdate[]; next_cursor: number; has_more: boolean; can_publish: boolean }>(
      path(sid, cid) + '/message-updates', { params: { after_revision }, signal })).data;
  },
  async send(sid: number, cid: number, content: string) {
    return (await api.post<ChannelChange>(path(sid, cid) + '/messages', { content })).data;
  },
  async edit(sid: number, cid: number, id: number, content: string) {
    return (await api.patch<ChannelChange>(path(sid, cid) + '/messages/' + id, { content })).data;
  },
  async remove(sid: number, cid: number, id: number) {
    return (await api.delete<ChannelChange>(path(sid, cid) + '/messages/' + id)).data;
  },
  async report(sid: number, cid: number, id: number, reason: string) {
    await api.post(path(sid, cid) + '/messages/' + id + '/reports', { reason });
  },
};
