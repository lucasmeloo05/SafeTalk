import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiMock } = vi.hoisted(() => ({
  apiMock: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

vi.mock('@/lib/api', () => ({ api: apiMock }));

import {
  createDirectConversation,
  deleteMessage,
  editMessage,
  listConversations,
  listMessageUpdates,
  listMessages,
  loadLatestMessagesWithRevision,
  reportMessage,
  sendMessage,
} from '@/services/conversation-api';

describe('serviços de conversas e mensagens', () => {
  beforeEach(() => vi.resetAllMocks());

  it('lista conversas pelo endpoint autenticado', async () => {
    const conversations = [{ id: 12, type: 'DIRECT' }];
    apiMock.get.mockResolvedValue({ data: conversations });

    await expect(listConversations()).resolves.toEqual(conversations);
    expect(apiMock.get).toHaveBeenCalledWith('/conversations/');
  });

  it('cria conversa direta com recipient_id do contrato real', async () => {
    const conversation = { id: 12, type: 'DIRECT' };
    apiMock.post.mockResolvedValue({ data: conversation });

    await expect(createDirectConversation(42)).resolves.toEqual(conversation);
    expect(apiMock.post).toHaveBeenCalledWith('/conversations/direct', {
      recipient_id: 42,
    });
  });

  it('envia limit e offset na listagem cronológica paginada', async () => {
    const messages = [{ id: 1, content: 'Olá' }];
    apiMock.get.mockResolvedValue({ data: messages });

    await expect(listMessages(12, 50, 50)).resolves.toEqual(messages);
    expect(apiMock.get).toHaveBeenCalledWith('/conversations/12/messages', {
      params: { limit: 50, offset: 50 },
    });
  });

  it('solicita explicitamente a janela mais recente sem alterar offsets legados', async () => {
    apiMock.get.mockResolvedValue({ data: [] });

    await expect(listMessages(12, 50, undefined, { latest: true })).resolves.toEqual([]);
    expect(apiMock.get).toHaveBeenCalledWith('/conversations/12/messages', {
      params: { limit: 50, latest: true },
    });
  });

  it('carrega a janela inicial e a revisão no mesmo endpoint autenticado', async () => {
    const page = { items: [{ id: 22, content: 'Atual' }], updates_revision: 8 };
    const controller = new AbortController();
    apiMock.get.mockResolvedValue({ data: page });

    await expect(loadLatestMessagesWithRevision(12, 50, controller.signal)).resolves.toEqual(page);
    expect(apiMock.get).toHaveBeenCalledWith('/conversations/12/messages/sync', {
      params: { limit: 50 },
      signal: controller.signal,
    });
  });

  it('consulta páginas de eventos usando o cursor aprovado e signal de cancelamento', async () => {
    const page = { items: [], updates_revision: 12, next_cursor: 10, has_more: true };
    const controller = new AbortController();
    apiMock.get.mockResolvedValue({ data: page });

    await expect(listMessageUpdates(12, 9, 1, controller.signal)).resolves.toEqual(page);
    expect(apiMock.get).toHaveBeenCalledWith('/conversations/12/message-updates', {
      params: { after_revision: 9, limit: 1 },
      signal: controller.signal,
    });
  });

  it('envia cursor composto e sinal de cancelamento para consulta incremental', async () => {
    const messages = [{ id: 22, content: 'Nova' }];
    const controller = new AbortController();
    apiMock.get.mockResolvedValue({ data: messages });

    await expect(listMessages(
      12,
      50,
      undefined,
      {
        cursor: { direction: 'after', created_at: '2026-11-17T12:00:00Z', id: 21 },
        signal: controller.signal,
      },
    )).resolves.toEqual(messages);
    expect(apiMock.get).toHaveBeenCalledWith('/conversations/12/messages', {
      params: {
        limit: 50,
        after_created_at: '2026-11-17T12:00:00Z',
        after_id: 21,
      },
      signal: controller.signal,
    });
  });

  it('envia somente content no corpo da mensagem', async () => {
    const message = { id: 9, conversation_id: 12, content: 'Olá' };
    apiMock.post.mockResolvedValue({ data: message });

    await expect(sendMessage(12, 'Olá')).resolves.toEqual(message);
    expect(apiMock.post).toHaveBeenCalledWith('/conversations/12/messages', {
      content: 'Olá',
    });
  });

  it('edita mensagem pelo endpoint existente enviando somente content', async () => {
    const result = {
      message: { id: 9, conversation_id: 12, content: 'Atualizada', edited_at: '2026-11-18T12:00:00Z' },
      message_state_revision: 4,
    };
    apiMock.patch.mockResolvedValue({ data: result });

    await expect(editMessage(12, 9, 'Atualizada')).resolves.toEqual(result);
    expect(apiMock.patch).toHaveBeenCalledWith(
      '/conversations/12/messages/9',
      { content: 'Atualizada' },
    );
  });

  it('solicita exclusão global no endpoint da conversa e recebe a revisão aplicada', async () => {
    const result = {
      message: { id: 9, conversation_id: 12, content: 'Esta mensagem foi excluída', is_deleted_for_everyone: true },
      message_state_revision: 7,
    };
    apiMock.delete.mockResolvedValue({ data: result });

    await expect(deleteMessage(12, 9)).resolves.toEqual(result);
    expect(apiMock.delete).toHaveBeenCalledWith('/conversations/12/messages/9');
  });

  it('denuncia a mensagem pelo ID real e motivo informado', async () => {
    const report = { id: 3, message_id: 9, status: 'PENDING' };
    apiMock.post.mockResolvedValue({ data: report });

    await expect(reportMessage(9, 'Motivo de teste')).resolves.toEqual(report);
    expect(apiMock.post).toHaveBeenCalledWith('/reports', {
      message_id: 9,
      reason: 'Motivo de teste',
    });
  });
});
