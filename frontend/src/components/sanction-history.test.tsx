/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { ApiError } from '@/lib/api';
import { SanctionHistory } from './sanction-history';
import { listOfficialSanctions, reviewOfficialSanction, type ModerationSanction } from '@/services/official-moderation-api';

vi.mock('@/services/official-moderation-api', () => ({
  listOfficialSanctions: vi.fn(), reviewOfficialSanction: vi.fn(),
}));
const list = vi.mocked(listOfficialSanctions);
const review = vi.mocked(reviewOfficialSanction);
const item: ModerationSanction = {
  id: 81, target_user_id: 61, report_id: 71, actor_user_id: 31, sanction_type: 'PERMANENT_BAN',
  issued_at: '2026-10-01T12:00:00Z', expires_at: null, reason: 'Decisão de exemplo',
  basis_warning_ids: [41, 42, 43], requires_review: true, review_history: [],
  reversed_at: null, reversed_by: null, reversal_reason: null,
};
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.resetAllMocks(); });

it('carrega o histórico do autor e identifica a lista vazia', async () => {
  list.mockResolvedValue({ items: [], total: 0 });
  render(<SanctionHistory targetId={61} />);
  expect(screen.getByText('Carregando sanções…')).toBeInTheDocument();
  expect(await screen.findByText('Nenhuma sanção nesta página.')).toBeInTheDocument();
  expect(list).toHaveBeenCalledWith(61, 1, expect.any(AbortSignal));
});

it.each([[403, /Sem permissão/], [500, /Serviço indisponível/]] as const)('trata erro %s sem oferecer ações', async (status, message) => {
  list.mockRejectedValue(new ApiError('Serviço indisponível', status));
  render(<SanctionHistory targetId={61} />);
  expect(await screen.findByRole('alert')).toHaveTextContent(message);
  expect(screen.queryByText(/Reverter sanção/)).toBeNull();
});

it.each([['REVERSE', 'Reverter', 'reversão'], ['UPHOLD', 'Manter', 'manutenção']] as const)(
  'exige justificativa e confirmação para %s e recarrega a situação', async (decision, verb, noun) => {
    list.mockResolvedValueOnce({ items: [item], total: 1 });
    const updated = { ...item, requires_review: false, reversed_at: decision === 'REVERSE' ? item.issued_at : null };
    list.mockResolvedValue({ items: [updated], total: 1 });
    review.mockResolvedValue(updated);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    render(<SanctionHistory targetId={61} />);
    fireEvent.click(await screen.findByText(verb + ' sanção #81'));
    expect(screen.getByText(/#41, #42, #43/)).toBeInTheDocument();
    const submit = screen.getByText('Confirmar ' + noun);
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Justificativa da revisão'), { target: { value: '  Motivo verificado  ' } });
    fireEvent.click(submit);
    expect(confirm).toHaveBeenCalled();
    expect(review).not.toHaveBeenCalled();
    fireEvent.click(submit);
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
    expect(review).toHaveBeenCalledWith(81, decision, 'Motivo verificado');
    expect(await screen.findByText(decision === 'REVERSE' ? 'Revertida' : 'Vigente')).toBeInTheDocument();
    expect(screen.queryByText(/Aguardando revisão/)).toBeNull();
  },
);

it('identifica suspensão expirada e esconde ações de sanções revertidas', async () => {
  list.mockResolvedValue({ items: [
    { ...item, sanction_type: 'TEMPORARY_SUSPENSION', expires_at: '2020-01-01T00:00:00Z', requires_review: false },
    { ...item, id: 82, reversed_at: item.issued_at, requires_review: false },
  ], total: 2 });
  render(<SanctionHistory targetId={61} />);
  expect(await screen.findByText('Expirada')).toBeInTheDocument();
  expect(screen.getByText('Revertida')).toBeInTheDocument();
  expect(screen.queryByText('Reverter sanção #82')).toBeNull();
});

it('remove o histórico se a revisão perde autorização', async () => {
  list.mockResolvedValue({ items: [item], total: 1 });
  review.mockRejectedValue(new ApiError('Acesso negado', 403));
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<SanctionHistory targetId={61} />);
  fireEvent.click(await screen.findByText('Reverter sanção #81'));
  fireEvent.change(screen.getByLabelText('Justificativa da revisão'), { target: { value: 'Reavaliação' } });
  fireEvent.click(screen.getByText('Confirmar reversão'));
  expect(await screen.findByRole('alert')).toHaveTextContent(/Sem permissão/);
  expect(screen.queryByText(item.reason)).toBeNull();
});
