import { beforeEach, describe, expect, it, vi } from "vitest";

const { apiMock } = vi.hoisted(() => ({
  apiMock: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));

import {
  getCurrentUser,
  loginUser,
  registerUser,
  type UserCreatePayload,
} from "@/services/auth-api";

describe("API de autenticação", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("envia o contrato real de cadastro para POST /users/", async () => {
    const payload: UserCreatePayload = {
      username: "marina_costa",
      email: "marina@example.test",
      password: "senha-segura-123",
      birth_date: "1998-04-12",
    };
    const user = {
      id: 7,
      username: payload.username,
      email: payload.email,
      birth_date: payload.birth_date,
      is_active: true,
      is_verified: false,
    };
    apiMock.post.mockResolvedValue({ data: user });

    await expect(registerUser(payload)).resolves.toEqual(user);
    expect(apiMock.post).toHaveBeenCalledWith("/users/", payload);
  });

  it("envia username ou e-mail e senha para POST /users/login", async () => {
    const credentials = { login: "marina@example.test", password: "senha-segura-123" };
    const token = { access_token: "jwt-example", token_type: "bearer" };
    apiMock.post.mockResolvedValue({ data: token });

    await expect(loginUser(credentials)).resolves.toEqual(token);
    expect(apiMock.post).toHaveBeenCalledWith("/users/login", credentials);
  });

  it("consulta o perfil autenticado em GET /users/me", async () => {
    const user = {
      id: 7,
      username: "marina_costa",
      email: "marina@example.test",
      birth_date: "1998-04-12",
      is_active: true,
      is_verified: false,
    };
    apiMock.get.mockResolvedValue({ data: user });

    await expect(getCurrentUser()).resolves.toEqual(user);
    expect(apiMock.get).toHaveBeenCalledWith("/users/me");
  });
});
