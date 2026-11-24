const TOKEN_KEY = "safetalk.access_token";
export const TOKEN_UPDATED_EVENT = "safetalk:token-updated";

/**
 * Decodifica apenas o campo exp para agendar o encerramento visual da sessão.
 * A validade/autorização do token continua sendo responsabilidade do backend.
 */
export function getTokenExpirationMs(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = JSON.parse(window.atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "="))) as {
      exp?: unknown;
    };
    return typeof decoded.exp === "number" ? decoded.exp * 1000 : null;
  } catch {
    return null;
  }
}

export const tokenStorage = {
  get(): string | null {
    return window.sessionStorage.getItem(TOKEN_KEY);
  },
  set(token: string): void {
    const previous = window.sessionStorage.getItem(TOKEN_KEY);
    window.sessionStorage.setItem(TOKEN_KEY, token);
    if (previous && previous !== token) window.dispatchEvent(new Event(TOKEN_UPDATED_EVENT));
  },
  clear(): void {
    window.sessionStorage.removeItem(TOKEN_KEY);
  },
};
