import axios from 'axios';

// 1. 创建 Axios 实例
const apiClient = axios.create({
  // 核心：统一配置基础路径。配置后，所有请求都会自动加上 /api 前缀
  baseURL: '/api',
  // 统一超时时间 (延长至 30 秒，防止后端冷启动拉取数据超时)
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 2. 请求拦截器 (Request Interceptor)
apiClient.interceptors.request.use(
  (config) => {
    // 在这里可以做发请求前的统一处理
    // 例如：从 localStorage/Cookie 中获取 Token 并塞入 Header
    // const token = localStorage.getItem('token');
    // if (token) {
    //   config.headers.Authorization = `Bearer ${token}`;
    // }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 3. 响应拦截器 (Response Interceptor)
apiClient.interceptors.response.use(
  (response) => {
    // 2xx 范围内的状态码会触发该函数
    // 可以在这里直接剥离外层的 axios data，直接返回后端真实的数据体
    return response.data;
  },
  (error) => {
    // 全局统一错误处理
    if (error.response) {
      const status = error.response.status;
      if (status === 401) {
        console.error('未授权或 Token 过期，请重新登录');
        // 可以触发全局登出逻辑，或重定向到 /login
        // window.location.href = '/login';
      } else if (status === 404) {
        console.error('请求的接口不存在');
      } else if (status >= 500) {
        console.error('服务器内部错误');
      }
    } else {
      console.error('网络异常或请求超时');
    }
    return Promise.reject(error);
  }
);

export default apiClient;