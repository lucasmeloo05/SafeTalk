/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

const { socialMock, conversationMock } = vi.hoisted(() => ({
  socialMock: {
    acceptFriendRequest: vi.fn(),
    cancelFriendRequest: vi.fn(),
    getPrivacySettings: vi.fn(),
    listSocial: vi.fn(),
    rejectFriendRequest: vi.fn(),
    removeFriend: vi.fn(),
    searchUsers: vi.fn(),
    sendFriendRequest: vi.fn(),
    updatePrivacySettings: vi.fn(),
  },
  conversationMock: { createDirectConversation: vi.fn() },
}));

vi.mock('@/components/dashboard-layout', () => ({
  DashboardLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock('@/services/social-api', () => ({ ...socialMock, SOCIAL_PAGE_SIZE: 20 }));
vi.mock('@/services/conversation-api', () => conversationMock);

import { api } from '@/lib/api';
import { SocialPage } from '@/pages/social';

const privacy = { allow_messages_from_strangers: false, allow_friend_requests: true };
const friend = { friendship_id: 1, user_id: 10, username: 'friend_one', created_at: '2026-11-01T10:00:00Z' };
const listPage = { items: [friend], total: 1, limit: 20, offset: 0 };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

function renderPage() {
  return render(<MemoryRouter><SocialPage /></MemoryRouter>);
}

describe('página social', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  it('confirma bloqueio, remove a relação e permite desbloquear na lista privada', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    const put = vi.spyOn(api, 'put').mockResolvedValue({});
    const del = vi.spyOn(api, 'delete').mockResolvedValue({});
    vi.spyOn(api, 'get').mockResolvedValueOnce({ data: [{ id: friend.user_id, username: friend.username }] })
      .mockResolvedValueOnce({ data: [] });
    renderPage();
    const block = await screen.findByRole('button', { name: 'Bloquear' });
    await user.click(block);
    expect(confirm).toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
    socialMock.listSocial.mockResolvedValue({ ...listPage, items: [], total: 0 });
    await user.click(block);
    expect(put).toHaveBeenCalledWith('/social/blocks/10');
    await waitFor(() => expect(screen.queryByText(friend.username)).not.toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Privacidade' }));
    expect(await screen.findByText(friend.username)).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Desbloquear' }));
    expect(del).toHaveBeenCalledWith('/social/blocks/10');
    expect(await screen.findByText('Nenhum usuário bloqueado.')).toBeVisible();
  });

  it('mantém as ações da relação se o bloqueio falhar', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.spyOn(api, 'put').mockRejectedValue(new Error());
    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: 'Bloquear' }));
    expect(await screen.findByRole('alert')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Conversar' })).toBeEnabled();
  });

  beforeEach(() => {
    vi.resetAllMocks();
    socialMock.listSocial.mockResolvedValue(listPage);
    socialMock.getPrivacySettings.mockResolvedValue(privacy);
    socialMock.searchUsers.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    socialMock.acceptFriendRequest.mockResolvedValue({ ...friend, user_id: 15, friendship_id: 42, status: 'ACCEPTED', responded_at: '2026-11-18T10:00:00Z' });
  });

  it('envia limite e offset ao paginar resultados de busca', async () => {
    const user = userEvent.setup();
    socialMock.searchUsers.mockResolvedValue({
      items: [{ id: 11, username: 'person_a', relationship_status: 'NONE', friendship_id: null }],
      total: 21, limit: 20, offset: 0,
    });
    renderPage();
    const input = screen.getByPlaceholderText('Buscar por username');
    await user.type(input, 'person');
    await user.click(screen.getByRole('button', { name: /Buscar/ }));
    await screen.findByText('person_a');
    expect(socialMock.searchUsers).toHaveBeenCalledWith('person', 20, 0);

    socialMock.searchUsers.mockResolvedValueOnce({
      items: [{ id: 12, username: 'person_b', relationship_status: 'NONE', friendship_id: null }],
      total: 21, limit: 20, offset: 20,
    });
    await user.click(screen.getByRole('button', { name: 'Próxima página resultados da busca' }));
    expect(await screen.findByText('person_b')).toBeInTheDocument();
    expect(socialMock.searchUsers).toHaveBeenLastCalledWith('person', 20, 20);
  });

  it('descarta resposta obsoleta após o texto ser alterado ou limpo', async () => {
    const user = userEvent.setup();
    const oldResponse = deferred<{ items: { id: number; username: string; relationship_status: 'NONE'; friendship_id: null }[]; total: number; limit: number; offset: number }>();
    socialMock.searchUsers.mockReturnValueOnce(oldResponse.promise).mockResolvedValueOnce({
      items: [{ id: 13, username: 'beta_person', relationship_status: 'NONE', friendship_id: null }],
      total: 1, limit: 20, offset: 0,
    });
    renderPage();
    const input = screen.getByPlaceholderText('Buscar por username');
    await user.type(input, 'alpha');
    await user.click(screen.getByRole('button', { name: /Buscar/ }));
    await user.clear(input);
    await user.type(input, 'beta');
    oldResponse.resolve({
      items: [{ id: 14, username: 'alpha_person', relationship_status: 'NONE', friendship_id: null }],
      total: 1, limit: 20, offset: 0,
    });
    await waitFor(() => expect(screen.queryByText('alpha_person')).not.toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Buscar/ }));
    expect(await screen.findByText('beta_person')).toBeInTheDocument();
    expect(screen.queryByText('alpha_person')).not.toBeInTheDocument();
  });

  it('atualiza a relação após aceitar solicitação nos resultados', async () => {
    const user = userEvent.setup();
    socialMock.searchUsers.mockResolvedValue({
      items: [{ id: 15, username: 'request_sender', relationship_status: 'REQUEST_RECEIVED', friendship_id: 42 }],
      total: 1, limit: 20, offset: 0,
    });
    renderPage();
    const input = screen.getByPlaceholderText('Buscar por username');
    await user.type(input, 'request');
    await user.click(screen.getByRole('button', { name: /Buscar/ }));
    await screen.findByText('request_sender');
    await user.click(screen.getByRole('button', { name: 'Aceitar' }));
    const searchResults = screen.getByRole('region', { name: 'Resultados da busca' });
    expect(await within(searchResults).findByRole('button', { name: 'Conversar' })).toBeInTheDocument();
    expect(within(searchResults).queryByRole('button', { name: 'Aceitar' })).not.toBeInTheDocument();
    expect(socialMock.acceptFriendRequest).toHaveBeenCalledWith(42);
  });

  it.each([
    ['Recebidos', 'Aceitar', 'ACCEPTED', 'Conversar'],
    ['Enviados', 'Cancelar', 'CANCELLED', 'Adicionar'],
    ['Amigos', 'Remover friend_one dos amigos', 'REMOVED', 'Adicionar'],
  ])('sincroniza a busca com a aba %s', async (tab, button, status, expected) => {
    const user = userEvent.setup();
    const previous = status === 'ACCEPTED' ? 'REQUEST_RECEIVED' : status === 'CANCELLED' ? 'REQUEST_SENT' : 'FRIENDS';
    socialMock.searchUsers.mockResolvedValue({ items: [{ id: friend.user_id, username: friend.username,
      friendship_id: friend.friendship_id, relationship_status: previous }], total: 1, limit: 20, offset: 0 });
    const action = status === 'ACCEPTED' ? socialMock.acceptFriendRequest : status === 'REMOVED' ? socialMock.removeFriend : socialMock.cancelFriendRequest;
    action.mockResolvedValue({ ...friend, status });
    renderPage();
    await user.type(screen.getByPlaceholderText('Buscar por username'), 'friend');
    await user.click(screen.getByRole('button', { name: 'Buscar' }));
    const results = await screen.findByRole('region', { name: 'Resultados da busca' });
    await user.click(screen.getByRole('button', { name: new RegExp(tab) }));
    const buttons = screen.getAllByRole('button', { name: button });
    await user.click(buttons.find(element => !results.contains(element))!);
    expect(await within(results).findByRole('button', { name: expected })).toBeInTheDocument();
    expect(socialMock.searchUsers).toHaveBeenCalledTimes(1);
  });

  it('permite voltar quando a última página deixou de ter resultados', async () => {
    const user = userEvent.setup();
    const first = { items: [{ id: 19, username: 'ana_teste', relationship_status: 'NONE', friendship_id: null }], total: 21 };
    socialMock.searchUsers.mockResolvedValueOnce(first).mockResolvedValueOnce({ items: [], total: 20 }).mockResolvedValueOnce(first);
    renderPage();
    await user.type(screen.getByPlaceholderText('Buscar por username'), 'ana');
    await user.click(screen.getByRole('button', { name: 'Buscar' }));
    await user.click(await screen.findByRole('button', { name: 'Próxima página resultados da busca' }));
    expect(await screen.findByText('Não há resultados nesta página.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Página anterior resultados da busca' }));
    expect(await screen.findByText('ana_teste')).toBeInTheDocument();
  });

  it('pagina listas de relações sem solicitar todos os registros', async () => {
    const user = userEvent.setup();
    socialMock.listSocial.mockImplementation((path: string, limit: number, offset: number) => Promise.resolve({
      items: [{ ...friend, username: offset === 0 ? `${path}_first` : `${path}_next` }],
      total: 21, limit, offset,
    }));
    renderPage();
    expect(await screen.findByText('friends_first')).toBeInTheDocument();
    expect(socialMock.listSocial).toHaveBeenCalledWith('friends', 20, 0);
    await user.click(screen.getByRole('button', { name: 'Próxima página lista de amigos' }));
    expect(await screen.findByText('friends_next')).toBeInTheDocument();
    expect(socialMock.listSocial).toHaveBeenCalledWith('friends', 20, 20);
    expect(socialMock.listSocial).toHaveBeenCalledTimes(4);
    expect(socialMock.getPrivacySettings).toHaveBeenCalledTimes(1);
  });
});
