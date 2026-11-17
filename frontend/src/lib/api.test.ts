import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AxiosError, AxiosHeaders, type AxiosAdapter } from "axios";
import { api, ApiError, AUTH_UNAUTHORIZED_EVENT } from "@/lib/api";
import { tokenStorage } from "@/lib/token-storage";

describe("interceptor de autenticação HTTP", () => {
  const values = new Map<string, string>();
  const dispatchEvent = vi.fn();
  const adapter: AxiosAdapter = async (config) => {
    throw new AxiosError(
      "Unauthorized",
      "ERR_BAD_REQUEST",
      config,
      {},
      {
        config,
        data: { detail: "Token inválido ou expirado." },
        headers: new AxiosHeaders(),
        status: 401,
        statusText: "Unauthorized",
      },
    );
  };

  beforeEach(() => {
    values.clear();
    dispatchEvent.mockClear();
    vi.stubGlobal("window", {
      atob,
      dispatchEvent,
      sessionStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key),
      },
    });
    api.defaults.adapter = adapter;
  });

  afterEach(() => {
    tokenStorage.clear();
    vi.unstubAllGlobals();
  });

  it("limpa a sessão e notifica a aplicação quando a API rejeita o JWT", async () => {
    tokenStorage.set("expired-token");

    await expect(api.get("/users/me")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      message: "Token inválido ou expirado.",
    } satisfies Partial<ApiError>);

    expect(tokenStorage.get()).toBeNull();
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    expect(dispatchEvent.mock.calls[0][0]).toBeInstanceOf(Event);
    expect((dispatchEvent.mock.calls[0][0] as Event).type).toBe(AUTH_UNAUTHORIZED_EVENT);
  });

  it("não anuncia expiração de sessão ao rejeitar login sem token existente", async () => {
    await expect(api.post("/users/login", { login: "user", password: "bad" }))
      .rejects.toBeInstanceOf(ApiError);

    expect(dispatchEvent).not.toHaveBeenCalled();
  });
});
