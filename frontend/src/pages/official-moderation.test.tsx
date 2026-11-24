/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';
import { ApiError } from '@/lib/api';

const { authMock, serviceMock } = vi.hoisted(() => ({
  authMock: vi.fn(),
  serviceMock: {
    listOfficialReports: vi.fn(),
    listOfficialSanctions: vi.fn(),
    getOfficialReport: vi.fn(),
    getOfficialAnalysis: vi.fn(),
    submitOfficialTriage: vi.fn(),
    submitOfficialDecision: vi.fn(),
  },
}));

vi.mock('@/context/auth-context', () => ({ useAuth: authMock }));
vi.mock('@/services/official-moderation-api', () => serviceMock);

import { OfficialModerationPage } from '@/pages/official-moderation';

const user = {
  id: 9,
  username: 'moderadora_teste',
  email: 'moderadora@example.test',
  birth_date: null,
  is_active: true,
  is_verified: true,
};

const analysis = {
  status: 'PENDING_TRIAGE',
  attempt_count: 0,
  model: null,
  flagged: null,
  categories: null,
  category_scores: null,
  category_applied_input_types: null,
  provider_response_id: null,
  analyzed_at: null,
  last_error_code: null,
  updated_at: '2026-11-16T10:00:00Z',
};

const queue = {
  items: [{
    id: 76,
    message_id: 840,
    reason: 'Teste de revisão',
    status: 'PENDING',
    triage_status: 'PENDING',
    analysis,
    created_at: '2026-11-16T10:00:00Z',
  }],
  page: 1,
  page_size: 20,
  total: 1,
};

const detail = {
  id: 76,
  message_id: 840,
  reporter_id: 31,
  reason: 'Teste de revisão',
  status: 'PENDING',
  triage_status: 'PENDING',
  created_at: '2026-11-16T10:00:00Z',
  updated_at: '2026-11-16T10:00:00Z',
  evidence: {
    message_id: 840,
    message_author_id: 42,
    content_snapshot: 'Texto fictício e inofensivo para o teste.',
    message_created_at: '2026-11-16T09:55:00Z',
    message_updated_at: '2026-11-16T09:55:00Z',
    message_edited_at: null,
    captured_at: '2026-11-16T10:00:00Z',
  },
  analysis,
  actions: [{
    id: 17,
    actor_user_id: 9,
    action_type: 'TRIAGE_PENDING',
    reason: 'Aguardando revisão.',
    created_at: '2026-11-16T10:00:00Z',
  }],
};

const detailB = {
  ...detail,
  id: 77,
  message_id: 841,
  reason: 'Outro teste de revisão',
  evidence: {
    ...detail.evidence,
    message_id: 841,
    content_snapshot: 'Snapshot exclusivo da denúncia B.',
  },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/moderacao']}>
      <OfficialModerationPage />
    </MemoryRouter>,
  );
}

describe('painel oficial de moderação', () => {
  afterEach(() => cleanup());

  beforeEach(() => {
    vi.resetAllMocks();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    serviceMock.listOfficialSanctions.mockResolvedValue({ items: [], total: 0 });
    authMock.mockReturnValue({ user, signOut: vi.fn() });
    serviceMock.listOfficialReports.mockResolvedValue(queue);
    serviceMock.getOfficialReport.mockResolvedValue(detail);
    serviceMock.getOfficialAnalysis.mockResolvedValue(analysis);
    serviceMock.submitOfficialTriage.mockResolvedValue(analysis);
    serviceMock.submitOfficialDecision.mockResolvedValue({ id: 19, report_id: 76 });
  });

  it('exibe a fila, evidência, resultado disponível e histórico retornados pela API', async () => {
    renderPage();

    expect(await screen.findByRole('button', { name: /Denúncia #76/ })).toBeInTheDocument();
    expect(await screen.findByText('Texto fictício e inofensivo para o teste.')).toBeInTheDocument();
    expect(screen.getByText('Usuário #31')).toBeInTheDocument();
    expect(screen.getByText('Usuário #42')).toBeInTheDocument();
    expect(screen.getByText('Aguardando revisão.')).toBeInTheDocument();
    expect(serviceMock.listOfficialReports).toHaveBeenCalledWith(1, 20);
    expect(serviceMock.getOfficialReport).toHaveBeenCalledWith(76);
    expect(serviceMock.getOfficialAnalysis).toHaveBeenCalledWith(76);
  });

  it('identifica o servidor e o canal de origem da evidência', async () => {
    serviceMock.getOfficialReport.mockResolvedValue({ ...detail, evidence: { ...detail.evidence, server_id: 12, channel_id: 3 } });
    renderPage();
    expect(await screen.findByText('Servidor #12 · Canal #3')).toBeVisible();
  });

  it('mostra uma mensagem restrita quando o backend responde 403 sem exibir detalhes', async () => {
    serviceMock.listOfficialReports.mockRejectedValue(new ApiError('Forbidden', 403));
    renderPage();

    expect(await screen.findByText('Acesso restrito à equipe oficial ativa da plataforma.')).toBeInTheDocument();
    expect(screen.queryByText('Texto fictício e inofensivo para o teste.')).not.toBeInTheDocument();
    expect(serviceMock.getOfficialReport).not.toHaveBeenCalled();
  });

  it('envia a triagem aprovada com justificativa somente após confirmação explícita', async () => {
    const userEventInstance = userEvent.setup();
    renderPage();
    await screen.findByText('Texto fictício e inofensivo para o teste.');

    await userEventInstance.click(screen.getByRole('button', { name: 'Autorizar análise externa' }));
    await userEventInstance.type(screen.getByLabelText(/Justificativa da triagem/), 'Conteúdo elegível após revisão humana.');
    const submit = screen.getByRole('button', { name: 'Registrar triagem' });
    expect(submit).toBeDisabled();
    await userEventInstance.click(screen.getByRole('checkbox', { name: /Confirmo que o snapshot/ }));
    await userEventInstance.click(submit);

    await waitFor(() => expect(serviceMock.submitOfficialTriage).toHaveBeenCalledWith(76, {
      external_analysis_eligible: true,
      sensitive_content_suspected: false,
      reason: 'Conteúdo elegível após revisão humana.',
    }));
  });

  it('envia triagem manual e decisão humana com os contratos do backend', async () => {
    const userEventInstance = userEvent.setup();
    renderPage();
    await screen.findByText('Texto fictício e inofensivo para o teste.');

    await userEventInstance.click(screen.getByRole('button', { name: 'Manter para análise manual' }));
    await userEventInstance.type(screen.getByLabelText(/Justificativa da triagem/), 'Revisão manual necessária.');
    await userEventInstance.click(screen.getByRole('button', { name: 'Registrar triagem' }));
    await waitFor(() => expect(serviceMock.submitOfficialTriage).toHaveBeenCalledWith(76, {
      external_analysis_eligible: false,
      sensitive_content_suspected: false,
      reason: 'Revisão manual necessária.',
    }));

    await userEventInstance.selectOptions(screen.getByLabelText(/^Decisão/), 'NO_VIOLATION');
    await userEventInstance.type(screen.getByLabelText(/obrigatória · até 1\.000 caracteres/), 'Revisão humana concluída.');
    await userEventInstance.click(screen.getByRole('button', { name: 'Registrar decisão' }));
    await waitFor(() => expect(serviceMock.submitOfficialDecision).toHaveBeenCalledWith(76, {
      decision: 'NO_VIOLATION',
      reason: 'Revisão humana concluída.',
    }));
    expect(screen.getByText(/segunda gera suspensão por 7 dias/)).toBeInTheDocument();
  });

  it('mostra o estado de fila vazia', async () => {
    serviceMock.listOfficialReports.mockResolvedValueOnce({ ...queue, items: [], total: 0 });
    renderPage();
    expect(await screen.findByText('Fila vazia')).toBeInTheDocument();
    expect(screen.getByText('Nenhuma denúncia disponível')).toBeInTheDocument();
  });

  it('pagina a fila com os limites da API', async () => {
    const userEventInstance = userEvent.setup();
    serviceMock.listOfficialReports.mockResolvedValue({ ...queue, total: 21 });
    renderPage();
    expect(await screen.findByText('Página 1 de 2')).toBeInTheDocument();
    await userEventInstance.click(screen.getByRole('button', { name: 'Próxima página' }));
    await waitFor(() => expect(serviceMock.listOfficialReports).toHaveBeenLastCalledWith(2, 20));
  });

  it('ignora detalhes obsoletos quando B responde antes de A e mantém triagem e decisão em B', async () => {
    const userEventInstance = userEvent.setup();
    const reportA = deferred<typeof detail>();
    const reportB = deferred<typeof detailB>();
    const analysisA = deferred<typeof analysis>();
    const analysisB = deferred<typeof analysis>();
    const queueWithTwoReports = {
      ...queue,
      items: [queue.items[0], { ...queue.items[0], id: 77, message_id: 841 }],
      total: 2,
    };
    const reportCalls = new Map<number, number>();
    const analysisCalls = new Map<number, number>();

    serviceMock.listOfficialReports.mockResolvedValue(queueWithTwoReports);
    serviceMock.getOfficialReport.mockImplementation((reportId: number) => {
      const call = (reportCalls.get(reportId) ?? 0) + 1;
      reportCalls.set(reportId, call);
      if (call > 1) return Promise.resolve(reportId === 77 ? detailB : detail);
      return reportId === 77 ? reportB.promise : reportA.promise;
    });
    serviceMock.getOfficialAnalysis.mockImplementation((reportId: number) => {
      const call = (analysisCalls.get(reportId) ?? 0) + 1;
      analysisCalls.set(reportId, call);
      if (call > 1) return Promise.resolve(analysis);
      return reportId === 77 ? analysisB.promise : analysisA.promise;
    });

    renderPage();
    await waitFor(() => expect(serviceMock.getOfficialReport).toHaveBeenCalledWith(76));
    await userEventInstance.click(await screen.findByRole('button', { name: /Denúncia #77/ }));
    await waitFor(() => expect(serviceMock.getOfficialReport).toHaveBeenCalledWith(77));

    reportB.resolve(detailB);
    analysisB.resolve(analysis);
    expect(await screen.findByText('Snapshot exclusivo da denúncia B.')).toBeInTheDocument();

    reportA.resolve(detail);
    analysisA.resolve(analysis);
    await waitFor(() => {
      expect(screen.getByText('Snapshot exclusivo da denúncia B.')).toBeInTheDocument();
      expect(screen.queryByText('Texto fictício e inofensivo para o teste.')).not.toBeInTheDocument();
    });

    await userEventInstance.click(screen.getByRole('button', { name: 'Manter para análise manual' }));
    await userEventInstance.type(screen.getByLabelText(/Justificativa da triagem/), 'Revisão manual da denúncia B.');
    await userEventInstance.click(screen.getByRole('button', { name: 'Registrar triagem' }));
    await waitFor(() => expect(serviceMock.submitOfficialTriage).toHaveBeenCalledWith(77, {
      external_analysis_eligible: false,
      sensitive_content_suspected: false,
      reason: 'Revisão manual da denúncia B.',
    }));

    await userEventInstance.selectOptions(screen.getByLabelText(/^Decisão/), 'REVIEWED_MANUALLY');
    await userEventInstance.type(screen.getByLabelText(/obrigatória · até 1\.000 caracteres/), 'Decisão referente à denúncia B.');
    await userEventInstance.click(screen.getByRole('button', { name: 'Registrar decisão' }));
    await waitFor(() => expect(serviceMock.submitOfficialDecision).toHaveBeenCalledWith(77, {
      decision: 'REVIEWED_MANUALLY',
      reason: 'Decisão referente à denúncia B.',
    }));
    expect(serviceMock.submitOfficialTriage).not.toHaveBeenCalledWith(76, expect.anything());
    expect(serviceMock.submitOfficialDecision).not.toHaveBeenCalledWith(76, expect.anything());
  });

  it('marca suspeita sensível, bloqueia escolha externa e envia a justificativa obrigatória', async () => {
    const userEventInstance = userEvent.setup();
    renderPage();
    await screen.findByText('Texto fictício e inofensivo para o teste.');

    await userEventInstance.click(screen.getByRole('checkbox', {
      name: /Há suspeita de conteúdo de exploração sexual infantil/,
    }));
    expect(screen.getByRole('button', { name: 'Autorizar análise externa' })).toBeDisabled();
    expect(screen.getByText(/suspeita ficará registrada na auditoria/i)).toBeInTheDocument();
    await userEventInstance.type(screen.getByLabelText(/Justificativa da triagem/), 'Encaminhar para análise humana especializada.');
    await userEventInstance.click(screen.getByRole('button', { name: 'Registrar triagem' }));

    await waitFor(() => expect(serviceMock.submitOfficialTriage).toHaveBeenCalledWith(76, {
      external_analysis_eligible: false,
      sensitive_content_suspected: true,
      reason: 'Encaminhar para análise humana especializada.',
    }));
  });
});
