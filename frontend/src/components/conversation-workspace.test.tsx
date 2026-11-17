/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
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

function message(id: number, senderId = 2, content = `Mensagem ${id}`) {
  return {
    id,
    conversation_id: 10,
    sender_id: senderId,
    content,
    created_at: `2026-11-16T10:${String(id % 60).padStart(2, '0')}:00Z`,
    updated_at: `2026-11-16T10:${String(id % 60).padStart(2, '0')}:00Z`,
    edited_at: null,
    is_deleted_for_everyone: false,
  };
}

function renderWorkspace() {
  return render(
    <MemoryRouter>
      <ConversationWorkspace createDialogOpen={false} onCreateDialogOpenChange={vi.fn()} />
    </MemoryRouter>,
  );
}

describe('fluxos do painel de conversas', () => {
  afterEach(() => cleanup());

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
    await waitFor(() => expect(serviceMock.listMessages).toHaveBeenCalledWith(10, 50, 0));
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

  it('solicita a próxima página usando o offset da API e preserva a ordem', async () => {
    serviceMock.listMessages
      .mockResolvedValueOnce(Array.from({ length: 50 }, (_, index) => message(index + 1)))
      .mockResolvedValueOnce([message(51)]);
    const user = userEvent.setup();
    renderWorkspace();
    await screen.findByText('Mensagem 1');
    await user.click(screen.getByRole('button', { name: 'Carregar mais mensagens' }));

    expect(await screen.findByText('Mensagem 51')).toBeInTheDocument();
    expect(serviceMock.listMessages).toHaveBeenNthCalledWith(2, 10, 50, 50);
    const contents = screen.getAllByText(/^Mensagem \d+$/);
    expect(contents[0]).toHaveTextContent('Mensagem 1');
    expect(contents.at(-1)).toHaveTextContent('Mensagem 51');
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
});
