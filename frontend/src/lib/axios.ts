import axios from 'axios';
import { useAuthStore } from '@/store/useAuthStore';

// Exported so callers that can't use the `api` instance directly — e.g. the
// SSE hook, which needs an absolute URL for `new EventSource(...)` rather
// than axios's `baseURL` config — can build a matching URL without
// duplicating this fallback string.
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use(
  (config) => {
    // Get the state directly from the store
    const { accessToken, tenantId } = useAuthStore.getState();
    
    if (accessToken) {
      config.headers.Authorization = `Bearer ${accessToken}`;
    }
    
    if (tenantId) {
      config.headers['X-Tenant-ID'] = tenantId;
    }
    
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

let isRefreshing = false;
let failedQueue: any[] = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  
  failedQueue = [];
};

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    
    // Check if error is 401 and it's not a retry or auth request
    if (error.response?.status === 401 && !originalRequest._retry && originalRequest.url !== '/auth/login' && originalRequest.url !== '/auth/refresh') {
      
      if (isRefreshing) {
        return new Promise(function(resolve, reject) {
          failedQueue.push({ resolve, reject });
        }).then(token => {
          originalRequest.headers['Authorization'] = 'Bearer ' + token;
          return api(originalRequest);
        }).catch(err => {
          return Promise.reject(err);
        });
      }
      
      originalRequest._retry = true;
      isRefreshing = true;
      
      const { refreshToken, setTokens, logout } = useAuthStore.getState();
      
      if (!refreshToken) {
        processQueue(error, null);
        isRefreshing = false;
        logout();
        if (typeof window !== 'undefined') window.location.href = '/login';
        return Promise.reject(error);
      }
      
      try {
        const { data } = await axios.post(
          `${API_BASE_URL}/auth/refresh`,
          { refresh_token: refreshToken }
        );
        
        const newAccessToken = data.access_token;
        const newRefreshToken = data.refresh_token;
        
        setTokens(newAccessToken, newRefreshToken);
        processQueue(null, newAccessToken);
        
        originalRequest.headers['Authorization'] = `Bearer ${newAccessToken}`;
        return api(originalRequest);
      } catch (err) {
        processQueue(err, null);
        logout();
        if (typeof window !== 'undefined') window.location.href = '/login';
        return Promise.reject(err);
      } finally {
        isRefreshing = false;
      }
    }
    
    return Promise.reject(error);
  }
);

export default api;
