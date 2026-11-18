/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { ApiError } from '@/lib/api';

const { authMock, serviceMock } = vi.hoisted(() => ({
  authMock: vi.fn(),
  serviceMock: {
    listConversations: vi.fn(),
    createDirectConversation: vi.fn(),
    listMessages: vi.fn(),
    sendMessage: vi.fn(),
    reportMessage: vi.fn(),
  },
}));

vi.mock('@/context/auth-context', () => ({ useAuth: authMock }));
vi.mock('@/services/conversation-api', () => serviceMock);

import { ConversationWorkspace } from '@/components/conversation-workspace';

const currentUser = {
  id: 1,
  username: 'lucas_teste',
  email: 'lucas@example.test',
  birth_date: null,
  is_active: true,
  is_verified: false,
};

const conversation = {
  id: 10,
  type: 'DIRECT',
  user_a_id: 1,
  user_b_id: 2,
  name: null,
  image_url: null,
  created_by: 1,
  created_at: '2026-11-16T10:00:00Z',
  updated_at: '2026-11-16T10:00:00Z',
};

function message(id: number, senderId = 2, content = `Mensagem ${id}`, conversationId = 10) {
  const createdAt = new Date(Date.UTC(2026, 10, 16, 10, 0, id)).toISOString();
  return {
    id,
    conversation_id: conversationId,
    sender_id: senderId,
    content,
    created_at: createdAt,
    updated_at: createdAt,
    edited_at: null,
    is_deleted_for_everyone: false,
  };
}

function renderWorkspace(initialConversationId?: number) {
  return render(
    <MemoryRouter>
      <ConversationWorkspace createDialogOpen={false} onCreateDialogOpenChange={vi.fn()} initialConversationId={initialConversationId} />
    </MemoryRouter>,
  );
}

describe('fluxos do painel de conversas', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
  });

  beforeEach(() => {
    vi.resetAllMocks();
    authMock.mockReturnValue({ user: currentUser });
    serviceMock.listConversations.mockResolvedValue([conversation]);
    serviceMock.listMessages.mockResolvedValue([]);
    serviceMock.sendMessage.mockImplementation(async (_id: number, content: string) => message(101, 1, content));
    serviceMock.reportMessage.mockResolvedValue({ id: 3, message_id: 9, status: 'PENDING' });
  });

  it('carrega conversas e seleciona a primeira, identificando o contato pelo ID real', async () => {
    renderWorkspace();

    expect(await screen.findByRole('button', { name: 'Abrir conversa com Usuário #2' })).toBeInTheDocument();
    await waitFor(() => expect(serviceMock.listMessages).toHaveBeenCalledWith(10, 50, undefined, { latest: true }));
    expect(screen.getByText('Esta conversa ainda não tem mensagens')).toBeInTheDocument();
  });

  it('exibe estado vazio quando a API não retorna conversas', async () => {
    serviceMock.listConversations.mockResolvedValue([]);
    renderWorkspace();

    expect(await screen.findByText('Ainda sem conversas')).toBeInTheDocument();
    expect(screen.getByText('Seu espaço de conversas')).toBeInTheDocument();
    expect(serviceMock.listMessages).not.toHaveBeenCalled();
  });

  it('envia a mensagem e a adiciona uma única vez sem exceder 5.000 caracteres', async () => {
    const user = userEvent.setup();
    renderWorkspace();
    const composer = await screen.findByRole('textbox', { name: 'Mensagem' });
    await user.type(composer, '  Olá SafeTalk  ');
    await user.click(screen.getByRole('button', { name: 'Enviar mensagem' }));

    await waitFor(() => expect(serviceMock.sendMessage).toHaveBeenCalledWith(10, 'Olá SafeTalk'));
    expect(await screen.findByText('Olá SafeTalk')).toBeInTheDocument();
    expect(screen.getAllByText('Olá SafeTalk')).toHaveLength(1);
    expect(composer).toHaveAttribute('maxlength', '5000');
  });

  it('solicita mensagens anteriores pelo cursor composto e preserva a ordem', async () => {
    serviceMock.listMessages
      .mockResolvedValueOnce(Array.from({ length: 50 }, (_, index) => message(index + 51)))
      .mockResolvedValueOnce([message(1)]);
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Mensagem 51');
    await user.click(screen.getByRole('button', { name: 'Carregar mais mensagens' }));

    expect(await screen.findByText('Mensagem 1')).toBeInTheDocument();
    expect(serviceMock.listMessages).toHaveBeenNthCalledWith(2, 10, 50, undefined, {
      cursor: {
        direction: 'before',
        created_at: message(51).created_at,
        id: 51,
      },
    });
    const contents = screen.getAllByText(/^Mensagem \d+$/);
    expect(contents[0]).toHaveTextContent('Mensagem 1');
    expect(contents.at(-1)).toHaveTextContent('Mensagem 100');
  });

  it('denuncia pelo ID da mensagem e envia somente o motivo informado', async () => {
    serviceMock.listMessages.mockResolvedValue([message(9)]);
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Mensagem 9');
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 9' }));
    await user.click(screen.getByRole('menuitem', { name: 'Denunciar mensagem' }));
    const dialog = screen.getByRole('dialog', { name: 'Denunciar mensagem' });
    await user.type(within(dialog).getByRole('textbox', { name: 'Motivo' }), 'Conteúdo inadequado');
    await user.click(within(dialog).getByRole('button', { name: 'Enviar denúncia' }));

    await waitFor(() => expect(serviceMock.reportMessage).toHaveBeenCalledWith(9, 'Conteúdo inadequado'));
    expect(await screen.findByRole('status')).toHaveTextContent('Denúncia enviada');
    expect(serviceMock.reportMessage).not.toHaveBeenCalledWith(expect.anything(), expect.stringContaining('Mensagem 9'));
  });

  it('identifica mensagem apagada para todos e mantém disponível a denúncia', async () => {
    serviceMock.listMessages.mockResolvedValue([{
      ...message(19, 2, '[Mensagem excluída]'),
      is_deleted_for_everyone: true,
    }]);
    const user = userEvent.setup();
    renderWorkspace();

    expect(await screen.findByText('Apagada para todos')).toBeInTheDocument();
    expect(screen.getByText('[Mensagem excluída]')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 19' }));
    expect(screen.getByRole('menuitem', { name: 'Denunciar mensagem' })).toBeInTheDocument();
    await user.click(screen.getByRole('menuitem', { name: 'Denunciar mensagem' }));
    expect(screen.getByRole('dialog', { name: 'Denunciar mensagem' })).toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: 'Motivo' }), 'Conteúdo apagado que requer análise');
    await user.click(screen.getByRole('button', { name: 'Enviar denúncia' }));

    await waitFor(() => expect(serviceMock.reportMessage).toHaveBeenCalledWith(19, 'Conteúdo apagado que requer análise'));
  });

  it('mostra erro de acesso retornado ao tentar ler mensagens', async () => {
    serviceMock.listMessages.mockRejectedValue(new ApiError('Você não participa desta conversa.', 403));
    renderWorkspace();

    expect(await screen.findByRole('alert')).toHaveTextContent('Você não participa desta conversa.');
  });

  it('inicia conversa pelo endpoint existente com o ID informado, sem busca fictícia', async () => {
    function CreateDialogHarness() {
      const [open, setOpen] = useState(true);
      return (
        <MemoryRouter>
          <ConversationWorkspace createDialogOpen={open} onCreateDialogOpenChange={setOpen} />
        </MemoryRouter>
      );
    }
    serviceMock.listConversations.mockResolvedValue([]);
    serviceMock.createDirectConversation.mockResolvedValue({ ...conversation, user_b_id: 42 });
    const user = userEvent.setup();
    render(<CreateDialogHarness />);

    const dialog = await screen.findByRole('dialog', { name: 'Iniciar conversa' });
    await user.type(within(dialog).getByRole('spinbutton', { name: 'ID do usuário' }), '42');
    await user.click(within(dialog).getByRole('button', { name: 'Continuar' }));

    await waitFor(() => expect(serviceMock.createDirectConversation).toHaveBeenCalledWith(42));
    expect(screen.queryByRole('dialog', { name: 'Iniciar conversa' })).not.toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Abrir conversa com Usuário #42' })).toBeInTheDocument();
  });

  it('recebe mensagens automaticamente, deduplica IDs e mantém ordem cronológica', async () => {
    vi.useFakeTimers();
    serviceMock.listMessages
      .mockResolvedValueOnce([message(1)])
      .mockResolvedValueOnce([message(1), message(2)]);
    renderWorkspace();

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText('Mensagem 1')).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });

    expect(screen.getByText('Mensagem 2')).toBeInTheDocument();
    expect(screen.getAllByText('Mensagem 1')).toHaveLength(1);
    const displayed = screen.getAllByText(/^Mensagem [12]$/);
    expect(displayed.map((item) => item.textContent)).toEqual(['Mensagem 1', 'Mensagem 2']);
    expect(serviceMock.listMessages).toHaveBeenLastCalledWith(
      10,
      50,
      undefined,
      {
        cursor: { direction: 'after', created_at: message(1).created_at, id: 1 },
        signal: expect.any(AbortSignal),
      },
    );
  });

  it('seleciona initialConversationId quando a lista chega com latência', async () => {
    let resolveConversations!: (value: Array<typeof conversation>) => void;
    serviceMock.listConversations.mockImplementationOnce(
      () => new Promise((resolve) => { resolveConversations = resolve; }),
    );
    renderWorkspace(20);

    await waitFor(() => expect(resolveConversations).toBeDefined());
    await act(async () => {
      resolveConversations([
        conversation,
        { ...conversation, id: 20, user_b_id: 3 },
      ]);
    });

    const requested = await screen.findByRole('button', { name: 'Abrir conversa com Usuário #3' });
    expect(requested).toHaveAttribute('aria-current', 'page');
    await waitFor(() => expect(serviceMock.listMessages).toHaveBeenCalledWith(20, 50, undefined, { latest: true }));
  });

  it('não sobrescreve seleção manual após atualizar a lista de conversas', async () => {
    serviceMock.listConversations.mockResolvedValue([
      conversation,
      { ...conversation, id: 20, user_b_id: 3 },
    ]);
    serviceMock.listMessages.mockImplementation(async (conversationId: number) =>
      conversationId === 10 ? [message(1)] : [message(20, 3, 'Mensagem de B', 20)],
    );
    serviceMock.sendMessage.mockImplementationOnce(async (_id: number, content: string) => message(21, 1, content, 20));
    const user = userEvent.setup();
    renderWorkspace(10);
    expect(await screen.findByRole('button', { name: 'Abrir conversa com Usuário #2' })).toHaveAttribute('aria-current', 'page');

    await user.click(screen.getByRole('button', { name: 'Abrir conversa com Usuário #3' }));
    expect(await screen.findByText('Mensagem de B')).toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: 'Mensagem' }), 'Atualização de B');
    await user.click(screen.getByRole('button', { name: 'Enviar mensagem' }));
    expect(await screen.findByText('Atualização de B')).toBeInTheDocument();

    expect(screen.getByRole('button', { name: 'Abrir conversa com Usuário #3' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText('Mensagem de B')).toBeInTheDocument();
  });

  it('não avança o cursor pelo envio próprio antes de sincronizar mensagens recebidas', async () => {
    vi.useFakeTimers();
    const ownReply = message(3, 1, 'Resposta própria');
    serviceMock.listMessages
      .mockResolvedValueOnce([message(1)])
      .mockResolvedValueOnce([message(2, 2, 'Recebida antes'), ownReply]);
    serviceMock.sendMessage.mockResolvedValueOnce(ownReply);
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    fireEvent.change(screen.getByRole('textbox', { name: 'Mensagem' }), {
      target: { value: 'Resposta própria' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Enviar mensagem' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getAllByText('Resposta própria')).toHaveLength(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

    expect(screen.getByText('Recebida antes')).toBeInTheDocument();
    expect(screen.getAllByText('Resposta própria')).toHaveLength(1);
    expect(serviceMock.listMessages).toHaveBeenLastCalledWith(
      10,
      50,
      undefined,
      {
        cursor: { direction: 'after', created_at: message(1).created_at, id: 1 },
        signal: expect.any(AbortSignal),
      },
    );
  });

  it('não inicia uma segunda consulta enquanto o polling atual ainda está pendente', async () => {
    vi.useFakeTimers();
    let resolvePoll!: (value: ReturnType<typeof message>[]) => void;
    serviceMock.listMessages
      .mockResolvedValueOnce([message(1)])
      .mockImplementationOnce(() => new Promise((resolve) => { resolvePoll = resolve; }))
      .mockResolvedValueOnce([]);
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(2);

    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(2);

    await act(async () => { resolvePoll([message(2)]); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(3);
  });

  it('ignora uma resposta de polling atrasada após selecionar outra conversa', async () => {
    vi.useFakeTimers();
    let resolveOldPoll!: (value: ReturnType<typeof message>[]) => void;
    serviceMock.listConversations.mockResolvedValue([
      conversation,
      { ...conversation, id: 20, user_b_id: 3 },
    ]);
    serviceMock.listMessages.mockImplementation((conversationId: number) => {
      if (conversationId === 20) return Promise.resolve([message(20, 3, 'Mensagem da B', 20)]);
      if (serviceMock.listMessages.mock.calls.filter(([id]) => id === 10).length === 1) {
        return Promise.resolve([message(1, 2, 'Mensagem inicial de A')]);
      }
      return new Promise((resolve) => { resolveOldPoll = resolve; });
    });
    renderWorkspace();

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText('Mensagem inicial de A')).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(resolveOldPoll).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: 'Abrir conversa com Usuário #3' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText('Mensagem da B')).toBeInTheDocument();
    await act(async () => { resolveOldPoll([message(2, 2, 'Resposta atrasada de A')]); await Promise.resolve(); });

    expect(screen.getByText('Mensagem da B')).toBeInTheDocument();
    expect(screen.queryByText('Resposta atrasada de A')).not.toBeInTheDocument();
    expect(screen.queryByText('Mensagem inicial de A')).not.toBeInTheDocument();
  });

  it('pausa quando a aba está oculta e retoma quando volta a ficar visível', async () => {
    vi.useFakeTimers();
    serviceMock.listMessages.mockResolvedValueOnce([message(1)]).mockResolvedValue([message(1)]);
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const initialCalls = serviceMock.listMessages.mock.calls.length;
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    fireEvent(document, new Event('visibilitychange'));
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(initialCalls);

    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    fireEvent(document, new Event('visibilitychange'));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(initialCalls + 1);
  });

  it('pausa offline e retoma a consulta ao recuperar a conexão', async () => {
    vi.useFakeTimers();
    serviceMock.listMessages.mockResolvedValue([message(1)]);
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const initialCalls = serviceMock.listMessages.mock.calls.length;
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
    fireEvent(window, new Event('offline'));
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(initialCalls);

    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
    fireEvent(window, new Event('online'));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(initialCalls + 1);
  });

  it('recupera falha de rede no polling sem descartar mensagens carregadas', async () => {
    vi.useFakeTimers();
    serviceMock.listMessages
      .mockResolvedValueOnce([message(1)])
      .mockRejectedValueOnce(new Error('rede indisponível'))
      .mockResolvedValueOnce([message(2)]);
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByText(/Atualização automática pausada temporariamente/)).toBeInTheDocument();
    expect(screen.getByText('Mensagem 1')).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByText('Mensagem 2')).toBeInTheDocument();
    expect(screen.queryByText(/Atualização automática pausada temporariamente/)).not.toBeInTheDocument();
  });

  it('HTTP 403 encerra o polling e limpa as mensagens e estados da conversa', async () => {
    vi.useFakeTimers();
    serviceMock.listMessages
      .mockResolvedValueOnce([message(1)])
      .mockRejectedValueOnce(new ApiError('Acesso negado', 403));
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    fireEvent.click(screen.getByRole('button', { name: 'Opções da mensagem 1' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Denunciar mensagem' }));
    expect(screen.getByRole('dialog', { name: 'Denunciar mensagem' })).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

    expect(screen.getByRole('alert')).toHaveTextContent('Você perdeu o acesso a esta conversa');
    expect(screen.queryByText('Mensagem 1')).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Denunciar mensagem' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Mensagem' })).toBeDisabled();
    const callsAfterForbidden = serviceMock.listMessages.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(callsAfterForbidden);
  });

  it('encerra o timer de polling ao desmontar o painel', async () => {
    vi.useFakeTimers();
    serviceMock.listMessages.mockResolvedValue([message(1)]);
    const view = renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const callsBeforeUnmount = serviceMock.listMessages.mock.calls.length;
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(callsBeforeUnmount);
  });

  it('encerra o polling quando a sessão autenticada termina', async () => {
    vi.useFakeTimers();
    serviceMock.listMessages.mockResolvedValue([message(1)]);
    const view = renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const callsBeforeLogout = serviceMock.listMessages.mock.calls.length;
    authMock.mockReturnValue({ user: null });
    view.rerender(
      <MemoryRouter>
        <ConversationWorkspace createDialogOpen={false} onCreateDialogOpenChange={vi.fn()} />
      </MemoryRouter>,
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(callsBeforeLogout);
  });
});
