import { api } from "@/lib/api";

export type UserCreatePayload = {
  username: string;
  email: string;
  password: string;
  birth_date: string;
};

export type UserResponse = {
  id: number;
  username: string;
  email: string;
  birth_date: string | null;
  is_active: boolean;
  is_verified: boolean;
};

export type LoginPayload = {
  login: string;
  password: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: "bearer" | string;
};

export async function registerUser(
  payload: UserCreatePayload,
): Promise<UserResponse> {
  const response = await api.post<UserResponse>("/users/", payload);
  return response.data;
}

export async function loginUser(payload: LoginPayload): Promise<TokenResponse | { two_factor_required: true; challenge: string; expires_in: number }> {
  const response = await api.post<TokenResponse | { two_factor_required: true; challenge: string; expires_in: number }>("/users/login", payload);
  return response.data;
}

export async function getCurrentUser(): Promise<UserResponse> {
  const response = await api.get<UserResponse>("/users/me");
  return response.data;
}


export async function completeTwoFactor(challenge: string, code: string, recovery: boolean) {
  return (await api.post<TokenResponse>("/users/login/2fa", { challenge, code, recovery })).data;
}
