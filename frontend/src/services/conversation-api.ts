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
  offset: number,
): Promise<MessageResponse[]> {
  const response = await api.get<MessageResponse[]>(
    `/conversations/${conversationId}/messages`,
    { params: { limit, offset } },
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
