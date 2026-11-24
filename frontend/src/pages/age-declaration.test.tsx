/** @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { AgeDeclarationPage } from './age-declaration';
import { RegisterPage } from './register';
import { ApiError } from '@/lib/api';
const mock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), signUp: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: mock, ApiError: class extends Error {} }));
vi.mock('@/context/auth-context', () => ({ useAuth: () => ({ signUp: mock.signUp }) }));
vi.mock('@/components/dashboard-layout', () => ({ DashboardLayout: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock('@/components/auth-shell', () => ({ AuthShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

it('carrega a conta antiga e persiste a declaração apenas após confirmação', async () => {
  mock.get.mockResolvedValue({ data: { birth_date: null } });
  mock.post.mockResolvedValue({ data: { birth_date: '1990-01-01' } });
  render(<AgeDeclarationPage />);
  expect(screen.getByText('Carregando seus dados…')).toBeVisible();
  await screen.findByText('Confirmar declaração');
  expect(screen.getByText(/autodeclarada/)).toBeVisible();
  fireEvent.change(screen.getByLabelText('Data de nascimento'), { target: { value: '1990-01-01' } });
  fireEvent.change(screen.getByLabelText('Senha atual'), { target: { value: 'password' } });
  fireEvent.click(screen.getByText('Confirmar declaração'));
  await screen.findByText(/Data de nascimento declarada/);
  expect(mock.post).toHaveBeenCalledWith('/users/me/birth-date', { birth_date: '1990-01-01', password: 'password' });
  expect(screen.queryByText('1990-01-01')).toBeNull();
});

it('mostra erro de idade sem confirmar gravação', async () => {
  mock.get.mockResolvedValue({ data: { birth_date: null } });
  mock.post.mockRejectedValue(new Error('É necessário ter pelo menos 14 anos.'));
  render(<AgeDeclarationPage />);
  await screen.findByText('Confirmar declaração');
  fireEvent.change(screen.getByLabelText('Data de nascimento'), { target: { value: '2015-01-01' } });
  fireEvent.change(screen.getByLabelText('Senha atual'), { target: { value: 'password' } });
  fireEvent.click(screen.getByText('Confirmar declaração'));
  await screen.findByText(/É necessário ter pelo menos 14 anos/);
  expect(screen.queryByText(/Data de nascimento declarada/)).toBeNull();
});

it('cadastro envia data declarada e apresenta recusa de idade mínima', async () => {
  mock.signUp.mockRejectedValue(new ApiError('É necessário ter pelo menos 14 anos.'));
  render(<MemoryRouter><RegisterPage /></MemoryRouter>);
  expect(screen.getByText(/Você declara sua própria data/)).toBeVisible();
  fireEvent.change(screen.getByLabelText('Nome de usuário'), { target: { value: 'tester' } });
  fireEvent.change(screen.getByLabelText('E-mail'), { target: { value: 'tester@example.test' } });
  fireEvent.change(screen.getByLabelText('Data de nascimento'), { target: { value: '2015-01-01' } });
  fireEvent.change(screen.getByLabelText('Senha'), { target: { value: 'password' } });
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByText('Criar minha conta'));
  await screen.findByText('É necessário ter pelo menos 14 anos.');
  expect(mock.signUp).toHaveBeenCalledWith(expect.objectContaining({ birth_date: '2015-01-01' }));
});
