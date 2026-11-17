import { afterEach, describe, expect, it, vi } from "vitest";
import { getTokenExpirationMs } from "@/lib/token-storage";

describe("expiração do JWT", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lê exp somente para agendar o fim local da sessão", () => {
    vi.stubGlobal("window", { atob });
    const expiration = Math.floor(Date.now() / 1000) + 60;
    const payload = btoa(JSON.stringify({ exp: expiration }))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");

    expect(getTokenExpirationMs(`header.${payload}.signature`)).toBe(expiration * 1000);
  });

  it("rejeita tokens sem exp ou com payload inválido", () => {
    vi.stubGlobal("window", { atob });
    expect(getTokenExpirationMs("not-a-jwt")).toBeNull();
    expect(getTokenExpirationMs("header.e30.signature")).toBeNull();
  });
});
