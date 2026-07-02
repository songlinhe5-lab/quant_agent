import React, { createContext, useContext, useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient, setAccessToken } from '@/lib/api-client';

interface User {
  id: string | number;
  username: string;
  email?: string;
  role?: string;
  // 根据你后端的实际返回字段补充
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  // 初始化：应用加载时检查用户是否已登录（结合 api-client 的无感刷新机制）
  useEffect(() => {
    const initAuth = async () => {
      try {
        // 如果内存中没有 access_token，但有 httpOnly 的 refresh_token
        // 这里的请求触发 401 后，你的 api-client 会自动帮我们调用 /auth/refresh
        const res = await apiClient.get('/auth/me');
        if (res.data) setUser(res.data);
      } catch (error) {
        // 会话确实过期或未登录
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    };
    initAuth();
  }, []);

  const login = async (username: string, password: string) => {
    // 💡 注意：如果你使用的是 Python FastAPI，默认标准的 OAuth2PasswordRequestForm 需要 form-data
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    // 如果你的后端接收 JSON，可直接改成 apiClient.post('/auth/login', { username, password })
    const res = await apiClient.post('/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    });

    const { access_token } = res.data;
    
    // 1. 将 Token 注入到全局 Axios 实例的内存中，供后续请求使用
    setAccessToken(access_token);

    // 2. 登录成功后，立即拉取当前用户信息
    const userRes = await apiClient.get('/auth/me');
    setUser(userRes.data);
  };

  const logout = async () => {
    // 可选：通知后端注销（清除服务端的 Refresh Token Cookie）
    try { await apiClient.post('/auth/logout'); } catch (e) { /* ignore logout error */ }
    
    setAccessToken(null);
    setUser(null);
    // 登出时同样使用硬跳转，确保内存和前端缓存中的敏感数据彻底清空
    window.location.href = '/login';
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth 必须在 AuthProvider 内部使用');
  }
  return context;
}