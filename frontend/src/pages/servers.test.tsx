/** @vitest-environment jsdom */
import { act, cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

const { serverApi } = vi.hoisted(() => ({
  serverApi: {
    acceptServerInvite: vi.fn(),
    createServer: vi.fn(),
    createServerInvite: vi.fn(),
    getServer: vi.fn(),
    getServerRole: vi.fn(),
    getServerMember: vi.fn(),
    getServerAuthorizationContext: vi.fn(),
    listServerInvites: vi.fn(),
    listServerMembers: vi.fn(),
    listServerRoles: vi.fn(),
    listServers: vi.fn(),
    assignServerRoleToMember: vi.fn(),
    createServerRole: vi.fn(),
    deleteServerRole: vi.fn(),
    removeServerRoleFromMember: vi.fn(),
    revokeServerInvite: vi.fn(),
    updateServerRole: vi.fn(),
    updateEveryonePermissions: vi.fn(),
  },
}));

vi.mock('@/services/server-api', () => ({
  ...serverApi,
  SERVER_INVITE_PAGE_SIZE: 20,
  SERVER_MEMBER_PAGE_SIZE: 20,
  SERVER_PERMISSION_KEYS: ['kick_members', 'ban_members', 'unban_members', 'manage_invites', 'manage_roles', 'mention_everyone'],
}));
vi.mock('@/context/auth-context', () => ({
  useAuth: () => ({
    user: { id: 7, username: 'owner', email: 'owner@example.test' },
    signOut: vi.fn(),
  }),
}));

import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { DashboardLayout } from '@/components/dashboard-layout';
import { AxiosError } from 'axios';
import { api, ApiError } from '@/lib/api';
import { ServerDetailsPage } from '@/pages/server-details';
import { ServersPage } from '@/pages/servers';

const server = {
  id: 12,
  owner_id: 7,
  name: 'Comunidade SafeTalk',
  description: 'Espaço de teste',
  created_at: '2026-11-01T10:00:00Z',
  updated_at: '2026-11-01T10:00:00Z',
  everyone_permissions: { manage_invites: true, kick_members: false },
};
const members = [
  { user_id: 7, username: 'owner', joined_at: '2026-11-01T10:00:00Z', roles: [] },
  { user_id: 9, username: 'member', joined_at: '2026-11-02T10:00:00Z', roles: [
    { id: 5, name: 'Membro', position: 1 },
    { id: 8, name: 'Moderador', position: 8 },
  ] },
];
const authorizationContext = {
  server_id: 12,
  user_id: 7,
  is_owner: true,
  highest_role_position: 0,
  effective_permissions: ['manage_invites' as const],
  has_manage_roles_permission: false,
};
const invite = {
  id: 31,
  server_id: 12,
  created_at: '2026-11-03T10:00:00Z',
  expires_at: '2026-12-01T10:00:00Z',
  max_uses: 5,
  uses_count: 1,
  revoked_at: null,
};
const roles = [
  { id: 5, server_id: 12, name: 'Membro', description: 'Cargo inicial', position: 1, permissions: { mention_everyone: false }, is_default: false, is_system_role: false, created_at: '2026-11-01T10:00:00Z' },
  { id: 8, server_id: 12, name: 'Moderador', description: null, position: 8, permissions: { kick_members: true, manage_roles: true }, is_default: false, is_system_role: false, created_at: '2026-11-02T10:00:00Z' },
];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function renderPages(initialEntry = '/servidores', allowSwitch = false) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      {allowSwitch && <Link to="/servidores/13">Abrir servidor B</Link>}
      <Routes>
        <Route path="/servidores" element={<ServersPage />} />
        <Route path="/servidores/:serverId" element={<ServerDetailsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('frontend de servidores — entrega 1', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    serverApi.listServers.mockResolvedValue([server]);
    serverApi.createServer.mockResolvedValue(server);
    serverApi.acceptServerInvite.mockResolvedValue({ server_id: 12, user_id: 8, status: 'ACTIVE', joined_at: '2026-11-20T10:00:00Z', left_at: null });
    serverApi.createServerInvite.mockResolvedValue({ ...invite, token: 'raw-invite-token' });
    serverApi.getServer.mockResolvedValue(server);
    serverApi.getServerAuthorizationContext.mockResolvedValue(authorizationContext);
    serverApi.listServerInvites.mockResolvedValue([]);
    serverApi.listServerMembers.mockResolvedValue(members);
    serverApi.listServerRoles.mockResolvedValue(roles);
    serverApi.revokeServerInvite.mockResolvedValue(undefined);
    serverApi.assignServerRoleToMember.mockResolvedValue(undefined);
    serverApi.createServerRole.mockResolvedValue(roles[0]);
    serverApi.deleteServerRole.mockResolvedValue(undefined);
    serverApi.removeServerRoleFromMember.mockResolvedValue(undefined);
    serverApi.updateServerRole.mockResolvedValue(roles[0]);
  });
  afterEach(() => { cleanup(); });

  it('envia a classificação +18 somente na criação e apresenta a decisão etária do backend', async () => {
    const user = userEvent.setup();
    serverApi.createServer.mockRejectedValueOnce(new ApiError('Servidores +18 exigem idade declarada de pelo menos 18 anos.', 403));
    renderPages();
    await screen.findByRole('heading', { name: 'Criar servidor' });
    await user.type(screen.getByLabelText('Nome do servidor'), 'Adultos');
    await user.click(screen.getByRole('checkbox', { name: /Servidor \+18/ }));
    await user.click(screen.getByRole('button', { name: 'Criar servidor' }));
    expect(serverApi.createServer).toHaveBeenCalledWith(expect.objectContaining({ is_adult: true }));
    expect(await screen.findByText('Servidores +18 exigem idade declarada de pelo menos 18 anos.')).toBeVisible();
    expect(screen.getByRole('checkbox', { name: /Servidor \+18/ })).toBeChecked();
  });


  it.each(['individual antiga', 'lista antiga', 'excluído', 'erro individual', 'erro da lista', 'outro servidor'])(
    'concilia a lista de cargos com a recuperação individual: %s', async scenario => {
      const user = userEvent.setup();
      const deletion = deferred<void>();
      const list = deferred<typeof roles>();
      const detail = deferred<typeof roles[number]>();
      serverApi.listServerMembers.mockResolvedValue([]);
      serverApi.deleteServerRole.mockReturnValueOnce(deletion.promise);
      serverApi.listServerRoles.mockResolvedValueOnce(roles).mockReturnValueOnce(list.promise)
        .mockResolvedValue([{ ...roles[0], name: 'Cargo B' }]);
      serverApi.getServerRole.mockReturnValueOnce(detail.promise);
      serverApi.getServer.mockImplementation(async id => ({ ...server, id }));
      serverApi.updateServerRole.mockRejectedValueOnce(new ApiError('Conflito', 409, { code: 'permissions_conflict' }));
      renderPages('/servidores/12', true);
      await user.click(await screen.findByRole('button', { name: scenario === 'excluído' ? 'Excluir Membro' : 'Excluir Moderador' }));
      await user.click(screen.getByRole('button', { name: 'Confirmar exclusão' }));
      await user.click(within(screen.getByRole('heading', { name: 'Membro' }).closest('article')!).getByText('Editar'));
      const editor = within(screen.getByText('Permissões deste cargo', { selector: 'legend' }).closest('form')!);
      await user.click(editor.getByLabelText('Banir membros'));
      await user.click(editor.getByText('Salvar alterações'));
      const recover = await screen.findByText('Carregar configuração atual');
      const listFirst = scenario === 'lista antiga' || scenario === 'erro da lista';
      if (listFirst) await act(async () => deletion.resolve());
      await user.click(recover);
      if (!listFirst) await act(async () => deletion.resolve());
      expect(serverApi.getServerRole).toHaveBeenCalledWith(12, 5);
      expect(serverApi.listServerRoles).toHaveBeenCalledTimes(2);
      const latest = { ...roles[0], name: 'Cargo vigente' };
      if (scenario === 'outro servidor') {
        await user.click(screen.getByText('Abrir servidor B'));
        await screen.findByRole('heading', { name: 'Cargo B' });
        await act(async () => { list.resolve(roles); detail.resolve(latest); });
        expect(screen.queryByText(latest.name)).toBeNull();
        expect(screen.getByRole('heading', { name: 'Cargo B' })).toBeVisible();
      } else if (listFirst) {
        await act(async () => detail.resolve(latest));
        const other = { ...roles[1], id: 42, name: 'Outro cargo válido' };
        if (scenario === 'lista antiga') {
          await act(async () => list.resolve([roles[0], other]));
          expect(screen.getByRole('heading', { name: other.name })).toBeVisible();
        } else await act(async () => list.reject(new Error('lista antiga')));
        expect(screen.getByRole('heading', { name: latest.name })).toBeVisible();
        expect(screen.queryByRole('alert')).toBeNull();
      } else {
        await act(async () => list.resolve(scenario === 'excluído' ? [] : [latest]));
        if (scenario === 'erro individual') await act(async () => detail.reject(new ApiError('Erro obsoleto', 422)));
        else await act(async () => detail.resolve(roles[0]));
        expect(screen.queryByText('Erro obsoleto')).toBeNull();
        expect(screen.queryByRole('heading', { name: 'Membro' })).toBeNull();
        if (scenario !== 'excluído') expect(screen.getByRole('heading', { name: latest.name })).toBeVisible();
      }
    });

  it.each([false, true])('concilia a página de membros com duas edições, troca de servidor=%s', async switchServer => {
    const user = userEvent.setup();
    const page = deferred<typeof members>();
    const first = Array.from({ length: 20 }, (_, i) => ({ ...members[0], user_id: 100 + i, username: 'usuário' + i }));
    serverApi.getServer.mockImplementation(async id => ({ ...server, id }));
    serverApi.listServerMembers.mockResolvedValueOnce(first).mockReturnValueOnce(page.promise).mockResolvedValue([]);
    let liveRoles = [...roles];
    serverApi.listServerRoles.mockImplementation(async () => liveRoles);
    serverApi.updateServerRole.mockImplementation(async (_server, id, changes) => {
      const updated = { ...liveRoles.find(role => role.id === id)!, ...changes };
      liveRoles = liveRoles.map(role => role.id === id ? updated : role);
      return updated;
    });
    renderPages('/servidores/12', true);
    await user.click(await screen.findByText('Carregar mais membros'));
    for (const role of roles) {
      await user.click(within(screen.getByRole('heading', { name: role.name }).closest('article')!).getByText('Editar'));
      await user.clear(screen.getByLabelText('Nome do cargo'));
      await user.type(screen.getByLabelText('Nome do cargo'), role.name + ' atual');
      if (role.id === 5) {
        await user.clear(screen.getByLabelText('Posição'));
        await user.type(screen.getByLabelText('Posição'), '15');
      }
      await user.click(screen.getByText('Salvar alterações'));
      await screen.findByRole('heading', { name: role.name + ' atual' });
    }
    if (switchServer) await user.click(screen.getByText('Abrir servidor B'));
    await act(async () => page.resolve([members[1]]));
    if (switchServer) expect(screen.queryByLabelText('Cargos de member')).toBeNull();
    else {
      expect(screen.getByLabelText('Cargos de member').textContent).toBe('Membro atual · posição 15Moderador atual · posição 8');
      expect(screen.getByText('usuário0')).toBeVisible();
      expect(screen.queryByText('Carregar mais membros')).toBeNull();
    }
    expect(serverApi.listServerMembers).toHaveBeenCalledTimes(switchServer ? 3 : 2);
  });

  it('bloqueia a revogação do segundo convite até o término da primeira', async () => {
    const user = userEvent.setup();
    const pending = deferred<void>();
    const second = { ...invite, id: 32 };
    serverApi.listServerInvites.mockResolvedValueOnce([invite, second]).mockResolvedValue([second]);
    serverApi.revokeServerInvite.mockReturnValueOnce(pending.promise);
    renderPages('/servidores/12');
    const row = async (id: number) => within((await screen.findByText('Convite #' + id)).closest('article')!);
    await user.click((await row(31)).getByText('Revogar'));
    await user.click((await row(31)).getByText('Confirmar'));
    const other = (await row(32)).getByText('Revogar');
    expect(other).toBeDisabled();
    await user.click(other);
    expect((await row(31)).getByText('Confirmar')).toBeDisabled();
    expect(serverApi.revokeServerInvite.mock.calls).toEqual([[12, 31]]);
    await act(async () => pending.resolve());
    expect(screen.getByText(/Revogação do convite #31 confirmada/)).toBeVisible();
    await user.click((await row(32)).getByText('Revogar'));
    await user.click((await row(32)).getByText('Confirmar'));
    expect(serverApi.revokeServerInvite.mock.calls).toEqual([[12, 31], [12, 32]]);
  });

  it.each(['sucesso antigo', 'falha antiga', 'troca de servidor'])('isola feedback da cópia: %s', async scenario => {
    const user = userEvent.setup();
    const copy = deferred<void>();
    const write = vi.spyOn(navigator.clipboard, 'writeText').mockReturnValueOnce(copy.promise);
    serverApi.getServer.mockImplementation(async id => ({ ...server, id }));
    serverApi.createServerInvite.mockResolvedValueOnce({ ...invite, token: 'token-A' })
      .mockResolvedValueOnce({ ...invite, id: 32, token: 'token-B', server_id: scenario === 'troca de servidor' ? 13 : 12 });
    renderPages('/servidores/12', true);
    await user.click(await screen.findByText('Criar convite'));
    await user.click(await screen.findByLabelText('Copiar token do convite'));
    expect(write).toHaveBeenCalledWith('token-A');
    if (scenario === 'troca de servidor') await user.click(screen.getByText('Abrir servidor B'));
    await user.click(await screen.findByText('Criar convite'));
    await screen.findByText('token-B');
    await act(async () => scenario === 'falha antiga' ? copy.reject(new Error('clipboard')) : copy.resolve());
    expect(screen.getByLabelText('Copiar token do convite')).toHaveTextContent('Copiar');
    expect(screen.queryByText(/Não foi possível copiar/)).toBeNull();
    write.mockRejectedValueOnce(new Error('clipboard'));
    await user.click(screen.getByLabelText('Copiar token do convite'));
    expect(screen.getByText(/Não foi possível copiar/)).toBeVisible();
    write.mockResolvedValueOnce(undefined);
    await user.click(screen.getByLabelText('Copiar token do convite'));
    expect(write).toHaveBeenLastCalledWith('token-B');
    expect(screen.getByText('Copiado')).toBeVisible();
    expect(screen.queryByText(/Não foi possível copiar/)).toBeNull();
  });

  it.each(['inicial', 'retry', 'paginação', 'individual', 'erro antigo'])(
    'isola membros, cargos e destinatários ao trocar de servidor durante %s',
    async scenario => {
      const user = userEvent.setup();
      const stale = deferred<typeof members>();
      const current = deferred<typeof members>();
      const otherMember = { ...members[0], username: 'participante B', roles: [roles[0]] };
      serverApi.getServer.mockImplementation(async id => ({ ...server, id, name: id === 13 ? 'Servidor B' : server.name }));
      serverApi.getServerAuthorizationContext.mockImplementation(async id => ({ ...authorizationContext, server_id: id }));
      if (scenario === 'retry' || scenario === 'erro antigo') {
        serverApi.listServerMembers.mockRejectedValueOnce(new Error());
      }
      if (scenario === 'paginação') {
        serverApi.listServerMembers.mockResolvedValueOnce(Array.from({ length: 20 }, (_, index) => ({
          ...members[0], user_id: index + 1, username: 'Participante ' + index,
        })));
      }
      if (scenario === 'individual') {
        serverApi.listServerMembers.mockResolvedValueOnce(members);
        serverApi.getServerMember.mockImplementationOnce(async () => (await stale.promise)[0]);
      } else {
        serverApi.listServerMembers.mockReturnValueOnce(stale.promise);
      }
      serverApi.listServerMembers.mockReturnValueOnce(current.promise);
      renderPages('/servidores/12', true);
      await screen.findByRole('heading', { name: 'Membros ativos' });
      if (scenario === 'retry' || scenario === 'erro antigo') {
        await user.click(await screen.findByRole('button', { name: 'Tentar novamente' }));
      } else if (scenario === 'paginação') {
        await user.click(await screen.findByRole('button', { name: 'Carregar mais membros' }));
        expect(serverApi.listServerMembers).toHaveBeenCalledWith(12, 20, 20);
      } else if (scenario === 'individual') {
        await user.selectOptions(await screen.findByLabelText('Membro ativo'), '7');
        await user.selectOptions(screen.getByLabelText('Cargo individual'), '8');
        await user.click(screen.getByRole('button', { name: 'Atribuir' }));
        expect(serverApi.getServerMember).toHaveBeenCalledWith(12, 7);
      }
      await user.click(screen.getByRole('link', { name: 'Abrir servidor B' }));
      expect(serverApi.listServerMembers).toHaveBeenLastCalledWith(13);
      expect(await screen.findByText('Carregando membros…')).toBeVisible();
      if (scenario === 'erro antigo') {
        await act(async () => stale.reject(new ApiError('Falha antiga', 422)));
        expect(screen.getByText('Carregando membros…')).toBeVisible();
        expect(screen.queryByText('Falha antiga')).toBeNull();
      }
      await act(async () => current.resolve([otherMember]));
      if (scenario !== 'erro antigo') {
        await act(async () => stale.resolve(Array.from({ length: 20 }, (_, i) => ({
          ...members[0], user_id: i + 7, username: 'Antigo ' + i, roles: [roles[1]],
        }))));
      }
      expect(screen.getByText('participante B')).toBeVisible();
      expect(screen.getByLabelText('Cargos de participante B')).toHaveTextContent('Membro · posição 1');
      expect(screen.queryByText('Antigo 0')).toBeNull();
      const selector = within(screen.getByLabelText('Membro ativo'));
      expect(selector.getAllByRole('option')).toHaveLength(2);
      expect(selector.getByRole('option', { name: 'participante B · ID 7' })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Carregar mais membros' })).toBeNull();
    },
  );

  it('recupera a lista de membros ao tentar novamente no mesmo servidor', async () => {
    serverApi.listServerMembers.mockRejectedValueOnce(new Error());
    renderPages('/servidores/12');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Tentar novamente' }));
    expect(await screen.findByText('member')).toBeVisible();
    expect(screen.getByLabelText('Cargos de member')).toHaveTextContent('Moderador · posição 8');
    expect(serverApi.listServerMembers.mock.calls).toEqual([[12], [12]]);
  });

  it('lista servidores ativos e navega aos detalhes e membros', async () => {
    const user = userEvent.setup();
    renderPages();

    expect(await screen.findByText('Comunidade SafeTalk')).toBeVisible();
    expect(screen.getByRole('link', { name: /Servidores/ })).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: /Comunidade SafeTalk/ }));

    expect(await screen.findByRole('heading', { name: 'Membros ativos' })).toBeVisible();
    expect(await screen.findByText('member')).toBeVisible();
    const memberRoles = within(screen.getByLabelText('Cargos de member'));
    expect(memberRoles.getByText('Moderador · posição 8')).toBeVisible();
    expect(memberRoles.getByText('Membro · posição 1')).toBeVisible();
    expect(within(screen.getByLabelText('Cargos de owner')).getByText('Sem cargos individuais')).toBeVisible();
    expect(screen.getByText('Gerenciar convites: Ativa')).toBeVisible();
    expect(screen.getByText('Expulsar membros: Inativa')).toBeVisible();
    expect(screen.getByText(/proprietário, com autoridade especial/i)).toBeVisible();
    expect(screen.getAllByText('Proprietário')).toHaveLength(2);
    expect(serverApi.getServer).toHaveBeenCalledWith(12);
    expect(serverApi.getServerAuthorizationContext).toHaveBeenCalledWith(12);
    expect(serverApi.listServerMembers).toHaveBeenCalledWith(12);
  });

  it('cria servidor pelo contrato da API e abre os detalhes', async () => {
    const user = userEvent.setup();
    renderPages();
    await screen.findByText('Comunidade SafeTalk');

    await user.clear(screen.getByLabelText('Nome do servidor'));
    await user.type(screen.getByLabelText('Nome do servidor'), '  Novo espaço  ');
    await user.type(screen.getByLabelText(/Descrição/), '  Descrição nova  ');
    await user.click(screen.getByRole('button', { name: 'Criar servidor' }));

    await screen.findByRole('heading', { name: 'Membros ativos' });
    expect(serverApi.createServer).toHaveBeenCalledWith({ name: 'Novo espaço', description: 'Descrição nova' });
  });

  it('mostra estado vazio quando a conta não possui servidores', async () => {
    serverApi.listServers.mockResolvedValue([]);
    renderPages();
    expect(await screen.findByText('Você ainda não participa de servidores')).toBeVisible();
    expect(screen.getByText(/aceite um convite válido para entrar em um servidor/i)).toBeVisible();
  });

  it('apresenta falha de autorização ao carregar a lista', async () => {
    serverApi.listServers.mockRejectedValue(new ApiError('Sem autorização.', 403));
    renderPages();
    expect(await screen.findByRole('alert')).toHaveTextContent('A API não autorizou esta operação.');
  });

  it('apresenta erros de validação 422 ao criar servidor', async () => {
    const user = userEvent.setup();
    serverApi.createServer.mockRejectedValue(new ApiError('O nome do servidor não pode estar vazio.', 422));
    renderPages();
    await screen.findByText('Comunidade SafeTalk');
    await user.type(screen.getByLabelText('Nome do servidor'), 'Grupo novo');
    await user.click(screen.getByRole('button', { name: 'Criar servidor' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('O nome do servidor não pode estar vazio.');
  });

  it('mostra erro 404 quando o usuário não tem acesso aos detalhes', async () => {
    serverApi.getServer.mockRejectedValue(new ApiError('Servidor não encontrado.', 404));
    renderPages('/servidores/999');
    expect(await screen.findByRole('alert')).toHaveTextContent('Servidor indisponível. Confira sua participação e a idade declarada para acesso +18.');
    expect(screen.getByRole('link', { name: 'Voltar à lista' })).toHaveAttribute('href', '/servidores');
  });

  it('permite buscar mais membros respeitando o offset do backend', async () => {
    const user = userEvent.setup();
    serverApi.listServerMembers
      .mockResolvedValueOnce(Array.from({ length: 20 }, (_, index) => ({ user_id: index + 1, username: `membro_${index + 1}`, joined_at: '2026-11-01T10:00:00Z', roles: [] })))
      .mockResolvedValueOnce([{ user_id: 21, username: 'membro_21', joined_at: '2026-11-02T10:00:00Z', roles: [] }]);
    renderPages('/servidores/12');
    await screen.findByText('membro_20');
    await user.click(screen.getByRole('button', { name: 'Carregar mais membros' }));
    expect(await screen.findByText('membro_21')).toBeVisible();
    expect(serverApi.listServerMembers).toHaveBeenLastCalledWith(12, 20, 20);
  });

  it('exibe navegação de servidores no layout principal', () => {
    render(<MemoryRouter initialEntries={['/servidores']}><DashboardLayout title="Servidores" description="Teste"><div /></DashboardLayout></MemoryRouter>);
    expect(screen.getByRole('link', { name: /Servidores/ })).toHaveAttribute('href', '/servidores');
  });

  it('aceita convite usando servidor no caminho e token no corpo e atualiza a lista', async () => {
    const user = userEvent.setup();
    const invitedServer = { ...server, id: 44, name: 'Servidor convidado' };
    serverApi.acceptServerInvite.mockResolvedValueOnce({ server_id: 44, user_id: 7, status: 'ACTIVE', joined_at: '2026-11-20T10:00:00Z', left_at: null });
    serverApi.listServers.mockResolvedValueOnce([server]).mockResolvedValueOnce([server, invitedServer]);
    renderPages();
    await screen.findByText('Comunidade SafeTalk');

    await user.type(screen.getByLabelText('ID do servidor do convite'), '44');
    await user.type(screen.getByLabelText('Token do convite'), 'invite-token-from-owner');
    await user.click(screen.getByRole('button', { name: 'Aceitar convite' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Entrada confirmada no servidor 44');
    expect(await screen.findByText('Servidor convidado')).toBeVisible();
    expect(serverApi.acceptServerInvite).toHaveBeenCalledWith(44, 'invite-token-from-owner');
    expect(serverApi.listServers).toHaveBeenCalledTimes(2);
  });

  async function submitInvite(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText('ID do servidor do convite'), '12');
    await user.type(screen.getByLabelText('Token do convite'), 'convite-de-teste');
    await user.click(screen.getByRole('button', { name: 'Aceitar convite' }));
  }

  it.each(['GET inicial', 'releitura manual'])('descarta %s que termina após a releitura do aceite', async origin => {
    const user = userEvent.setup();
    const older = deferred<(typeof server)[]>();
    const latest = deferred<(typeof server)[]>();
    if (origin === 'releitura manual') serverApi.listServers.mockResolvedValueOnce([]);
    serverApi.listServers.mockReturnValueOnce(older.promise).mockReturnValueOnce(latest.promise);
    renderPages();
    if (origin === 'releitura manual') {
      await screen.findByText('Você ainda não participa de servidores');
      await user.click(screen.getByRole('button', { name: 'Atualizar' }));
    }
    await submitInvite(user);
    expect(screen.getByText(/Entrada confirmada no servidor 12/)).toHaveTextContent('Atualizando sua lista');
    await act(async () => latest.resolve([server]));
    expect(screen.getByText(server.name)).toBeVisible();
    await act(async () => older.resolve([]));
    expect(screen.getByText(server.name)).toBeVisible();
    expect(screen.getByText(/Entrada confirmada no servidor 12/)).toHaveTextContent('Sua lista foi atualizada.');
    expect(screen.queryByText('Você ainda não participa de servidores')).toBeNull();
  });

  it('preserva o aceite quando o GET falha e recupera a lista repetindo somente o GET', async () => {
    const user = userEvent.setup();
    const initial = deferred<(typeof server)[]>();
    const refresh = deferred<(typeof server)[]>();
    const retry = deferred<(typeof server)[]>();
    serverApi.listServers.mockReturnValueOnce(initial.promise).mockReturnValueOnce(refresh.promise).mockReturnValueOnce(retry.promise);
    renderPages();
    await submitInvite(user);
    await act(async () => refresh.reject(new Error('Falha de conexão')));
    const confirmation = screen.getByText(/Entrada confirmada no servidor 12/);
    expect(confirmation).toHaveTextContent('Não foi possível atualizar sua lista.');
    await user.click(screen.getByRole('button', { name: 'Tentar novamente' }));
    await act(async () => initial.reject(new Error('Erro antigo')));
    expect(confirmation).toHaveTextContent('Atualizando sua lista');
    expect(screen.getByText('Carregando servidores…')).toBeVisible();
    expect(screen.queryByRole('alert')).toBeNull();
    await act(async () => retry.resolve([server]));
    expect(confirmation).toHaveTextContent('Sua lista foi atualizada.');
    expect(screen.getByText(server.name)).toBeVisible();
    expect(serverApi.acceptServerInvite).toHaveBeenCalledTimes(1);
    expect(serverApi.listServers).toHaveBeenCalledTimes(3);
  });

  it.each(['recusado', 'desmontado'])('POST de aceite %s não confirma entrada nem inicia releitura', async outcome => {
    const user = userEvent.setup();
    const post = deferred<{ server_id: number }>();
    serverApi.acceptServerInvite.mockReturnValueOnce(post.promise);
    const page = renderPages();
    await submitInvite(user);
    expect(screen.queryByText(/Entrada confirmada/)).toBeNull();
    if (outcome === 'desmontado') {
      page.unmount();
      await act(async () => post.resolve({ server_id: 12 }));
    } else {
      await act(async () => post.reject(new ApiError('O convite expirou.', 409)));
      expect(screen.getByRole('alert')).toHaveTextContent('O convite expirou.');
    }
    expect(screen.queryByText(/Entrada confirmada/)).toBeNull();
    expect(serverApi.listServers).toHaveBeenCalledTimes(1);
  });

  it('mostra a resposta 409 recebida para convite expirado ou indisponível', async () => {
    const user = userEvent.setup();
    serverApi.acceptServerInvite.mockRejectedValue(new ApiError('O convite expirou.', 409));
    renderPages();
    await screen.findByText('Comunidade SafeTalk');
    await user.type(screen.getByLabelText('ID do servidor do convite'), '12');
    await user.type(screen.getByLabelText('Token do convite'), 'expired-token');
    await user.click(screen.getByRole('button', { name: 'Aceitar convite' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('O convite expirou.');
  });

  it('apresenta erro não enumerável 404 para token inválido', async () => {
    const user = userEvent.setup();
    serverApi.acceptServerInvite.mockRejectedValue(new ApiError('Convite não encontrado ou inválido.', 404));
    renderPages();
    await screen.findByText('Comunidade SafeTalk');
    await user.type(screen.getByLabelText('ID do servidor do convite'), '12');
    await user.type(screen.getByLabelText('Token do convite'), 'invalid-token');
    await user.click(screen.getByRole('button', { name: 'Aceitar convite' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Convite inválido ou servidor indisponível. Confira o ID e o token.');
  });

  it.each([true, false])('guarda a confirmação sem revelar o token até recuperar a lista (autorizado=%s)', async allowed => {
    const user = userEvent.setup();
    const retry = deferred<(typeof invite)[]>();
    serverApi.listServerInvites.mockResolvedValueOnce([]).mockRejectedValueOnce(new ApiError('Sem acesso.', 403)).mockReturnValueOnce(retry.promise);
    serverApi.getServerAuthorizationContext.mockResolvedValueOnce(authorizationContext)
      .mockResolvedValueOnce({ ...authorizationContext, is_owner: allowed, effective_permissions: [] });
    renderPages('/servidores/12', true);
    await screen.findByRole('heading', { name: 'Convites' });
    await user.click(screen.getByRole('button', { name: 'Criar convite' }));
    expect(await screen.findByText('Criação do convite confirmada pelo servidor.')).toBeVisible();
    expect(screen.queryByText('raw-invite-token')).toBeNull();
    expect(screen.queryByLabelText('Copiar token do convite')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Verificar acesso aos convites' }));
    expect(screen.queryByLabelText('Copiar token do convite')).toBeNull();
    expect(screen.queryByText('raw-invite-token')).toBeNull();
    await act(async () => retry.resolve([invite]));
    expect(await screen.findByLabelText('Copiar token do convite')).toBeVisible();
    expect(screen.getByText('raw-invite-token')).toBeVisible();
    serverApi.getServer.mockResolvedValueOnce({ ...server, id: 13 });
    await user.click(screen.getByRole('link', { name: 'Abrir servidor B' }));
    await screen.findByRole('heading', { name: 'Convites' });
    expect(screen.queryByText('raw-invite-token')).toBeNull();
    expect(serverApi.createServerInvite).toHaveBeenCalledTimes(1);
  });

  it('não oferece gerenciamento quando o backend nega a permissão de convites', async () => {
    serverApi.listServerInvites.mockRejectedValue(new ApiError('Você não pode gerenciar convites deste servidor.', 403));
    renderPages('/servidores/12');
    expect(await screen.findByRole('alert')).toHaveTextContent(/proprietário ou um membro com manage_invites/i);
    expect(screen.queryByRole('button', { name: 'Criar convite' })).not.toBeInTheDocument();
  });

  it('cria convite, mostra o token somente na confirmação e não o confunde com metadados listados', async () => {
    const user = userEvent.setup();
    serverApi.listServerInvites.mockResolvedValue([invite]);
    renderPages('/servidores/12');
    expect(await screen.findByText('Convite #31')).toBeVisible();
    expect(screen.queryByText('raw-invite-token')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/Expiração/), '2026-12-20T10:30');
    await user.type(screen.getByLabelText(/Limite de utilizações/), '3');
    await user.click(screen.getByRole('button', { name: 'Criar convite' }));

    expect(serverApi.createServerInvite).toHaveBeenCalledWith(12, {
      expires_at: new Date('2026-12-20T10:30').toISOString(),
      max_uses: 3,
    });
    expect(await screen.findByText('raw-invite-token')).toBeVisible();
    expect(screen.getByText('ID do servidor')).toBeVisible();
  });

  it.each([
    [1, 'Uma utilização'], [4, 'Até 4 utilizações'], [null, 'Sem limite de utilizações'],
  ] as const)('descreve o limite confirmado pela criação: %s', async (limit, label) => {
    serverApi.createServerInvite.mockResolvedValueOnce({ ...invite, max_uses: limit, token: 'token-test' });
    const user = userEvent.setup();
    renderPages('/servidores/12');
    if (limit !== null) await user.type(await screen.findByLabelText(/Limite de utilizações/), String(limit));
    await user.click(await screen.findByRole('button', { name: 'Criar convite' }));
    expect(await screen.findByText(label)).toBeVisible();
    expect(screen.getByText('Token do convite')).toBeVisible();
    expect(serverApi.createServerInvite).toHaveBeenCalledWith(12, limit === null ? {} : { max_uses: limit });
  });

  it.each(['criação', 'revogação'])('revalida o contexto após 403 na %s e recupera o acesso sem repetir a escrita', async operation => {
    const user = userEvent.setup();
    const denied = deferred<typeof authorizationContext>();
    const manager = { ...authorizationContext, is_owner: false };
    serverApi.getServerAuthorizationContext.mockResolvedValueOnce(manager).mockReturnValueOnce(denied.promise)
      .mockResolvedValueOnce(manager);
    serverApi.listServerInvites.mockResolvedValue([invite]);
    const write = operation === 'criação' ? serverApi.createServerInvite : serverApi.revokeServerInvite;
    write.mockRejectedValueOnce(new ApiError('Recusada', 403));
    renderPages('/servidores/12');
    await screen.findByText('Convite #31');
    if (operation === 'criação') await user.click(screen.getByRole('button', { name: 'Criar convite' }));
    else {
      await user.click(screen.getByRole('button', { name: 'Revogar' }));
      await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    }
    expect(screen.getByRole('alert')).toHaveTextContent(/recusada/i);
    expect(screen.getByText('Verificando acesso aos convites…')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Criar convite' })).toBeNull();
    await act(async () => denied.resolve({ ...manager, effective_permissions: [] }));
    expect(screen.queryByText('Convite #31')).toBeNull();
    expect(screen.queryByText('Convite criado')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Verificar acesso aos convites' }));
    expect(await screen.findByText('Convite #31')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Criar convite' })).toBeEnabled();
    expect(serverApi.getServerAuthorizationContext.mock.calls).toEqual([[12], [12], [12]]);
    expect(write).toHaveBeenCalledTimes(1);
    expect(serverApi.getServer).toHaveBeenCalledTimes(1);
  });

  it('mantém os controles fechados durante a carga inicial e após falha do contexto', async () => {
    const first = deferred<typeof authorizationContext>();
    serverApi.getServerAuthorizationContext.mockReturnValueOnce(first.promise);
    renderPages('/servidores/12');
    expect(await screen.findByText('Verificando acesso aos convites…')).toBeVisible();
    await act(async () => first.reject(new Error('offline')));
    expect(screen.getByText('Gerenciamento de convites indisponível para o contexto atual.')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Criar convite' })).toBeNull();
    expect(serverApi.listServerInvites).not.toHaveBeenCalled();
  });

  it('ignora uma página antiga após atualizar a lista do mesmo servidor', async () => {
    const user = userEvent.setup();
    const page = deferred<(typeof invite)[]>();
    serverApi.listServerInvites.mockResolvedValueOnce(Array.from({ length: 20 }, (_, i) => ({ ...invite, id: i + 1 })))
      .mockReturnValueOnce(page.promise).mockResolvedValueOnce([invite]);
    renderPages('/servidores/12');
    await user.click(await screen.findByRole('button', { name: 'Carregar mais convites' }));
    await user.click(screen.getByRole('button', { name: 'Atualizar' }));
    expect(await screen.findByText('Convite #31')).toBeVisible();
    await act(async () => page.resolve([{ ...invite, id: 99 }]));
    expect(screen.queryByText('Convite #99')).toBeNull();
    expect(screen.getByText('Convite #31')).toBeVisible();
  });

  it.each(['autorizado', '403', 'POST primeiro'])('preserva a criação durante revalidação: %s', async outcome => {
    const user = userEvent.setup();
    const post = deferred<typeof invite & { token: string }>();
    const context = deferred<typeof authorizationContext>();
    serverApi.createServerInvite.mockReturnValueOnce(post.promise);
    serverApi.getServerAuthorizationContext.mockResolvedValueOnce(authorizationContext).mockReturnValueOnce(context.promise);
    serverApi.updateEveryonePermissions.mockResolvedValue({ server_id: 12, everyone_permissions: {} });
    renderPages('/servidores/12');
    await user.click(await screen.findByRole('button', { name: 'Criar convite' }));
    await user.click(screen.getByRole('button', { name: 'Editar permissões de @everyone' }));
    await user.click(screen.getByRole('button', { name: 'Salvar permissões' }));
    expect(screen.getByText('Verificando acesso aos convites…')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Criar convite' })).toBeNull();
    const confirmPost = () => act(async () => post.resolve({ ...invite, token: 'token-confirmado' }));
    if (outcome === '403') {
      await act(async () => context.reject(new ApiError('Acesso recusado', 403)));
      await confirmPost();
      expect(screen.getByText('Criação do convite confirmada pelo servidor.')).toBeVisible();
      expect(screen.queryByText('token-confirmado')).toBeNull();
      expect(screen.queryByRole('button', { name: 'Criar convite' })).toBeNull();
      expect(serverApi.listServerInvites).toHaveBeenCalledTimes(1);
      await user.click(screen.getByRole('button', { name: 'Verificar acesso aos convites' }));
    } else if (outcome === 'POST primeiro') {
      await confirmPost();
      expect(screen.getByText('Criação do convite confirmada pelo servidor.')).toBeVisible();
      await act(async () => context.resolve(authorizationContext));
    } else {
      await act(async () => context.resolve(authorizationContext));
      const submit = screen.getByRole('button', { name: 'Criar convite' });
      expect(submit).toBeDisabled();
      await user.click(submit);
      expect(screen.queryByText('Convite criado')).toBeNull();
      await confirmPost();
    }
    expect(await screen.findByText('token-confirmado')).toBeVisible();
    expect(serverApi.createServerInvite.mock.calls).toEqual([[12, {}]]);
  });

  it.each([true, false])('recupera a listagem sem repetir um POST confirmado=%s', async confirmed => {
    const user = userEvent.setup();
    const post = deferred<typeof invite & { token: string }>();
    serverApi.createServerInvite.mockReturnValueOnce(post.promise);
    renderPages('/servidores/12');
    await user.click(await screen.findByRole('button', { name: 'Criar convite' }));
    if (confirmed) {
      serverApi.listServerInvites.mockRejectedValueOnce(new Error('Offline'));
      await act(async () => post.resolve({ ...invite, token: 'token-confirmado' }));
      expect(screen.getByText('token-confirmado')).toBeVisible();
      await user.click(screen.getByRole('button', { name: 'Tentar novamente' }));
      expect(screen.getByText('token-confirmado')).toBeVisible();
    } else {
      await act(async () => post.reject(new ApiError('Erro de conexão')));
      expect(screen.getByRole('alert')).toHaveTextContent(/não foi possível confirmar a criação/i);
      await user.click(screen.getByRole('button', { name: 'Atualizar' }));
      expect(screen.queryByText('Convite criado')).toBeNull();
    }
    expect(screen.getByText('Nenhum convite criado')).toBeVisible();
    expect(serverApi.createServerInvite.mock.calls).toEqual([[12, {}]]);
  });

  it('descarta criação concluída em A após a navegação e confirmação de outro convite em B', async () => {
    const user = userEvent.setup();
    const pending = deferred<typeof invite & { token: string }>();
    serverApi.createServerInvite.mockReturnValueOnce(pending.promise);
    serverApi.getServer.mockImplementation(async id => ({ ...server, id }));
    serverApi.getServerAuthorizationContext.mockImplementation(async id => ({ ...authorizationContext, server_id: id }));
    serverApi.listServerInvites.mockResolvedValueOnce([]).mockResolvedValueOnce([{ ...invite, id: 99, server_id: 13 }]);
    renderPages('/servidores/12', true);
    await user.click(await screen.findByRole('button', { name: 'Criar convite' }));
    await user.click(screen.getByRole('link', { name: 'Abrir servidor B' }));
    expect(await screen.findByText('Convite #99')).toBeVisible();
    serverApi.createServerInvite.mockResolvedValueOnce({ ...invite, server_id: 13, token: 'token-de-b' });
    await user.click(screen.getByRole('button', { name: 'Criar convite' }));
    expect(await screen.findByText('token-de-b')).toBeVisible();
    await act(async () => pending.resolve({ ...invite, token: 'token-antigo' }));
    expect(screen.queryByText('token-antigo')).toBeNull();
    expect(screen.getByText('token-de-b')).toBeVisible();
    expect(serverApi.listServerInvites.mock.calls).toEqual([[12, 20, 0], [13, 20, 0], [13, 20, 0]]);
  });

  it('revoga somente após confirmação e atualiza o estado da lista', async () => {
    const user = userEvent.setup();
    serverApi.listServerInvites.mockResolvedValue([invite]);
    renderPages('/servidores/12');
    await screen.findByText('Convite #31');
    await user.click(screen.getByRole('button', { name: 'Revogar' }));
    expect(serverApi.revokeServerInvite).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));
    expect(serverApi.revokeServerInvite).toHaveBeenCalledWith(12, 31);
    expect(serverApi.listServerInvites).toHaveBeenCalledTimes(2);
  });

  it('apresenta erro de validação da API ao criar convite', async () => {
    const user = userEvent.setup();
    serverApi.createServerInvite.mockRejectedValue(new ApiError('A expiração deve estar no futuro.', 422));
    renderPages('/servidores/12');
    await screen.findByRole('heading', { name: 'Convites' });
    await user.click(screen.getByRole('button', { name: 'Criar convite' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A expiração deve estar no futuro.');
    expect(serverApi.createServerInvite).toHaveBeenCalledTimes(1);
  });

  it('orienta a consultar a lista após timeout convertido pelo interceptor Axios', async () => {
    const user = userEvent.setup();
    const timeout = vi.fn(async () => { throw new AxiosError('timeout', 'ECONNABORTED'); });
    serverApi.createServerInvite.mockImplementationOnce(() => api.post('/servers/12/invites', {}, { adapter: timeout }));
    renderPages('/servidores/12');
    await user.click(await screen.findByRole('button', { name: 'Criar convite' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/pode ter sido criado.*consulte a lista/i);
    await user.click(screen.getByRole('button', { name: 'Atualizar' }));
    expect(timeout).toHaveBeenCalledTimes(1);
    expect(serverApi.createServerInvite).toHaveBeenCalledTimes(1);
  });

  it.each(['contexto primeiro', '204 primeiro', 'revalidação posterior', 'outro servidor'])(
    'isola revogação durante revalidação: %s', async order => {
      const user = userEvent.setup();
      const write = deferred<void>();
      const context = deferred<typeof authorizationContext>();
      serverApi.getServer.mockImplementation(async id => ({ ...server, id }));
      serverApi.listServerInvites.mockResolvedValue([invite]);
      serverApi.revokeServerInvite.mockReturnValueOnce(write.promise);
      serverApi.updateEveryonePermissions.mockResolvedValue({ server_id: 12, everyone_permissions: {} });
      renderPages('/servidores/12', true);
      await user.click(await screen.findByRole('button', { name: 'Revogar' }));
      await user.dblClick(screen.getByRole('button', { name: 'Confirmar' }));
      const confirmed = 'Revogação do convite #31 confirmada pelo servidor.';
      if (order === 'outro servidor') {
        serverApi.listServerInvites.mockResolvedValue([]);
        await user.click(screen.getByRole('link', { name: 'Abrir servidor B' }));
        await screen.findByText('Nenhum convite criado');
        await act(async () => write.resolve());
        expect(screen.queryByText(confirmed)).toBeNull();
      } else {
        serverApi.getServerAuthorizationContext.mockReturnValueOnce(context.promise);
        if (order === 'revalidação posterior') {
          serverApi.listServerInvites.mockRejectedValueOnce(new Error('offline'));
          await act(async () => write.resolve());
          expect(screen.getByText(confirmed)).toBeVisible();
          expect(screen.getByText(/não foi possível carregar os convites/i)).toBeVisible();
        }
        await user.click(screen.getByRole('button', { name: 'Editar permissões de @everyone' }));
        await user.click(screen.getByRole('button', { name: 'Salvar permissões' }));
        if (order === '204 primeiro') {
          await act(async () => write.resolve());
          expect(screen.getByText(confirmed)).toBeVisible();
        }
        await act(async () => context.resolve(authorizationContext));
        if (order === 'contexto primeiro') {
          const button = screen.getByRole('button', { name: 'Confirmar' });
          expect(button).toBeDisabled();
          await user.click(button);
          await act(async () => write.resolve());
        }
        expect(screen.getByText(confirmed)).toBeVisible();
      }
      expect(serverApi.revokeServerInvite.mock.calls).toEqual([[12, 31]]);
    },
  );

  it('lista cargos por hierarquia e exibe somente permissões conhecidas concedidas', async () => {
    renderPages('/servidores/12');
    expect(await screen.findByText(/Maior posição cadastrada:/)).toBeVisible();
    expect(screen.getByText('POSIÇÃO 8 · MAIOR NÍVEL')).toBeVisible();
    expect(screen.getAllByText('Expulsar membros')).toHaveLength(2);
    expect(screen.getAllByText('Gerenciar cargos')).toHaveLength(2);
    expect(screen.getByText('@everyone é implícito e não aparece como cargo atribuído.')).toBeVisible();
  });

  it.each(['lista antiga', 'erro antigo', 'antiga durante loading', 'troca de servidor'])(
    'ordena as releituras após editar e excluir cargos: %s', async order => {
      const user = userEvent.setup();
      const first = deferred<typeof roles>();
      const latest = deferred<typeof roles>();
      const deletion = deferred<void>();
      const renamed = { ...roles[0], name: 'Cargo renomeado' };
      serverApi.listServerMembers.mockResolvedValue(members.map(member => ({ ...member, roles: [] })));
      serverApi.getServer.mockImplementation(async id => ({ ...server, id }));
      serverApi.deleteServerRole.mockReturnValueOnce(deletion.promise);
      serverApi.updateServerRole.mockResolvedValueOnce(renamed);
      serverApi.listServerRoles.mockResolvedValueOnce(roles).mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(latest.promise).mockResolvedValueOnce([{ ...renamed, name: 'Cargo B', server_id: 13 }]);
      renderPages('/servidores/12', true);
      await user.click(await screen.findByRole('button', { name: 'Excluir Moderador' }));
      await user.click(screen.getByRole('button', { name: 'Confirmar exclusão' }));
      await user.click(within(screen.getByRole('heading', { name: 'Membro' }).closest('article')!).getByRole('button', { name: 'Editar' }));
      await user.clear(screen.getByLabelText('Nome do cargo'));
      await user.type(screen.getByLabelText('Nome do cargo'), renamed.name);
      await user.click(screen.getByRole('button', { name: 'Salvar alterações' }));
      expect(serverApi.listServerRoles).toHaveBeenCalledTimes(2);
      await act(async () => deletion.resolve());
      expect(serverApi.listServerRoles).toHaveBeenCalledTimes(3);
      if (order === 'troca de servidor') {
        await user.click(screen.getByRole('link', { name: 'Abrir servidor B' }));
        await screen.findByRole('heading', { name: 'Cargo B' });
        await act(async () => { first.resolve(roles); latest.reject(new Error('erro de A')); });
      } else {
        if (order === 'antiga durante loading') {
          await act(async () => first.resolve(roles));
          expect(screen.getByText('Carregando cargos…')).toBeVisible();
          expect(screen.getByLabelText('Cargo individual')).toBeDisabled();
        }
        await act(async () => latest.resolve([renamed]));
        if (order === 'erro antigo') await act(async () => first.reject(new Error('offline')));
        if (order === 'lista antiga') await act(async () => first.resolve(roles));
      }
      const expected = order === 'troca de servidor' ? 'Cargo B' : renamed.name;
      expect(screen.getByRole('heading', { name: expected })).toBeVisible();
      expect(screen.queryByRole('heading', { name: 'Moderador' })).toBeNull();
      expect(screen.queryByText('Carregando cargos…')).toBeNull();
      expect(screen.queryByRole('alert')).toBeNull();
      expect(within(screen.getByLabelText('Cargo individual')).getAllByRole('option').map(o => o.textContent))
        .toEqual(['Selecione um cargo', expected + ' · posição 1']);
    },
  );

  it('cria cargo com os campos suportados e permissões do catálogo conhecido', async () => {
    const user = userEvent.setup();
    renderPages('/servidores/12');
    await screen.findByText(/Maior posição cadastrada:/);
    await user.type(screen.getByLabelText('Nome do cargo'), 'Ajudante');
    await user.clear(screen.getByLabelText('Posição'));
    await user.type(screen.getByLabelText('Posição'), '3');
    await user.type(screen.getByLabelText(/Descrição/), 'Ajuda na comunidade');
    await user.click(screen.getByLabelText('Gerenciar convites'));
    await user.click(screen.getByRole('button', { name: 'Criar cargo' }));
    expect(serverApi.createServerRole).toHaveBeenCalledWith(12, {
      name: 'Ajudante',
      description: 'Ajuda na comunidade',
      position: 3,
      permissions: { kick_members: false, ban_members: false, unban_members: false, manage_invites: true, manage_roles: false, mention_everyone: false },
    });
  });

  it('envia apenas o nome alterado por PATCH', async () => {
    const user = userEvent.setup();
    renderPages('/servidores/12');
    await screen.findByText(/Maior posição cadastrada:/);
    await user.click(screen.getAllByRole('button', { name: 'Editar' })[0]);
    await user.clear(screen.getByLabelText('Nome do cargo'));
    await user.type(screen.getByLabelText('Nome do cargo'), 'Moderador sênior');
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    expect(serverApi.updateServerRole).toHaveBeenCalledWith(12, 8, { name: 'Moderador sênior' });
  });

  it('envia somente a descrição e mantém o cargo exibido quando o PATCH falha', async () => {
    const user = userEvent.setup();
    serverApi.updateServerRole.mockRejectedValueOnce(new ApiError('Edição recusada.', 403));
    renderPages('/servidores/12');
    await user.click((await screen.findAllByRole('button', { name: 'Editar' }))[0]);
    await user.type(screen.getByLabelText(/Descrição/), 'Nova descrição');
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    expect(serverApi.updateServerRole).toHaveBeenCalledWith(12, 8, { description: 'Nova descrição' });
    expect(await screen.findByRole('alert')).toHaveTextContent('Edição recusada.');
    expect(screen.getByText('Sem descrição')).toBeVisible();
    expect(screen.queryByText('Cargo atualizado.')).toBeNull();
    expect(serverApi.listServerRoles).toHaveBeenCalledTimes(1);
  });

  it('envia apenas o mapa conhecido quando o proprietário altera uma permissão', async () => {
    const user = userEvent.setup();
    serverApi.listServerRoles.mockResolvedValue([{ ...roles[1], permissions: { ...roles[1].permissions, legacy_flag: true } }]);
    renderPages('/servidores/12');
    await user.click(await screen.findByRole('button', { name: 'Editar' }));
    await user.click(screen.getByLabelText('Banir membros'));
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    expect(serverApi.updateServerRole).toHaveBeenCalledWith(12, 8, { permissions: {
      ban_members: true, kick_members: true, manage_roles: true, manage_invites: false,
      mention_everyone: false, unban_members: false,
    } }, { kick_members: true, manage_roles: true, ban_members: false, manage_invites: false, mention_everyone: false, unban_members: false });
  });

  it.each(['cargo', '@everyone'])('recupera conflito em %s com leitura explícita e nova confirmação', async resource => {
    const user = userEvent.setup();
    const everyone = resource === '@everyone';
    const write = everyone ? serverApi.updateEveryonePermissions : serverApi.updateServerRole;
    write.mockRejectedValueOnce(new ApiError('Conflito', 409, { code: 'permissions_conflict' }));
    renderPages('/servidores/12');
    if (everyone) await user.click(await screen.findByRole('button', { name: 'Editar permissões de @everyone' }));
    else await user.click((await screen.findAllByRole('button', { name: 'Editar' }))[0]);
    const editor = within((await screen.findByText(everyone ? 'Editar permissões de @everyone' : 'Permissões deste cargo', { selector: 'legend' })).closest('form')!);
    const save = editor.getByRole('button', { name: everyone ? 'Salvar permissões' : 'Salvar alterações' });
    await user.click(editor.getByLabelText('Banir membros'));
    await user.click(save);
    expect(await screen.findByText(/alteradas em outra sessão/)).toBeVisible();
    expect(editor.getByLabelText('Banir membros')).toBeChecked();
    expect(save).toBeDisabled();
    const latest = { mention_everyone: true };
    const refreshedRole = { ...roles[1], permissions: latest };
    serverApi.getServerRole.mockResolvedValueOnce(refreshedRole);
    serverApi.getServer.mockResolvedValueOnce({ ...server, everyone_permissions: latest });
    if (everyone) expect(screen.getByText('Banir membros: Inativa')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Carregar configuração atual' }));
    expect(everyone ? serverApi.getServer : serverApi.getServerRole).toHaveBeenCalledWith(...(everyone ? [12] : [12, 8]));
    expect(editor.getByLabelText('Banir membros')).toBeChecked();
    expect(editor.getByLabelText('Mencionar todos')).toBeChecked();
    expect(write).toHaveBeenCalledTimes(1);
    expect(save).toBeEnabled();
    if (everyone) write.mockResolvedValueOnce({ server_id: 12, everyone_permissions: { ...latest, ban_members: true } });
    else write.mockResolvedValueOnce({ ...refreshedRole, permissions: { ...latest, ban_members: true } });
    await user.click(save);
    expect(write).toHaveBeenCalledTimes(2);
    const args = write.mock.calls[1];
    expect(args[everyone ? 2 : 3]).toMatchObject(latest);
    expect(everyone ? args[1] : args[2].permissions).toMatchObject({ ...latest, ban_members: true });
    expect(await screen.findByText(everyone ? 'Permissões de @everyone salvas.' : 'Cargo atualizado.')).toBeVisible();
  });

  it('confirma antes de excluir e mostra conflitos 409 do backend', async () => {
    const user = userEvent.setup();
    serverApi.listServerMembers.mockResolvedValue([]);
    serverApi.deleteServerRole.mockRejectedValue(new ApiError('Não é possível excluir um cargo que possui membros atribuídos.', 409));
    renderPages('/servidores/12');
    await screen.findByText(/Maior posição cadastrada:/);
    await user.click(screen.getByRole('button', { name: 'Excluir Moderador' }));
    expect(serverApi.deleteServerRole).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Confirmar exclusão' }));
    expect(serverApi.deleteServerRole).toHaveBeenCalledWith(12, 8);
    expect(await screen.findByRole('alert')).toHaveTextContent('Não é possível excluir um cargo que possui membros atribuídos.');
  });

  it.each([
    { remove: false, self: false, failRead: false },
    { remove: false, self: false, failRead: true },
    { remove: true, self: false, failRead: true },
    { remove: false, self: true, failRead: true },
  ])('separa escrita e leitura de cargo ($remove, $self, $failRead)', async ({ remove, self, failRead }) => {
    const user = userEvent.setup();
    const target = { ...members[self ? 0 : 1], roles: remove ? [roles[1]] : [] };
    const updated = { ...target, roles: remove ? [] : [roles[1]] };
    const write = deferred<void>();
    const read = deferred<typeof updated>();
    const mutation = remove ? serverApi.removeServerRoleFromMember : serverApi.assignServerRoleToMember;
    const confirmation = remove ? 'A remoção foi confirmada pela API.' : 'A atribuição foi confirmada pela API.';
    mutation.mockReturnValueOnce(write.promise);
    serverApi.listServerMembers.mockResolvedValue([target]);
    serverApi.getServerMember.mockReturnValueOnce(read.promise).mockResolvedValueOnce(updated);
    renderPages('/servidores/12');
    await user.selectOptions(await screen.findByLabelText('Membro ativo'), String(target.user_id));
    await user.selectOptions(screen.getByLabelText('Cargo individual'), '8');
    await user.click(screen.getByRole('button', { name: remove ? 'Remover' : 'Atribuir' }));
    expect(mutation).toHaveBeenCalledWith(12, target.user_id, 8);
    expect(serverApi.getServerMember).not.toHaveBeenCalled();
    expect(screen.queryByText(confirmation)).toBeNull();
    await act(async () => write.resolve());
    expect(screen.getByText(confirmation)).toBeVisible();
    expect(serverApi.getServerMember).toHaveBeenCalledWith(12, target.user_id);
    expect(serverApi.getServerAuthorizationContext).toHaveBeenCalledTimes(self ? 2 : 1);
    const badges = screen.getByLabelText('Cargos de ' + target.username);
    if (failRead) {
      await act(async () => read.reject(new Error('offline')));
      expect(screen.getByText(confirmation)).toBeVisible();
      expect(screen.getByRole('alert')).toHaveTextContent('A alteração foi salva');
      expect(badges).toHaveTextContent(remove ? 'Moderador' : 'Sem cargos individuais');
      expect(screen.getByRole('button', { name: remove ? 'Remover' : 'Atribuir' })).toBeDisabled();
      await user.click(screen.getByRole('button', { name: 'Atualizar membro novamente' }));
      expect(screen.queryByRole('alert')).toBeNull();
    } else {
      await act(async () => read.resolve(updated));
    }
    expect(badges).toHaveTextContent(remove ? 'Sem cargos individuais' : 'Moderador');
    expect(serverApi.getServerMember.mock.calls).toEqual(Array(failRead ? 2 : 1).fill([12, target.user_id]));
    expect(mutation).toHaveBeenCalledTimes(1);
    expect(serverApi.getServerAuthorizationContext).toHaveBeenCalledTimes(self ? 2 : 1);
  });

  it.each([403, 404, 409])('preserva o membro e só revalida autorização em caso de 403 após PUT rejeitado com %i', async status => {
    const user = userEvent.setup();
    const write = deferred<void>();
    serverApi.assignServerRoleToMember.mockReturnValueOnce(write.promise);
    renderPages('/servidores/12');
    await user.selectOptions(await screen.findByLabelText('Membro ativo'), '7');
    await user.selectOptions(screen.getByLabelText('Cargo individual'), '8');
    await user.click(screen.getByRole('button', { name: 'Atribuir' }));
    await act(async () => write.reject(new ApiError('Rejeitado pela API.', status)));
    expect(serverApi.assignServerRoleToMember.mock.calls).toEqual([[12, 7, 8]]);
    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível atribuir o cargo. Rejeitado pela API.');
    expect(screen.queryByText('A atribuição foi confirmada pela API.')).toBeNull();
    expect(screen.getByLabelText('Cargos de owner')).toHaveTextContent('Sem cargos individuais');
    expect(serverApi.getServerMember).not.toHaveBeenCalled();
    expect(serverApi.getServerAuthorizationContext).toHaveBeenCalledTimes(status === 403 ? 2 : 1);
  });

  it.each(['criação', 'edição', 'atribuição', 'remoção'])('revalida após 403 na %s sem repetir a operação', async operation => {
    const user = userEvent.setup();
    const read = deferred<typeof authorizationContext>();
    const admin = { ...authorizationContext, is_owner: false, highest_role_position: 10,
      has_manage_roles_permission: true, effective_permissions: ['manage_roles', 'mention_everyone'] };
    serverApi.getServer.mockResolvedValue({ ...server, owner_id: 11 });
    serverApi.getServerAuthorizationContext.mockResolvedValueOnce(admin).mockReturnValueOnce(read.promise);
    const write = {
      criação: serverApi.createServerRole, edição: serverApi.updateServerRole,
      atribuição: serverApi.assignServerRoleToMember, remoção: serverApi.removeServerRoleFromMember,
    }[operation]!;
    write.mockRejectedValueOnce(new ApiError('Operação recusada.', 403));
    renderPages('/servidores/12');
    await screen.findByLabelText('Nome do cargo');
    if (operation === 'criação' || operation === 'edição') {
      if (operation === 'edição') await user.click((await screen.findAllByRole('button', { name: 'Editar' }))[0]);
      await user.type(screen.getByLabelText('Nome do cargo'), 'Novo');
      await user.click(screen.getByRole('button', { name: operation === 'criação' ? 'Criar cargo' : 'Salvar alterações' }));
    } else {
      await user.selectOptions(screen.getByLabelText('Membro ativo'), operation === 'remoção' ? '9' : '7');
      await user.selectOptions(screen.getByLabelText('Cargo individual'), '5');
      await user.click(screen.getByRole('button', { name: operation === 'remoção' ? 'Remover' : 'Atribuir' }));
    }
    expect(serverApi.getServerAuthorizationContext.mock.calls).toEqual([[12], [12]]);
    expect(screen.getByRole('alert')).toHaveTextContent('Operação recusada.');
    expect(screen.getByText('Último contexto confirmado')).toBeVisible();
    expect(screen.getByText('Sua maior posição individual: 10.')).toBeVisible();
    expect(screen.queryByLabelText('Nome do cargo')).toBeNull();
    expect(screen.queryByLabelText('Cargo individual')).toBeNull();
    await act(async () => read.resolve({ ...authorizationContext, is_owner: false, effective_permissions: [] }));
    expect(screen.queryByRole('button', { name: 'Editar' })).toBeNull();
    expect(screen.queryByLabelText('Nome do cargo')).toBeNull();
    expect(screen.queryByLabelText('Cargo individual')).toBeNull();
    const gain = deferred<typeof admin>();
    serverApi.getServerAuthorizationContext.mockReturnValueOnce(gain.promise);
    await user.click(screen.getByRole('button', { name: 'Verificar acesso aos convites' }));
    expect(screen.queryByLabelText('Nome do cargo')).toBeNull();
    await act(async () => gain.resolve(admin));
    expect(screen.getByLabelText('Nome do cargo')).toBeEnabled();
    expect(screen.getByLabelText('Cargo individual')).toBeEnabled();
    expect(write).toHaveBeenCalledTimes(1);
    expect(serverApi.getServerMember).not.toHaveBeenCalled();
  });

  it.each(['recente primeiro', 'antiga primeiro'])('ordena releituras de autorização no mesmo servidor: %s', async order => {
    const user = userEvent.setup();
    const older = deferred<typeof authorizationContext>();
    const newer = deferred<typeof authorizationContext>();
    serverApi.getServerAuthorizationContext.mockResolvedValueOnce(authorizationContext)
      .mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise);
    serverApi.getServerMember.mockResolvedValue({ ...members[0], roles: [roles[1]] });
    const everyoneWrite = deferred<{ server_id: number; everyone_permissions: object }>();
    serverApi.updateEveryonePermissions.mockReturnValueOnce(everyoneWrite.promise);
    renderPages('/servidores/12');
    await user.click(await screen.findByRole('button', { name: 'Editar permissões de @everyone' }));
    await user.click(screen.getByRole('button', { name: 'Salvar permissões' }));
    await user.selectOptions(await screen.findByLabelText('Membro ativo'), '7');
    await user.selectOptions(screen.getByLabelText('Cargo individual'), '8');
    await user.click(screen.getByRole('button', { name: 'Atribuir' }));
    expect(serverApi.getServerAuthorizationContext).toHaveBeenCalledTimes(2);
    await act(async () => everyoneWrite.resolve({ server_id: 12, everyone_permissions: {} }));
    expect(serverApi.getServerAuthorizationContext.mock.calls).toEqual([[12], [12], [12]]);
    if (order === 'antiga primeiro') {
      await act(async () => older.reject(new Error('Resposta obsoleta')));
      expect(screen.getByText('Carregando seu contexto de autorização…')).toBeVisible();
      expect(screen.queryByRole('alert')).toBeNull();
    }
    await act(async () => newer.resolve({ ...authorizationContext, is_owner: false, highest_role_position: 2, effective_permissions: [] }));
    if (order === 'recente primeiro') await act(async () => older.resolve(authorizationContext));
    expect(screen.getByText('Sua maior posição individual: 2.')).toBeVisible();
    expect(screen.getByText('Permissões efetivas: nenhuma permissão explícita.')).toBeVisible();
    expect(screen.queryByText('Carregando seu contexto de autorização…')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Atribuir' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Editar permissões de @everyone' })).toBeNull();
  });

  it('descarta contexto inicial de A que chega após o contexto de B', async () => {
    const user = userEvent.setup();
    const first = deferred<typeof authorizationContext>();
    serverApi.getServer.mockImplementation(async id => ({ ...server, id, owner_id: id === 13 ? 9 : 7 }));
    serverApi.getServerAuthorizationContext.mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce({ ...authorizationContext, server_id: 13, is_owner: false, highest_role_position: 3 });
    renderPages('/servidores/12', true);
    expect(await screen.findByText('Carregando seu contexto de autorização…')).toBeVisible();
    await user.click(screen.getByRole('link', { name: 'Abrir servidor B' }));
    expect(await screen.findByText('Sua maior posição individual: 3.')).toBeVisible();
    await act(async () => first.resolve(authorizationContext));
    expect(screen.getByText('Sua maior posição individual: 3.')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Criar cargo' })).toBeNull();
    expect(serverApi.getServerAuthorizationContext.mock.calls).toEqual([[12], [13]]);
  });

  it('preserva a autoatribuição confirmada quando só a atualização do contexto falha', async () => {
    const user = userEvent.setup();
    const context = deferred<typeof authorizationContext>();
    const recovery = deferred<typeof authorizationContext>();
    serverApi.getServerAuthorizationContext.mockResolvedValueOnce(authorizationContext).mockReturnValueOnce(context.promise).mockReturnValueOnce(recovery.promise);
    serverApi.getServerMember.mockResolvedValueOnce({ ...members[0], roles: [roles[1]] });
    renderPages('/servidores/12');
    await user.selectOptions(await screen.findByLabelText('Membro ativo'), '7');
    await user.selectOptions(screen.getByLabelText('Cargo individual'), '8');
    await user.click(screen.getByRole('button', { name: 'Atribuir' }));
    await act(async () => context.reject(new Error('offline')));
    expect(screen.getByText('A atribuição foi confirmada pela API.')).toBeVisible();
    expect(screen.getByLabelText('Cargos de owner')).toHaveTextContent('Moderador');
    expect(screen.getByRole('alert')).toHaveTextContent('Não foi possível atualizar suas permissões.');
    expect(screen.queryByRole('button', { name: 'Atribuir' })).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Atualizar contexto de autorização novamente' }));
    expect(screen.getByText('Último contexto confirmado')).toBeVisible();
    expect(screen.getByText('Permissões efetivas: Gerenciar convites.')).toBeVisible();
    expect(screen.getByText('Carregando seu contexto de autorização…')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Atribuir' })).toBeNull();
    await act(async () => recovery.resolve(authorizationContext));
    expect(serverApi.getServer).toHaveBeenCalledTimes(1);
    expect(serverApi.listServerMembers).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('button', { name: 'Remover' })).toBeEnabled();
    expect(serverApi.getServerAuthorizationContext.mock.calls).toEqual([[12], [12], [12]]);
    expect(serverApi.getServerMember.mock.calls).toEqual([[12, 7]]);
    expect(serverApi.assignServerRoleToMember.mock.calls).toEqual([[12, 7, 8]]);
  });

  it('atribui e remove cargo para membro ativo usando os métodos e caminhos reais', async () => {
    const user = userEvent.setup();
    renderPages('/servidores/12');
    await screen.findByText(/Maior posição cadastrada:/);
    serverApi.getServerMember.mockResolvedValueOnce({ ...members[0], roles: [roles[1]] }).mockResolvedValueOnce(members[0]);
    await user.selectOptions(screen.getByLabelText('Membro ativo'), '7');
    await user.selectOptions(screen.getByLabelText('Cargo individual'), '8');
    await user.click(screen.getByRole('button', { name: 'Atribuir' }));
    expect(serverApi.assignServerRoleToMember).toHaveBeenCalledWith(12, 7, 8);
    expect(await screen.findByText('A atribuição foi confirmada pela API.')).toBeVisible();
    expect(within(screen.getByLabelText('Cargos de owner')).getByText('Moderador · posição 8')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Remover' }));
    expect(serverApi.removeServerRoleFromMember).toHaveBeenCalledWith(12, 7, 8);
  });

  it.each(['manage_roles', 'ban_members'])('permite ao proprietário conceder %s a outro membro sem possuir a permissão', async key => {
    const user = userEvent.setup();
    const target = { ...members[1], roles: [] };
    const role = { ...roles[1], permissions: { [key]: true } };
    serverApi.listServerMembers.mockResolvedValue([target]);
    serverApi.listServerRoles.mockResolvedValue([role]);
    serverApi.getServerMember.mockResolvedValue({ ...target, roles: [role] });
    renderPages('/servidores/12');
    await screen.findByText(/Maior posição cadastrada:/);
    await user.selectOptions(screen.getByLabelText('Membro ativo'), '9');
    await user.selectOptions(screen.getByLabelText('Cargo individual'), '8');
    const assign = screen.getByRole('button', { name: 'Atribuir' });
    expect(assign).toBeEnabled();
    await user.click(assign);
    expect(serverApi.assignServerRoleToMember).toHaveBeenCalledWith(12, 9, 8);
  });

  it('impede o administrador de conceder uma nova permissão que não possui', async () => {
    const user = userEvent.setup();
    serverApi.getServer.mockResolvedValue({ ...server, owner_id: 42 });
    serverApi.getServerAuthorizationContext.mockResolvedValue({
      ...authorizationContext, is_owner: false, highest_role_position: 10,
      effective_permissions: ['manage_roles'], has_manage_roles_permission: true,
    });
    serverApi.listServerMembers.mockResolvedValue([{ ...members[1], roles: [] }]);
    renderPages('/servidores/12');
    await screen.findByText(/Maior posição cadastrada:/);
    await user.selectOptions(screen.getByLabelText('Membro ativo'), '9');
    await user.selectOptions(screen.getByLabelText('Cargo individual'), '8');
    const assign = screen.getByRole('button', { name: 'Atribuir' });
    expect(assign).toBeDisabled();
    await user.click(assign);
    expect(serverApi.assignServerRoleToMember).not.toHaveBeenCalled();
  });

  it('exclui cargos de sistema das opções mesmo para o proprietário', async () => {
    const user = userEvent.setup();
    serverApi.listServerRoles.mockResolvedValue([{ ...roles[0], is_system_role: true }]);
    renderPages('/servidores/12');
    await screen.findByText(/Maior posição cadastrada:/);
    await user.selectOptions(screen.getByLabelText('Membro ativo'), '9');
    expect(within(screen.getByLabelText('Cargo individual')).getAllByRole('option')).toHaveLength(1);
    const assign = screen.getByRole('button', { name: 'Atribuir' });
    expect(assign).toBeDisabled();
    await user.click(assign);
    expect(serverApi.assignServerRoleToMember).not.toHaveBeenCalled();
  });

  it.each([4, 8])('limita o administrador à posição inferior ao nível %i', async level => {
    serverApi.getServer.mockResolvedValue({ ...server, owner_id: 42 });
    serverApi.getServerAuthorizationContext.mockResolvedValue({
      ...authorizationContext, is_owner: false, highest_role_position: level,
      effective_permissions: ['manage_roles'], has_manage_roles_permission: true,
    });
    renderPages('/servidores/12');
    expect(await screen.findByText(/Administrador de cargos/)).toBeVisible();
    expect(screen.getByLabelText('Posição')).toHaveAttribute('max', String(level - 1));
    expect(await screen.findAllByRole('button', { name: 'Editar' })).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Editar' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Excluir Moderador' })).toBeNull();
    expect(within(screen.getByLabelText('Membro ativo')).queryByText(/member · ID/)).toBeNull();
    expect(within(screen.getByLabelText('Cargo individual')).getByText('Membro · posição 1')).toBeVisible();
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText('Cargo individual'), '5');
    const assign = screen.getByRole('button', { name: 'Atribuir' });
    expect(assign).toBeDisabled();
    await user.click(assign);
    expect(serverApi.assignServerRoleToMember).not.toHaveBeenCalled();
  });

  it('permite ao administrador editar, atribuir e remover um cargo inferior de um membro sem cargos', async () => {
    const user = userEvent.setup();
    serverApi.getServer.mockResolvedValue({ ...server, owner_id: 42 });
    serverApi.getServerAuthorizationContext.mockResolvedValue({
      ...authorizationContext, is_owner: false, highest_role_position: 4,
      effective_permissions: ['manage_roles'], has_manage_roles_permission: true,
    });
    const target = { ...members[1], roles: [] };
    serverApi.listServerMembers.mockResolvedValue([target]);
    serverApi.getServerMember.mockResolvedValueOnce({ ...target, roles: [roles[0]] }).mockResolvedValueOnce(target);
    serverApi.updateServerRole.mockResolvedValue(roles[0]);
    renderPages('/servidores/12');
    await user.click(await screen.findByRole('button', { name: 'Editar' }));
    expect(screen.getByLabelText('Banir membros')).toBeDisabled();
    await user.clear(screen.getByLabelText('Posição'));
    await user.type(screen.getByLabelText('Posição'), '4');
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    expect(serverApi.updateServerRole).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText('Posição'));
    await user.type(screen.getByLabelText('Posição'), '2');
    await user.click(screen.getByRole('button', { name: 'Salvar alterações' }));
    expect(serverApi.updateServerRole).toHaveBeenCalledWith(12, 5, { position: 2 });
    await user.selectOptions(screen.getByLabelText('Membro ativo'), '9');
    await user.selectOptions(screen.getByLabelText('Cargo individual'), '5');
    await user.click(screen.getByRole('button', { name: 'Atribuir' }));
    const badges = within(screen.getByLabelText('Cargos de member'));
    expect(await badges.findByText('Membro · posição 1')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Remover' }));
    expect(await badges.findByText('Sem cargos individuais')).toBeVisible();
  });

  it('mantém membros sem manage_roles em consulta', async () => {
    serverApi.getServerAuthorizationContext.mockResolvedValue({ ...authorizationContext, is_owner: false });
    renderPages('/servidores/12');
    expect(await screen.findByText(/Consulta de cargos/)).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Criar cargo' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Atribuir' })).toBeNull();
  });

  it('mostra a configuração confirmada de @everyone e trata 403 ao criar cargo', async () => {
    const user = userEvent.setup();
    serverApi.createServerRole.mockRejectedValue(new ApiError('A API negou a alteração.', 403));
    renderPages('/servidores/12');
    await screen.findByText(/Maior posição cadastrada:/);
    expect(screen.getByText(/estado atual das permissões conhecidas/i)).toBeVisible();
    expect(screen.getByText('Gerenciar convites: Ativa')).toBeVisible();
    expect(screen.getByText('Banir membros: Inativa')).toBeVisible();
    await user.type(screen.getByLabelText('Nome do cargo'), 'Cargo negado');
    await user.click(screen.getByRole('button', { name: 'Criar cargo' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('A API negou a alteração.');
    expect(screen.queryByRole('checkbox', { name: /@everyone/i })).not.toBeInTheDocument();
  });

  it.each([true, false])('permite apenas consultar @everyone quando não proprietário, manage_roles=%s', async manager => {
    serverApi.getServer.mockResolvedValue({ ...server, owner_id: 9 });
    serverApi.getServerAuthorizationContext.mockResolvedValue({
      ...authorizationContext, is_owner: false, has_manage_roles_permission: manager,
    });
    renderPages('/servidores/12');
    const section = within(await screen.findByRole('region', { name: 'Permissões de @everyone' }));
    expect(section.getByText('Gerenciar convites: Ativa')).toBeVisible();
    expect(section.queryByRole('button')).toBeNull();
  });

  it('edita a configuração atual e confirma somente após resposta do PATCH', async () => {
    const user = userEvent.setup();
    let confirm!: () => void;
    serverApi.updateEveryonePermissions.mockReturnValueOnce(new Promise(resolve => {
      confirm = () => resolve({ server_id: 12, everyone_permissions: { ban_members: true, manage_invites: true } });
    }));
    renderPages('/servidores/12');
    await user.click(await screen.findByRole('button', { name: 'Editar permissões de @everyone' }));
    const section = within(screen.getByRole('region', { name: 'Permissões de @everyone' }));
    expect(section.getByLabelText('Gerenciar convites')).toBeChecked();
    await user.click(section.getByLabelText('Banir membros'));
    await user.dblClick(section.getByRole('button', { name: 'Salvar permissões' }));
    expect(section.getByRole('button', { name: 'Salvando…' })).toBeDisabled();
    expect(serverApi.updateEveryonePermissions).toHaveBeenCalledTimes(1);
    expect(section.getByText('Banir membros: Inativa')).toBeVisible();
    await act(async () => confirm());
    expect(await section.findByText('Permissões de @everyone salvas.')).toBeVisible();
    expect(section.getByText('Banir membros: Ativa')).toBeVisible();
    expect(serverApi.getServerAuthorizationContext).toHaveBeenCalledTimes(2);
  });

  it.each([403, 404, 422])('preserva permissões confirmadas após HTTP %i', async status => {
    const user = userEvent.setup();
    serverApi.updateEveryonePermissions.mockRejectedValueOnce(new ApiError('Alteração recusada.', status));
    renderPages('/servidores/12');
    await user.click(await screen.findByRole('button', { name: 'Editar permissões de @everyone' }));
    const section = within(screen.getByRole('region', { name: 'Permissões de @everyone' }));
    await user.click(section.getByLabelText('Gerenciar convites'));
    await user.click(section.getByRole('button', { name: 'Salvar permissões' }));
    expect(await section.findByRole('alert')).toHaveTextContent('Alteração recusada.');
    expect(section.getByText('Gerenciar convites: Ativa')).toBeVisible();
    expect(section.queryByText('Permissões de @everyone salvas.')).toBeNull();
    await user.click(section.getByRole('button', { name: 'Cancelar' }));
    expect(section.queryByRole('checkbox')).toBeNull();
  });

  it('apresenta carregamento e falha do contexto sem esconder os detalhes do servidor', async () => {
    let resolveContext!: (value: typeof authorizationContext) => void;
    serverApi.getServerAuthorizationContext.mockReturnValueOnce(
      new Promise(resolve => { resolveContext = resolve; }),
    );
    renderPages('/servidores/12');
    expect(await screen.findByRole('heading', { name: 'Membros ativos' })).toBeVisible();
    expect(screen.getByText('Carregando seu contexto de autorização…')).toBeVisible();

    await act(async () => resolveContext(authorizationContext));
    expect(await screen.findByText(/proprietário, com autoridade especial/i)).toBeVisible();

    serverApi.getServerAuthorizationContext.mockRejectedValueOnce(new ApiError('Contexto indisponível.', 503));
    cleanup();
    renderPages('/servidores/12');
    expect(await screen.findByText('Contexto indisponível.')).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Membros ativos' })).toBeVisible();
  });

  it('exibe estado vazio e erro ao consultar cargos', async () => {
    serverApi.listServerRoles.mockResolvedValueOnce([]);
    const first = renderPages('/servidores/12');
    expect(await screen.findByText('Nenhum cargo individual configurado')).toBeVisible();
    first.unmount();
    serverApi.listServerRoles.mockRejectedValueOnce(new ApiError('Servidor indisponível.', 404));
    renderPages('/servidores/12');
    expect(await screen.findByRole('alert')).toHaveTextContent('Servidor indisponível.');
  });
});
