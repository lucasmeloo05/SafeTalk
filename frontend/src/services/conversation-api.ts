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
  edited_at?: string | null;
  is_deleted_for_everyone: boolean;
};

export type ConversationMessageSync = {
  items: MessageResponse[];
  updates_revision: number;
};

export type MessageUpdateEvent = {
  event_revision: number;
  message_state_revision: number;
  event_type: 'UPDATED' | 'DELETED';
  message: MessageResponse;
};

export type MessageUpdateEventPage = {
  items: MessageUpdateEvent[];
  updates_revision: number;
  next_cursor: number;
  has_more: boolean;
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

export async function loadLatestMessagesWithRevision(
  conversationId: number,
  limit = 50,
  signal?: AbortSignal,
): Promise<ConversationMessageSync> {
  const response = await api.get<ConversationMessageSync>(
    `/conversations/${conversationId}/messages/sync`,
    { params: { limit }, signal },
  );
  return response.data;
}

export async function listMessageUpdates(
  conversationId: number,
  afterRevision: number,
  limit = 50,
  signal?: AbortSignal,
): Promise<MessageUpdateEventPage> {
  const response = await api.get<MessageUpdateEventPage>(
    `/conversations/${conversationId}/message-updates`,
    { params: { after_revision: afterRevision, limit }, signal },
  );
  return response.data;
}

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

export type EditMessageResponse = {
  message: MessageResponse;
  message_state_revision: number;
};

export type MessageMutationResponse = EditMessageResponse;

export async function editMessage(
  conversationId: number,
  messageId: number,
  content: string,
): Promise<EditMessageResponse> {
  const response = await api.patch<EditMessageResponse>(
    `/conversations/${conversationId}/messages/${messageId}`,
    { content },
  );
  return response.data;
}

export async function deleteMessage(
  conversationId: number,
  messageId: number,
): Promise<MessageMutationResponse> {
  const response = await api.delete<MessageMutationResponse>(
    `/conversations/${conversationId}/messages/${messageId}`,
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
