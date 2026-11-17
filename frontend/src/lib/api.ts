import axios, { AxiosError } from "axios";
import { tokenStorage } from "@/lib/token-storage";

const baseURL = import.meta.env.VITE_API_BASE_URL;

if (!baseURL) {
  throw new Error(
    "VITE_API_BASE_URL não foi definida. Copie .env.example para .env.local e configure a URL da API.",
  );
}

export const api = axios.create({
  baseURL: baseURL.replace(/\/+$/, ""),
  headers: { "Content-Type": "application/json" },
  timeout: 15_000,
});

export const AUTH_UNAUTHORIZED_EVENT = "safetalk:unauthorized";

api.interceptors.request.use((config) => {
  const token = tokenStorage.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: unknown }>) => {
    const detail = error.response?.data?.detail;
    const validationMessages = Array.isArray(detail)
      ? detail
          .map((item) =>
            typeof item === "object" && item !== null && "msg" in item
              ? String(item.msg)
              : "",
          )
          .filter(Boolean)
      : [];
    const message = typeof detail === "string"
      ? detail
      : validationMessages.length > 0
        ? validationMessages.join(" ")
        : error.response
          ? `A solicitação falhou (${error.response.status}).`
          : "Não foi possível conectar à API. Verifique sua conexão e tente novamente.";

    if (error.response?.status === 401) {
      const hadSessionToken = Boolean(tokenStorage.get());
      tokenStorage.clear();
      if (hadSessionToken && typeof window !== "undefined") {
        window.dispatchEvent(new Event(AUTH_UNAUTHORIZED_EVENT));
      }
    }

    return Promise.reject(
      new ApiError(message, error.response?.status, detail),
    );
  },
);
