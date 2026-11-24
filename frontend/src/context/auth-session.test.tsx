/** @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from './auth-context';
import { tokenStorage } from '@/lib/token-storage';

vi.mock('@/services/auth-api', () => ({
  getCurrentUser: vi.fn(async () => ({ id: 1, username: 'fixture', is_active: true })),
  loginUser: vi.fn(), registerUser: vi.fn(), completeTwoFactor: vi.fn(),
}));
function Profile() { const { user } = useAuth(); return <p>{user ? 'Sessão ativa' : 'Sem sessão'}</p>; }
const token = (expiry: number) => 'header.' + btoa(JSON.stringify({ exp: expiry })) + '.fixture';
afterEach(() => { cleanup(); tokenStorage.clear(); vi.useRealTimers(); });

it('renovação do JWT pelo 2FA reagenda a expiração visual', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-11-24T12:00:00Z'));
  const seconds = Date.now() / 1000;
  tokenStorage.set(token(seconds + 60));
  await act(async () => { render(<AuthProvider><Profile /></AuthProvider>); });
  expect(screen.getByText('Sessão ativa')).toBeVisible();
  await act(async () => {
    vi.advanceTimersByTime(30000);
    tokenStorage.set(token(seconds + 120));
  });
  await act(async () => { vi.advanceTimersByTime(30000); });
  expect(screen.getByText('Sessão ativa')).toBeVisible();
  expect(tokenStorage.get()).not.toBeNull();
  await act(async () => { vi.advanceTimersByTime(60000); });
  expect(screen.getByText('Sem sessão')).toBeVisible();
  expect(tokenStorage.get()).toBeNull();
});
