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
    loadLatestMessagesWithRevision: vi.fn(),
    listMessageUpdates: vi.fn(),
    sendMessage: vi.fn(),
    editMessage: vi.fn(),
    deleteMessage: vi.fn(),
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
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValue({ items: [], updates_revision: 0 });
    serviceMock.listMessageUpdates.mockResolvedValue({
      items: [], updates_revision: 0, next_cursor: 0, has_more: false,
    });
    serviceMock.sendMessage.mockImplementation(async (_id: number, content: string) => message(101, 1, content));
    serviceMock.editMessage.mockImplementation(async (conversationId: number, id: number, content: string) => ({
      message: { ...message(id, 1, content, conversationId), edited_at: new Date().toISOString() },
      message_state_revision: 1,
    }));
    serviceMock.deleteMessage.mockImplementation(async (conversationId: number, id: number) => ({
      message: {
        ...message(id, 1, 'Esta mensagem foi excluída', conversationId),
        updated_at: new Date().toISOString(),
        is_deleted_for_everyone: true,
      },
      message_state_revision: 1,
    }));
    serviceMock.reportMessage.mockResolvedValue({ id: 3, message_id: 9, status: 'PENDING' });
  });

  it('carrega conversas e seleciona a primeira, identificando o contato pelo ID real', async () => {
    renderWorkspace();

    expect(await screen.findByRole('button', { name: 'Abrir conversa com Usuário #2' })).toBeInTheDocument();
    await waitFor(() => expect(serviceMock.loadLatestMessagesWithRevision).toHaveBeenCalledWith(
      10, 50, expect.any(AbortSignal),
    ));
    expect(screen.getByText('Esta conversa ainda não tem mensagens')).toBeInTheDocument();
  });

  it('inicializa o cursor de eventos com a revisão do snapshot do histórico', async () => {
    vi.useFakeTimers();
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({
      items: [message(1)],
      updates_revision: 12,
    });
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

    expect(serviceMock.listMessageUpdates).toHaveBeenCalledWith(10, 12, 50, expect.any(AbortSignal));
  });

  it('exibe estado vazio quando a API não retorna conversas', async () => {
    serviceMock.listConversations.mockResolvedValue([]);
    renderWorkspace();

    expect(await screen.findByText('Ainda sem conversas')).toBeInTheDocument();
    expect(screen.getByText('Seu espaço de conversas')).toBeInTheDocument();
    expect(serviceMock.loadLatestMessagesWithRevision).not.toHaveBeenCalled();
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

  it('oferece edição somente em mensagem própria ainda dentro da janela', async () => {
    const ownRecent = {
      ...message(71, 1, 'Minha mensagem'),
      created_at: new Date(Date.now() - 60_000).toISOString(),
    };
    const otherRecent = {
      ...message(72, 2, 'Mensagem recebida'),
      created_at: new Date(Date.now() - 60_000).toISOString(),
    };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [ownRecent, otherRecent], updates_revision: 0 });
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Minha mensagem');

    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 71' }));
    expect(screen.getByRole('menuitem', { name: 'Editar mensagem' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 72' }));
    expect(screen.queryByRole('menuitem', { name: 'Editar mensagem' })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Denunciar mensagem' })).toBeInTheDocument();
  });

  it('mantém exclusão disponível após 15 minutos e mostra só o placeholder em mensagens apagadas', async () => {
    const expired = {
      ...message(73, 1, 'Expirada'),
      created_at: new Date(Date.now() - 16 * 60_000).toISOString(),
    };
    const deleted = {
      ...message(74, 1, 'Esta mensagem foi excluída'),
      created_at: new Date(Date.now() - 60_000).toISOString(),
      edited_at: new Date(Date.now() - 30_000).toISOString(),
      is_deleted_for_everyone: true,
    };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [expired, deleted], updates_revision: 0 });
    renderWorkspace();
    await screen.findByText('Expirada');

    expect(screen.getByRole('button', { name: 'Opções da mensagem 73' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Opções da mensagem 74' })).not.toBeInTheDocument();
    expect(screen.getByText('Esta mensagem foi excluída')).toBeInTheDocument();
    expect(screen.queryByText('editada')).not.toBeInTheDocument();
    expect(screen.queryByText('Apagada para todos')).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 73' }));
    expect(screen.queryByRole('menuitem', { name: 'Editar mensagem' })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Excluir mensagem' })).toBeInTheDocument();
    expect(serviceMock.editMessage).not.toHaveBeenCalled();
  });

  it('abre e cancela a edição sem alterar a mensagem exibida', async () => {
    const own = { ...message(75, 1, 'Texto original'), created_at: new Date(Date.now() - 30_000).toISOString() };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [own], updates_revision: 0 });
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Texto original');
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 75' }));
    await user.click(screen.getByRole('menuitem', { name: 'Editar mensagem' }));

    expect(screen.getByRole('textbox', { name: 'Editar mensagem 75' })).toHaveValue('Texto original');
    await user.clear(screen.getByRole('textbox', { name: 'Editar mensagem 75' }));
    await user.type(screen.getByRole('textbox', { name: 'Editar mensagem 75' }), 'Rascunho alterado');
    await user.click(screen.getByRole('button', { name: 'Cancelar edição' }));

    expect(screen.getByText('Texto original')).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Editar mensagem 75' })).not.toBeInTheDocument();
    expect(serviceMock.editMessage).not.toHaveBeenCalled();
  });

  it('salva a edição e atualiza mensagem e revisão local', async () => {
    const own = { ...message(76, 1, 'Antes'), created_at: new Date(Date.now() - 30_000).toISOString() };
    const edited = { ...own, content: 'Depois', updated_at: new Date().toISOString(), edited_at: new Date().toISOString() };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [own], updates_revision: 0 });
    serviceMock.editMessage.mockResolvedValueOnce({ message: edited, message_state_revision: 6 });
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Antes');
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 76' }));
    await user.click(screen.getByRole('menuitem', { name: 'Editar mensagem' }));
    const editor = screen.getByRole('textbox', { name: 'Editar mensagem 76' });
    await user.clear(editor);
    await user.type(editor, 'Depois');
    await user.click(screen.getByRole('button', { name: 'Salvar edição' }));

    expect(await screen.findByText('Depois')).toBeInTheDocument();
    expect(screen.getByText('editada')).toBeInTheDocument();
    expect(screen.queryByText('Antes')).not.toBeInTheDocument();
    expect(serviceMock.editMessage).toHaveBeenCalledWith(10, 76, 'Depois');
    expect(screen.getByRole('status')).toHaveTextContent('Mensagem editada');
  });

  it('mostra erro de autorização ou prazo retornado pelo PATCH e mantém edição aberta', async () => {
    const own = { ...message(77, 1, 'Editar'), created_at: new Date(Date.now() - 30_000).toISOString() };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [own], updates_revision: 0 });
    serviceMock.editMessage.mockRejectedValueOnce(new ApiError('O prazo de 15 minutos expirou.', 409));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Editar');
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 77' }));
    await user.click(screen.getByRole('menuitem', { name: 'Editar mensagem' }));
    await user.click(screen.getByRole('button', { name: 'Salvar edição' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('O prazo de 15 minutos expirou.');
    expect(screen.getByRole('textbox', { name: 'Editar mensagem 77' })).toBeInTheDocument();
  });

  it('apresenta uma mensagem clara quando o PATCH falha por conexão', async () => {
    const own = { ...message(79, 1, 'Conexão'), created_at: new Date(Date.now() - 30_000).toISOString() };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [own], updates_revision: 0 });
    serviceMock.editMessage.mockRejectedValueOnce(
      new ApiError('Não foi possível conectar à API. Verifique sua conexão e tente novamente.'),
    );
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Conexão');
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 79' }));
    await user.click(screen.getByRole('menuitem', { name: 'Editar mensagem' }));
    await user.click(screen.getByRole('button', { name: 'Salvar edição' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Verifique sua conexão e tente novamente.');
  });

  it('oferece exclusão somente na mensagem própria, sem limite de idade', async () => {
    const ownOld = {
      ...message(80, 1, 'Minha mensagem antiga'),
      created_at: new Date(Date.now() - 90 * 24 * 60 * 60_000).toISOString(),
    };
    const other = message(81, 2, 'Mensagem de outra pessoa');
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [ownOld, other], updates_revision: 0 });
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Minha mensagem antiga');

    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 80' }));
    expect(screen.getByRole('menuitem', { name: 'Excluir mensagem' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Editar mensagem' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 81' }));
    expect(screen.queryByRole('menuitem', { name: 'Excluir mensagem' })).not.toBeInTheDocument();
  });

  it('confirma exclusão e permite cancelar sem chamar a API', async () => {
    const own = message(82, 1, 'Ainda visível');
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [own], updates_revision: 0 });
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Ainda visível');
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 82' }));
    await user.click(screen.getByRole('menuitem', { name: 'Excluir mensagem' }));

    const dialog = screen.getByRole('dialog', { name: 'Excluir mensagem para todos?' });
    expect(within(dialog).getByText(/Esta mensagem foi excluída/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Cancelar' }));
    expect(screen.getByText('Ainda visível')).toBeInTheDocument();
    expect(serviceMock.deleteMessage).not.toHaveBeenCalled();
  });

  it('aplica a resposta do DELETE imediatamente e remove edição e exclusão', async () => {
    const own = message(83, 1, 'Conteúdo confidencial original');
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [own], updates_revision: 2 });
    serviceMock.deleteMessage.mockResolvedValueOnce({
      message: { ...own, content: 'Esta mensagem foi excluída', is_deleted_for_everyone: true },
      message_state_revision: 3,
    });
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Conteúdo confidencial original');
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 83' }));
    await user.click(screen.getByRole('menuitem', { name: 'Excluir mensagem' }));
    await user.click(screen.getByRole('button', { name: 'Excluir para todos' }));

    expect(await screen.findByText('Esta mensagem foi excluída')).toBeInTheDocument();
    expect(screen.queryByText('Conteúdo confidencial original')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Opções da mensagem 83' })).not.toBeInTheDocument();
    expect(serviceMock.deleteMessage).toHaveBeenCalledWith(10, 83);
    expect(screen.getByRole('status')).toHaveTextContent('Mensagem excluída para todos');
  });

  it('mostra erros de autorização ou conexão na confirmação de exclusão', async () => {
    const own = message(84, 1, 'Ainda preservada');
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [own], updates_revision: 0 });
    serviceMock.deleteMessage.mockRejectedValueOnce(new ApiError('Somente o autor pode excluir esta mensagem.', 403));
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Ainda preservada');
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 84' }));
    await user.click(screen.getByRole('menuitem', { name: 'Excluir mensagem' }));
    await user.click(screen.getByRole('button', { name: 'Excluir para todos' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Somente o autor pode excluir esta mensagem.');
    expect(screen.getByText('Ainda preservada')).toBeInTheDocument();
  });

  it('sincroniza exclusão por polling e ignora versão anterior que tentaria restaurar o conteúdo', async () => {
    vi.useFakeTimers();
    const original = message(85, 2, 'Texto anterior secreto');
    const deleted = { ...original, content: 'Esta mensagem foi excluída', is_deleted_for_everyone: true };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [original], updates_revision: 0 });
    serviceMock.listMessageUpdates
      .mockResolvedValueOnce({
        items: [{ event_revision: 1, message_state_revision: 2, event_type: 'DELETED', message: deleted }],
        updates_revision: 1,
        next_cursor: 1,
        has_more: false,
      })
      .mockResolvedValueOnce({
        items: [{ event_revision: 2, message_state_revision: 1, event_type: 'UPDATED', message: original }],
        updates_revision: 2,
        next_cursor: 2,
        has_more: false,
      });
    renderWorkspace();

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByText('Esta mensagem foi excluída')).toBeInTheDocument();
    expect(screen.queryByText('Texto anterior secreto')).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

    expect(screen.getByText('Esta mensagem foi excluída')).toBeInTheDocument();
    expect(screen.queryByText('Texto anterior secreto')).not.toBeInTheDocument();
  });

  it('mantém a revisão retornada pelo PATCH diante de um evento de polling mais antigo', async () => {
    vi.useFakeTimers();
    const own = { ...message(78, 1, 'Versão inicial'), created_at: new Date(Date.now() - 30_000).toISOString() };
    const saved = { ...own, content: 'Versão do PATCH', edited_at: new Date().toISOString() };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [own], updates_revision: 0 });
    serviceMock.editMessage.mockResolvedValueOnce({ message: saved, message_state_revision: 5 });
    serviceMock.listMessageUpdates.mockResolvedValueOnce({
      items: [{
        event_revision: 7,
        message_state_revision: 4,
        event_type: 'UPDATED',
        message: { ...own, content: 'Representação antiga do polling' },
      }],
      updates_revision: 7,
      next_cursor: 7,
      has_more: false,
    });
    renderWorkspace();

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    fireEvent.click(screen.getByRole('button', { name: 'Opções da mensagem 78' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Editar mensagem' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Editar mensagem 78' }), {
      target: { value: 'Versão do PATCH' },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Salvar edição' }));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText('Versão do PATCH')).toBeInTheDocument();

    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(serviceMock.listMessageUpdates).toHaveBeenCalledWith(10, 0, 50, expect.any(AbortSignal));
    expect(screen.getByText('Versão do PATCH')).toBeInTheDocument();
    expect(screen.queryByText('Representação antiga do polling')).not.toBeInTheDocument();
  });

  it('solicita mensagens anteriores pelo cursor composto e preserva a ordem', async () => {
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({
      items: Array.from({ length: 50 }, (_, index) => message(index + 51)),
      updates_revision: 7,
    });
    serviceMock.listMessages.mockResolvedValueOnce([message(1)]);
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Mensagem 51');
    await user.click(screen.getByRole('button', { name: 'Carregar mais mensagens' }));

    expect(await screen.findByText('Mensagem 1')).toBeInTheDocument();
    expect(serviceMock.listMessages).toHaveBeenCalledWith(10, 50, undefined, {
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
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [message(9)], updates_revision: 0 });
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
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [{
      ...message(19, 2, 'Esta mensagem foi excluída'),
      is_deleted_for_everyone: true,
    }], updates_revision: 0 });
    const user = userEvent.setup();
    renderWorkspace();

    expect(await screen.findByText('Esta mensagem foi excluída')).toBeInTheDocument();
    expect(screen.queryByText('Apagada para todos')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Opções da mensagem 19' }));
    expect(screen.queryByRole('menuitem', { name: 'Editar mensagem' })).not.toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: 'Excluir mensagem' })).not.toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Denunciar mensagem' })).toBeInTheDocument();
    await user.click(screen.getByRole('menuitem', { name: 'Denunciar mensagem' }));
    expect(screen.getByRole('dialog', { name: 'Denunciar mensagem' })).toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: 'Motivo' }), 'Conteúdo apagado que requer análise');
    await user.click(screen.getByRole('button', { name: 'Enviar denúncia' }));

    await waitFor(() => expect(serviceMock.reportMessage).toHaveBeenCalledWith(19, 'Conteúdo apagado que requer análise'));
  });

  it('mostra erro de acesso retornado ao tentar ler mensagens', async () => {
    serviceMock.loadLatestMessagesWithRevision.mockRejectedValue(new ApiError('Você não participa desta conversa.', 403));
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
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [message(1)], updates_revision: 4 });
    serviceMock.listMessages.mockResolvedValueOnce([message(2)]);
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

  it('aplica atualização de uma mensagem antiga pelo ID sem criar duplicata', async () => {
    vi.useFakeTimers();
    const original = message(1, 2, 'Texto antigo');
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [original], updates_revision: 4 });
    serviceMock.listMessageUpdates.mockResolvedValueOnce({
      items: [{
        event_revision: 5,
        message_state_revision: 5,
        event_type: 'UPDATED',
        message: {
          ...original,
          content: 'Texto atualizado',
          updated_at: '2026-11-16T11:00:00Z',
          edited_at: '2026-11-16T11:00:00Z',
        },
      }],
      updates_revision: 5,
      next_cursor: 5,
      has_more: false,
    });
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

    expect(screen.getByText('Texto atualizado')).toBeInTheDocument();
    expect(screen.getByText('editada')).toBeInTheDocument();
    expect(screen.queryByText('Texto antigo')).not.toBeInTheDocument();
    expect(screen.getAllByText('Texto atualizado')).toHaveLength(1);
  });

  it('drena páginas com next_cursor e ignora versões antigas da mesma mensagem', async () => {
    vi.useFakeTimers();
    const original = message(1, 2, 'Versão inicial');
    const current = { ...original, content: 'Versão mais recente' };
    const stale = { ...original, content: 'Versão atrasada' };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [original], updates_revision: 0 });
    serviceMock.listMessageUpdates
      .mockResolvedValueOnce({
        items: [{ event_revision: 1, message_state_revision: 3, event_type: 'UPDATED', message: current }],
        updates_revision: 3,
        next_cursor: 1,
        has_more: true,
      })
      .mockResolvedValueOnce({
        items: [
          { event_revision: 2, message_state_revision: 3, event_type: 'UPDATED', message: current },
          { event_revision: 3, message_state_revision: 2, event_type: 'UPDATED', message: stale },
        ],
        updates_revision: 3,
        next_cursor: 3,
        has_more: false,
      });
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

    expect(serviceMock.listMessageUpdates).toHaveBeenNthCalledWith(1, 10, 0, 50, expect.any(AbortSignal));
    expect(serviceMock.listMessageUpdates).toHaveBeenNthCalledWith(2, 10, 1, 50, expect.any(AbortSignal));
    expect(screen.getByText('Versão mais recente')).toBeInTheDocument();
    expect(screen.queryByText('Versão atrasada')).not.toBeInTheDocument();
    expect(screen.getAllByText('Versão mais recente')).toHaveLength(1);
  });

  it('mantém o cursor confirmado após falha temporária e recupera na tentativa seguinte', async () => {
    vi.useFakeTimers();
    const original = message(1, 2, 'Antes');
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [original], updates_revision: 6 });
    serviceMock.listMessageUpdates
      .mockRejectedValueOnce(new Error('rede indisponível'))
      .mockResolvedValueOnce({
        items: [{
          event_revision: 7,
          message_state_revision: 7,
          event_type: 'UPDATED',
          message: { ...original, content: 'Depois' },
        }],
        updates_revision: 7,
        next_cursor: 7,
        has_more: false,
      });
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByText(/Atualização automática pausada temporariamente/)).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });

    expect(serviceMock.listMessageUpdates).toHaveBeenNthCalledWith(1, 10, 6, 50, expect.any(AbortSignal));
    expect(serviceMock.listMessageUpdates).toHaveBeenNthCalledWith(2, 10, 6, 50, expect.any(AbortSignal));
    expect(screen.getByText('Depois')).toBeInTheDocument();
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
    await waitFor(() => expect(serviceMock.loadLatestMessagesWithRevision).toHaveBeenCalledWith(
      20, 50, expect.any(AbortSignal),
    ));
  });

  it('não sobrescreve seleção manual após atualizar a lista de conversas', async () => {
    serviceMock.listConversations.mockResolvedValue([
      conversation,
      { ...conversation, id: 20, user_b_id: 3 },
    ]);
    serviceMock.loadLatestMessagesWithRevision.mockImplementation(async (conversationId: number) =>
      conversationId === 10
        ? { items: [message(1)], updates_revision: 0 }
        : { items: [message(20, 3, 'Mensagem de B', 20)], updates_revision: 0 },
    );
    serviceMock.sendMessage.mockImplementationOnce(async (_id: number, content: string) => message(21, 1, content, 20));
    const user = userEvent.setup();
    renderWorkspace(10);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Abrir conversa com Usuário #2' }))
      .toHaveAttribute('aria-current', 'page'));

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
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [message(1)], updates_revision: 0 });
    serviceMock.listMessages.mockResolvedValueOnce([message(2, 2, 'Recebida antes'), ownReply]);
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

  it('resposta atrasada do envio não substitui estado de evento mais recente', async () => {
    vi.useFakeTimers();
    const sent = message(2, 1, 'Conteúdo no envio');
    const updated = { ...sent, content: 'Estado mais recente' };
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [message(1)], updates_revision: 0 });
    let resolveSend!: (value: ReturnType<typeof message>) => void;
    serviceMock.sendMessage.mockImplementationOnce(() => new Promise((resolve) => { resolveSend = resolve; }));
    serviceMock.listMessages.mockResolvedValueOnce([sent]);
    serviceMock.listMessageUpdates.mockResolvedValueOnce({
      items: [{ event_revision: 1, message_state_revision: 1, event_type: 'UPDATED', message: updated }],
      updates_revision: 1,
      next_cursor: 1,
      has_more: false,
    });
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    fireEvent.change(screen.getByRole('textbox', { name: 'Mensagem' }), { target: { value: 'Conteúdo no envio' } });
    fireEvent.click(screen.getByRole('button', { name: 'Enviar mensagem' }));
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByText('Estado mais recente')).toBeInTheDocument();

    await act(async () => { resolveSend(sent); await Promise.resolve(); });
    expect(screen.getByText('Estado mais recente')).toBeInTheDocument();
    expect(screen.queryByText('Conteúdo no envio')).not.toBeInTheDocument();
  });

  it('não inicia uma segunda consulta enquanto o polling atual ainda está pendente', async () => {
    vi.useFakeTimers();
    let resolvePoll!: (value: ReturnType<typeof message>[]) => void;
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [message(1)], updates_revision: 0 });
    serviceMock.listMessages
      .mockImplementationOnce(() => new Promise((resolve) => { resolvePoll = resolve; }))
      .mockResolvedValueOnce([]);
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(1);

    await act(async () => { resolvePoll([message(2)]); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(2);
  });

  it('não inicia outra rodada enquanto uma página de eventos está pendente', async () => {
    vi.useFakeTimers();
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [message(1)], updates_revision: 2 });
    let resolveEvents!: (value: { items: []; updates_revision: number; next_cursor: number; has_more: false }) => void;
    serviceMock.listMessageUpdates.mockImplementationOnce(() => new Promise((resolve) => { resolveEvents = resolve; }));
    renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(serviceMock.listMessageUpdates).toHaveBeenCalledTimes(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(serviceMock.listMessageUpdates).toHaveBeenCalledTimes(1);
    resolveEvents({ items: [], updates_revision: 2, next_cursor: 2, has_more: false });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(serviceMock.listMessageUpdates).toHaveBeenCalledTimes(2);
  });

  it('ignora uma resposta de polling atrasada após selecionar outra conversa', async () => {
    vi.useFakeTimers();
    let resolveOldPoll!: (value: ReturnType<typeof message>[]) => void;
    serviceMock.listConversations.mockResolvedValue([
      conversation,
      { ...conversation, id: 20, user_b_id: 3 },
    ]);
    serviceMock.loadLatestMessagesWithRevision.mockImplementation(async (conversationId: number) => {
      if (conversationId === 20) return { items: [message(20, 3, 'Mensagem da B', 20)], updates_revision: 0 };
      return { items: [message(1, 2, 'Mensagem inicial de A')], updates_revision: 0 };
    });
    serviceMock.listMessages.mockImplementation((conversationId: number) => {
      if (conversationId === 20) return Promise.resolve([]);
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

  it('ignora eventos atrasados depois de trocar de conversa', async () => {
    vi.useFakeTimers();
    let resolveOldEvents!: (value: {
      items: Array<{ event_revision: number; message_state_revision: number; event_type: 'UPDATED'; message: ReturnType<typeof message> }>;
      updates_revision: number; next_cursor: number; has_more: boolean;
    }) => void;
    serviceMock.listConversations.mockResolvedValue([
      conversation,
      { ...conversation, id: 20, user_b_id: 3 },
    ]);
    serviceMock.loadLatestMessagesWithRevision.mockImplementation(async (id: number) => ({
      items: [message(id, 2, id === 10 ? 'Mensagem A' : 'Mensagem B', id)],
      updates_revision: 0,
    }));
    serviceMock.listMessageUpdates.mockImplementation((id: number) => {
      if (id === 10) return new Promise((resolve) => { resolveOldEvents = resolve; });
      return Promise.resolve({ items: [], updates_revision: 0, next_cursor: 0, has_more: false });
    });
    const view = renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(resolveOldEvents).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: 'Abrir conversa com Usuário #3' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => {
      resolveOldEvents({
        items: [{
          event_revision: 1,
          message_state_revision: 1,
          event_type: 'UPDATED',
          message: message(10, 2, 'Evento atrasado de A', 10),
        }],
        updates_revision: 1,
        next_cursor: 1,
        has_more: false,
      });
      await Promise.resolve();
    });

    expect(screen.getByText('Mensagem B')).toBeInTheDocument();
    expect(screen.queryByText('Evento atrasado de A')).not.toBeInTheDocument();
    view.unmount();
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
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [message(1)], updates_revision: 0 });
    serviceMock.listMessages
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
    serviceMock.loadLatestMessagesWithRevision.mockResolvedValueOnce({ items: [message(1)], updates_revision: 0 });
    serviceMock.listMessages.mockRejectedValueOnce(new ApiError('Acesso negado', 403));
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
    const eventCallsBeforeUnmount = serviceMock.listMessageUpdates.mock.calls.length;
    view.unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(callsBeforeUnmount);
    expect(serviceMock.listMessageUpdates).toHaveBeenCalledTimes(eventCallsBeforeUnmount);
  });

  it('encerra o polling quando a sessão autenticada termina', async () => {
    vi.useFakeTimers();
    serviceMock.listMessages.mockResolvedValue([message(1)]);
    const view = renderWorkspace();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const callsBeforeLogout = serviceMock.listMessages.mock.calls.length;
    const eventCallsBeforeLogout = serviceMock.listMessageUpdates.mock.calls.length;
    authMock.mockReturnValue({ user: null });
    view.rerender(
      <MemoryRouter>
        <ConversationWorkspace createDialogOpen={false} onCreateDialogOpenChange={vi.fn()} />
      </MemoryRouter>,
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(serviceMock.listMessages).toHaveBeenCalledTimes(callsBeforeLogout);
    expect(serviceMock.listMessageUpdates).toHaveBeenCalledTimes(eventCallsBeforeLogout);
  });
});
