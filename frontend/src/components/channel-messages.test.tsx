/** @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerChannels } from './channel-messages';
import { channelApi, type ChannelHistory } from '@/services/channel-api';
import { ApiError } from '@/lib/api';

vi.mock('@/services/channel-api', () => ({ channelApi: {
  list: vi.fn(), history: vi.fn(), updates: vi.fn(), send: vi.fn(), edit: vi.fn(),
  remove: vi.fn(), report: vi.fn(), policy: vi.fn(),
} }));
const api = vi.mocked(channelApi);
const channel = { id: 3, server_id: 1, name: 'geral', is_read_only: false, is_private: false, channel_type: 'TEXT' as const };
const message = { id: 7, conversation_id: 2, sender_id: 9, content: 'Olá', edited_at: null,
  is_deleted_for_everyone: false, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
const history: ChannelHistory = { items: [message], has_more: false, updates_revision: 2, can_publish: true };
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
async function open() {
  const view = render(<ServerChannels serverId={1} userId={9} owner={false} />);
  click('Abrir canais');
  await screen.findByRole('option', { name: 'geral' });
  fireEvent.change(screen.getByLabelText('Selecionar canal'), { target: { value: '3' } });
  return view;
}
beforeEach(() => {
  vi.resetAllMocks();
  api.list.mockResolvedValue([channel, { ...channel, id: 4, name: 'avisos' }]);
  api.history.mockResolvedValue(history);
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('carrega histórico anterior e confirma edição, exclusão e envio somente após a resposta', async () => {
  api.history.mockResolvedValueOnce({ ...history, has_more: true })
    .mockResolvedValueOnce({ ...history, items: [{ ...message, id: 5, sender_id: 8, content: 'Antiga' }] });
  await open();
  await screen.findByText('Olá');
  click('Mensagens anteriores');
  await screen.findByText('Antiga');
  expect(api.history.mock.lastCall?.[3]).toBe(7);
  const own = screen.getByText('Olá').closest('article')!;
  expect(within(own).queryByText('Denunciar mensagem')).toBeNull();
  click('Editar mensagem');
  fireEvent.change(screen.getByLabelText('Editar conteúdo'), { target: { value: 'Revisada' } });
  api.edit.mockResolvedValue({ message: { ...message, content: 'Revisada' }, message_state_revision: 3 });
  click('Confirmar');
  await screen.findByText('Revisada');
  click('Excluir mensagem');
  api.remove.mockResolvedValue({ message: { ...message, content: 'Esta mensagem foi excluída', is_deleted_for_everyone: true }, message_state_revision: 4 });
  click('Confirmar');
  await screen.findByText('Esta mensagem foi excluída');
  expect(screen.queryByText('Editar mensagem')).toBeNull();
  api.send.mockRejectedValueOnce(new Error('Sem conexão')).mockResolvedValueOnce({
    message: { ...message, id: 8, content: 'Nova' }, message_state_revision: 5,
  });
  fireEvent.change(screen.getByLabelText('Mensagem no canal'), { target: { value: 'Nova' } });
  click('Enviar mensagem');
  await screen.findByText('Sem conexão');
  expect(screen.getByLabelText('Mensagem no canal')).toHaveValue('Nova');
  click('Enviar mensagem');
  await screen.findByText('Mensagem enviada.');
  expect(api.send).toHaveBeenCalledTimes(2);
  click('Denunciar mensagem');
  fireEvent.change(screen.getByLabelText('Motivo da denúncia'), { target: { value: 'Revisar' } });
  click('Confirmar');
  await screen.findByText('Denúncia registrada para triagem.');
  expect(api.report).toHaveBeenCalledWith(1, 3, 5, 'Revisar');
});

it.each(['canal', 'servidor'])('descarta a resposta antiga ao trocar de %s', async target => {
  let resolve!: (value: ChannelHistory) => void;
  api.history.mockReturnValueOnce(new Promise(ok => { resolve = ok; }))
    .mockResolvedValueOnce({ ...history, can_publish: false, items: [] });
  const view = await open();
  if (target === 'servidor') {
    api.list.mockResolvedValue([{ ...channel, server_id: 2, id: 4, name: 'destino' }]);
    view.rerender(<ServerChannels serverId={2} userId={9} owner={false} />);
    await screen.findByRole('option', { name: 'destino' });
  }
  fireEvent.change(screen.getByLabelText('Selecionar canal'), { target: { value: '4' } });
  await screen.findByText('Nenhuma mensagem neste canal.');
  await act(async () => resolve(history));
  expect(screen.queryByText('Olá')).toBeNull();
  expect(screen.queryByText('Enviar mensagem')).toBeNull();
  expect(screen.queryByText('Tornar somente leitura')).toBeNull();
});

it('aplica eventos paginados, atualiza autorização e oculta o histórico após perda de acesso', async () => {
  api.updates.mockResolvedValueOnce({ items: [{ event_revision: 3, event_type: 'UPDATED',
    message_state_revision: 3, message: { ...message, content: 'Atualizada' } }], has_more: true, next_cursor: 3, can_publish: false })
    .mockResolvedValueOnce({ items: [], next_cursor: 3, has_more: false, can_publish: false })
    .mockRejectedValueOnce(new ApiError('Canal não encontrado.', 404));
  await open();
  await screen.findByText('Olá');
  await act(async () => window.dispatchEvent(new Event('online')));
  expect(screen.getByText('Atualizada')).toBeVisible();
  expect(screen.queryByText('Editar mensagem')).toBeNull();
  expect(screen.queryByText('Enviar mensagem')).toBeNull();
  expect(api.updates.mock.calls.map(call => call[2])).toEqual([2, 3]);
  await act(async () => window.dispatchEvent(new Event('online')));
  expect(screen.queryByText('Atualizada')).toBeNull();
  expect(screen.getByText('Canal não encontrado.')).toBeVisible();
});

it('permite ao proprietário configurar somente leitura e publicar uma mensagem', async () => {
  api.policy.mockResolvedValue({ ...channel, is_read_only: true });
  render(<ServerChannels serverId={1} userId={9} owner />);
  click('Abrir canais');
  await screen.findByRole('option', { name: 'geral' });
  fireEvent.change(screen.getByLabelText('Selecionar canal'), { target: { value: '3' } });
  await screen.findByText('Tornar somente leitura');
  click('Tornar somente leitura');
  await screen.findByText('Configuração do canal salva.');
  expect(api.policy).toHaveBeenCalledWith(1, 3, true);
  expect(screen.getByText('Liberar publicação')).toBeEnabled();
  expect(screen.getByLabelText('Mensagem no canal')).toBeEnabled();
});
