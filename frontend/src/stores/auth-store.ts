/**
 * Auth Store — 认证状态管理
 * SEC-07: Access Token 仅存于内存（lib/api-client.ts 的 currentAccessToken），
 *         Refresh Token 由浏览器自动携带 HttpOnly Cookie（withCredentials: true）。
 *         严禁将任何 Token 持久化到 localStorage。
 */
import { create } from 'zustand';

interface User {
  id: string | number;
  username: string;
  email?: string;
  role?: string;
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  (set) => ({
    user: null,
    isLoading: true,
    setUser: (user) => set({ user, isLoading: false }),
    setLoading: (isLoading) => set({ isLoading }),
    logout: () => set({ user: null, isLoading: false }),
  })
);
