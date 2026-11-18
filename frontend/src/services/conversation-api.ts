import { api } from "@/lib/api";

export type ConversationResponse = {
  id: number;
  type: string;
  user_a_id: number | null;
  user_b_id: number | null;
  name: string | null;
  image_url: string | null;
  created_by: number;
  created_at: string;
  updated_at: string;
};

export type MessageResponse = {
  id: number;
  conversation_id: number;
  sender_id: number;
  content: string;
  created_at: string;
  updated_at: string;
  edited_at: string | null;
  is_deleted_for_everyone: boolean;
};

export type MessageReportResponse = {
  id: number;
  message_id: number;
  status: string;
  triage_status: string;
  analysis_status: string;
  created_at: string;
};

export type MessageCursor = {
  direction: 'after' | 'before';
  created_at: string;
  id: number;
};

export type MessageListOptions = {
  cursor?: MessageCursor;
  signal?: AbortSignal;
  latest?: boolean;
};

export async function listConversations(): Promise<ConversationResponse[]> {
  const response = await api.get<ConversationResponse[]>('/conversations/');
  return response.data;
}

export async function createDirectConversation(
  recipientId: number,
): Promise<ConversationResponse> {
  const response = await api.post<ConversationResponse>('/conversations/direct', {
    recipient_id: recipientId,
  });
  return response.data;
}

export async function listMessages(
  conversationId: number,
  limit: number,
  offset?: number,
  options: MessageListOptions = {},
): Promise<MessageResponse[]> {
  const params: Record<string, number | string | boolean> = { limit };
  if (offset !== undefined) params.offset = offset;
  if (options.latest) params.latest = true;
  if (options.cursor) {
    params[`${options.cursor.direction}_created_at`] = options.cursor.created_at;
    params[`${options.cursor.direction}_id`] = options.cursor.id;
  }
  const config: { params: Record<string, number | string | boolean>; signal?: AbortSignal } = { params };
  if (options.signal) config.signal = options.signal;
  const response = await api.get<MessageResponse[]>(
    `/conversations/${conversationId}/messages`,
    config,
  );
  return response.data;
}

export async function sendMessage(
  conversationId: number,
  content: string,
): Promise<MessageResponse> {
  const response = await api.post<MessageResponse>(
    `/conversations/${conversationId}/messages`,
    { content },
  );
  return response.data;
}

export async function reportMessage(
  messageId: number,
  reason: string,
): Promise<MessageReportResponse> {
  const response = await api.post<MessageReportResponse>('/reports', {
    message_id: messageId,
    reason,
  });
  return response.data;
}
