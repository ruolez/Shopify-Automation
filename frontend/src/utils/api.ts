import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

const API_BASE_URL =
  (import.meta as any).env?.VITE_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: Error) => void;
}> = [];

const processQueue = (error: Error | null, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else if (token) {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  },
);

// FastAPI validation errors (422) send `detail` as a list of objects; pages render
// `detail` in toasts, so normalize it to a string once here.
const formatErrorDetail = (detail: unknown): string => {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item: any) => {
        if (item && typeof item === "object" && "msg" in item) {
          const field = Array.isArray(item.loc) ? item.loc.filter((p: any) => p !== "body").join(".") : "";
          return field ? `${field}: ${item.msg}` : String(item.msg);
        }
        return typeof item === "string" ? item : JSON.stringify(item);
      })
      .join("; ");
  }
  return JSON.stringify(detail);
};

// Response interceptor to handle auth errors and token refresh
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const data = error.response?.data as { detail?: unknown } | undefined;
    if (data && data.detail !== undefined && typeof data.detail !== "string") {
      data.detail = formatErrorDetail(data.detail);
    }

    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    // If error is not 401 or request already retried, reject
    if (error.response?.status !== 401 || originalRequest._retry) {
      // If still 401 after retry, clear tokens and redirect
      if (error.response?.status === 401 && originalRequest._retry) {
        localStorage.removeItem("token");
        localStorage.removeItem("refreshToken");
        window.location.href = "/login";
      }
      return Promise.reject(error);
    }

    // Check if this is the refresh endpoint itself failing
    if (originalRequest.url?.includes("/auth/refresh")) {
      localStorage.removeItem("token");
      localStorage.removeItem("refreshToken");
      window.location.href = "/login";
      return Promise.reject(error);
    }

    const refreshToken = localStorage.getItem("refreshToken");

    // No refresh token available, redirect to login
    if (!refreshToken) {
      localStorage.removeItem("token");
      window.location.href = "/login";
      return Promise.reject(error);
    }

    // If already refreshing, queue this request
    if (isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        failedQueue.push({ resolve, reject });
      })
        .then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return api(originalRequest);
        })
        .catch((err) => {
          return Promise.reject(err);
        });
    }

    originalRequest._retry = true;
    isRefreshing = true;

    try {
      const response = await axios.post(`${API_BASE_URL}/auth/refresh`, {
        refresh_token: refreshToken,
      });

      const { access_token, refresh_token: newRefreshToken } = response.data;

      localStorage.setItem("token", access_token);
      localStorage.setItem("refreshToken", newRefreshToken);

      processQueue(null, access_token);

      originalRequest.headers.Authorization = `Bearer ${access_token}`;
      return api(originalRequest);
    } catch (refreshError) {
      processQueue(refreshError as Error, null);
      localStorage.removeItem("token");
      localStorage.removeItem("refreshToken");
      window.location.href = "/login";
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  },
);

export default api;
