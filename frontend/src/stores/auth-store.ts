import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
  id: string;
  email: string;
  name: string;
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  accessToken: string | null;
  refreshTokenValue: string | null;
  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
  setTokens: (accessToken: string, refreshToken: string) => void;
  refreshToken: () => Promise<boolean>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isLoading: true,
      accessToken: null,
      refreshTokenValue: null,
      setUser: (user) => set({ user, isLoading: false }),
      setLoading: (isLoading) => set({ isLoading }),
      setTokens: (accessToken, refreshToken) => set({ accessToken, refreshTokenValue: refreshToken }),
      refreshToken: async () => {
        const state = get();
        if (!state.refreshTokenValue) return false;
        try {
          const response = await fetch('/api/v1/auth/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refreshToken: state.refreshTokenValue }),
          });
          if (!response.ok) return false;
          const data = await response.json();
          set({ accessToken: data.accessToken, refreshTokenValue: data.refreshToken });
          return true;
        } catch {
          return false;
        }
      },
      logout: () => set({ user: null, isLoading: false, accessToken: null, refreshTokenValue: null }),
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({ user: state.user, accessToken: state.accessToken, refreshTokenValue: state.refreshTokenValue }),
    }
  )
);
