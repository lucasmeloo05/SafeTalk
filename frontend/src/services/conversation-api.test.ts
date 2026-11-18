import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiMock } = vi.hoisted(() => ({
  apiMock: { get: vi.fn(), post: vi.fn() },
}));

vi.mock('@/lib/api', () => ({ api: apiMock }));

import {
  createDirectConversation,
  listConversations,
  listMessages,
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
