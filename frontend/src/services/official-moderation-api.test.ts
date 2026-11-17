import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiMock } = vi.hoisted(() => ({
  apiMock: { get: vi.fn(), post: vi.fn() },
}));

vi.mock('@/lib/api', () => ({ api: apiMock }));

import {
  getOfficialAnalysis,
  getOfficialReport,
  listOfficialReports,
  submitOfficialDecision,
  submitOfficialTriage,
} from '@/services/official-moderation-api';

describe('serviços da API oficial de moderação', () => {
  beforeEach(() => vi.resetAllMocks());

  it('lista denúncias com paginação page/page_size', async () => {
    const page = { items: [], page: 2, page_size: 20, total: 21 };
    apiMock.get.mockResolvedValue({ data: page });

    await expect(listOfficialReports(2, 20)).resolves.toEqual(page);
    expect(apiMock.get).toHaveBeenCalledWith('/official/reports', {
      params: { page: 2, page_size: 20 },
    });
  });

  it('consulta detalhe e resultado da análise nos caminhos oficiais', async () => {
    const detail = { id: 76, evidence: { message_id: 8 }, actions: [] };
    const analysis = { status: 'COMPLETED', model: 'omni-moderation-latest' };
    apiMock.get.mockResolvedValueOnce({ data: detail }).mockResolvedValueOnce({ data: analysis });

    await expect(getOfficialReport(76)).resolves.toEqual(detail);
    await expect(getOfficialAnalysis(76)).resolves.toEqual(analysis);
    expect(apiMock.get).toHaveBeenNthCalledWith(1, '/official/reports/76');
    expect(apiMock.get).toHaveBeenNthCalledWith(2, '/official/reports/76/analysis');
  });

  it('envia o contrato booleano da triagem com justificativa', async () => {
    const payload = {
      external_analysis_eligible: false,
      sensitive_content_suspected: false,
      reason: 'Encaminhar para revisão manual.',
    };
    const result = { status: 'MANUAL_REVIEW', attempt_count: 0 };
    apiMock.post.mockResolvedValue({ data: result });

    await expect(submitOfficialTriage(76, payload)).resolves.toEqual(result);
    expect(apiMock.post).toHaveBeenCalledWith('/official/reports/76/triage', payload);
  });

  it('envia decisão humana livre e justificativa sem inferir punição', async () => {
    const payload = { decision: 'Revisada', reason: 'A evidência foi analisada pela equipe.' };
    const result = { id: 5, report_id: 76, actor_user_id: 3, ...payload, created_at: '2026-11-16T10:00:00Z' };
    apiMock.post.mockResolvedValue({ data: result });

    await expect(submitOfficialDecision(76, payload)).resolves.toEqual(result);
    expect(apiMock.post).toHaveBeenCalledWith('/official/reports/76/decision', payload);
  });
});
