import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { ApiError, AUTH_UNAUTHORIZED_EVENT } from "@/lib/api";
import { getTokenExpirationMs, tokenStorage } from "@/lib/token-storage";
import {
  getCurrentUser,
  loginUser,
  registerUser,
  type UserCreatePayload,
  type UserResponse,
} from "@/services/auth-api";

type AuthContextValue = {
  user: UserResponse | null;
  isLoading: boolean;
  sessionNotice: string | null;
  signIn: (login: string, password: string) => Promise<void>;
  signUp: (payload: UserCreatePayload) => Promise<UserResponse>;
  signOut: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [sessionNotice, setSessionNotice] = useState<string | null>(null);

  const signOut = useCallback(() => {
    tokenStorage.clear();
    setUser(null);
    setSessionNotice(null);
  }, []);

  useEffect(() => {
    let active = true;
    const onUnauthorized = () => {
      tokenStorage.clear();
      setUser(null);
      setIsLoading(false);
      setSessionNotice("Sua sessão expirou ou não é mais válida. Entre novamente.");
    };

    window.addEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);

    const storedToken = tokenStorage.get();
    if (!storedToken) {
      setIsLoading(false);
      return () => {
        active = false;
        window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
      };
    }

    const expiresAt = getTokenExpirationMs(storedToken);
    if (!expiresAt || expiresAt <= Date.now()) {
      tokenStorage.clear();
      setSessionNotice("Sua sessão expirou ou não é mais válida. Entre novamente.");
      setIsLoading(false);
      return () => {
        active = false;
        window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
      };
    }

    getCurrentUser()
      .then((profile) => {
        if (active) {
          setUser(profile);
          setSessionNotice(null);
        }
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.status === 401) {
          tokenStorage.clear();
          setUser(null);
          setSessionNotice("Sua sessão expirou ou não é mais válida. Entre novamente.");
        } else {
          setUser(null);
          setSessionNotice("Não foi possível validar sua sessão. Entre novamente quando a API estiver disponível.");
        }
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });

    return () => {
      active = false;
      window.removeEventListener(AUTH_UNAUTHORIZED_EVENT, onUnauthorized);
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    const token = tokenStorage.get();
    const expiresAt = token ? getTokenExpirationMs(token) : null;
    if (!expiresAt) {
      tokenStorage.clear();
      setUser(null);
      setSessionNotice("Sua sessão expirou ou não é mais válida. Entre novamente.");
      return;
    }

    const timeout = window.setTimeout(() => {
      tokenStorage.clear();
      setUser(null);
      setSessionNotice("Sua sessão expirou. Entre novamente.");
    }, Math.max(0, expiresAt - Date.now()));
    return () => window.clearTimeout(timeout);
  }, [user]);

  const signIn = useCallback(async (login: string, password: string) => {
    const token = await loginUser({ login, password });
    if (!token.access_token || token.token_type.toLowerCase() !== "bearer") {
      throw new ApiError("A API retornou uma resposta de autenticação inválida.");
    }
    const expiresAt = getTokenExpirationMs(token.access_token);
    if (!expiresAt || expiresAt <= Date.now()) {
      throw new ApiError("A API retornou um token inválido ou expirado.");
    }

    tokenStorage.set(token.access_token);
    try {
      const profile = await getCurrentUser();
      setUser(profile);
      setSessionNotice(null);
    } catch (error) {
      tokenStorage.clear();
      setUser(null);
      throw error;
    }
  }, []);

  const signUp = useCallback((payload: UserCreatePayload) => {
    return registerUser(payload);
  }, []);

  const value = useMemo(
    () => ({ user, isLoading, sessionNotice, signIn, signUp, signOut }),
    [user, isLoading, sessionNotice, signIn, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth precisa estar dentro de AuthProvider.");
  return context;
}
