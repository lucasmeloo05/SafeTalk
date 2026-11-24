/** @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { TwoFactorPage } from './two-factor';
import { ApiError } from '@/lib/api';
import { LoginPage } from './login';
import { MemoryRouter } from 'react-router-dom';
const mock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), signIn: vi.fn(), verifySecondFactor: vi.fn(), set: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: mock, ApiError: class extends Error {} }));
vi.mock('@/lib/token-storage', () => ({ tokenStorage: { set: mock.set } }));
vi.mock('@/context/auth-context', () => ({ useAuth: () => ({ signIn: mock.signIn, verifySecondFactor: mock.verifySecondFactor }) }));
vi.mock('@/components/dashboard-layout', () => ({ DashboardLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock('@/components/auth-shell', () => ({ AuthShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
beforeEach(() => { vi.resetAllMocks(); mock.get.mockResolvedValue({ data: { enabled: false } }); vi.spyOn(window, 'confirm').mockReturnValue(true); });
afterEach(cleanup);

it('configura, confirma e mostra códigos uma única vez sem persistir o segredo', async () => {
  mock.post.mockResolvedValueOnce({ data: { manual_key: 'MANUAL', qr_svg: '<svg/>' } })
    .mockResolvedValueOnce({ data: { recovery_codes: ['RECOVERY'], access_token: 'access' } });
  render(<TwoFactorPage />);
  await screen.findByText('2FA desativado');
  fireEvent.change(screen.getByLabelText('Senha atual'), { target: { value: 'password' } });
  fireEvent.click(screen.getByText('Configurar 2FA'));
  await screen.findByText('MANUAL');
  expect(screen.getByAltText('QR Code para configurar o autenticador')).toBeVisible();
  fireEvent.change(screen.getByLabelText('Código'), { target: { value: '123456' } });
  fireEvent.click(screen.getByText('Confirmar ativação'));
  await screen.findByText('RECOVERY');
  expect(mock.set).toHaveBeenCalledWith('access');
  expect(screen.queryByText('MANUAL')).toBeNull();
  fireEvent.click(screen.getByText('Já guardei os códigos'));
  expect(screen.queryByText('RECOVERY')).toBeNull();
});

it('exige prova forte para regenerar e permite desativação confirmada', async () => {
  mock.get.mockResolvedValue({ data: { enabled: true } });
  mock.post.mockRejectedValueOnce(new Error('Código inválido')).mockResolvedValueOnce({ data: { enabled: false } });
  render(<TwoFactorPage />);
  await screen.findByText('2FA ativo');
  fireEvent.change(screen.getByLabelText('Senha atual'), { target: { value: 'password' } });
  fireEvent.change(screen.getByLabelText('Código'), { target: { value: 'RECOVERY' } });
  fireEvent.click(screen.getByLabelText('Utilizar código de recuperação'));
  fireEvent.click(screen.getByText('Regenerar códigos'));
  await screen.findByText('Código inválido');
  expect(screen.getByText('2FA ativo')).toBeVisible();
  fireEvent.click(screen.getByText('Desativar 2FA'));
  await screen.findByText('2FA desativado');
  expect(mock.post).toHaveBeenLastCalledWith('/users/me/2fa/disable', { password: 'password', code: 'RECOVERY', recovery: true });
});

it('mantém login parcial na etapa de desafio e mostra expiração sem autenticar', async () => {
  mock.signIn.mockResolvedValue('challenge');
  mock.verifySecondFactor.mockRejectedValue(new ApiError('Desafio expirado'));
  render(<MemoryRouter><LoginPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('Usuário ou e-mail'), { target: { value: 'tester' } });
  fireEvent.change(screen.getByLabelText('Senha'), { target: { value: 'password' } });
  fireEvent.click(screen.getByRole('button', { name: /Entrar no SafeTalk/ }));
  await screen.findByText('O desafio expira em cinco minutos.');
  expect(mock.set).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText('Usar código de recuperação'));
  fireEvent.change(screen.getByLabelText('Código de recuperação'), { target: { value: 'RECOVERY' } });
  fireEvent.click(screen.getByRole('button', { name: /Entrar no SafeTalk/ }));
  await screen.findByText('Desafio expirado');
  expect(mock.verifySecondFactor).toHaveBeenCalledWith('challenge', 'RECOVERY', true);
  fireEvent.click(screen.getByText('Reiniciar login'));
  expect(screen.getByLabelText('Usuário ou e-mail')).toBeVisible();
});
