import axios from 'axios';

const API_BASE_URL = 'http://localhost:8000';

const adminApiClient = axios.create({
  baseURL: `${API_BASE_URL}/admin`,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add auth interceptor
adminApiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Add response interceptor for token expiration
adminApiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('admin_token');
      window.location.href = '/admin/login';
    }
    return Promise.reject(error);
  }
);

export interface AdminUser {
  id: number;
  username: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  last_login?: string;
  created_at: string;
  updated_at?: string;
}

export interface SystemStats {
  total_users: number;
  active_users: number;
  total_stores: number;
  active_stores: number;
  total_rules: number;
  active_rules: number;
  total_processed_orders: number;
  total_order_logs: number;
  recent_registrations: number;
}

export interface UserManagement {
  id: number;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  stores_count: number;
  rules_count: number;
  last_activity?: string;
}

export interface AdminAuditLog {
  id: number;
  admin_user_id: number;
  action: string;
  target_type?: string;
  target_id?: string;
  details?: any;
  ip_address?: string;
  user_agent?: string;
  created_at: string;
  admin_user: AdminUser;
}

export const adminApi = {
  // Auth
  login: async (username: string, password: string) => {
    const response = await adminApiClient.post('/auth/login', { username, password });
    return response.data;
  },

  getMe: async (): Promise<AdminUser> => {
    const response = await adminApiClient.get('/auth/me');
    return response.data;
  },

  changePassword: async (currentPassword: string, newPassword: string) => {
    const response = await adminApiClient.put('/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword
    });
    return response.data;
  },

  // Dashboard
  getStats: async (): Promise<SystemStats> => {
    const response = await adminApiClient.get('/stats');
    return response.data;
  },

  // User Management
  getUsers: async (skip = 0, limit = 100): Promise<UserManagement[]> => {
    const response = await adminApiClient.get(`/users?skip=${skip}&limit=${limit}`);
    return response.data;
  },

  toggleUserActive: async (userId: number) => {
    const response = await adminApiClient.put(`/users/${userId}/toggle-active`);
    return response.data;
  },

  deleteUser: async (userId: number) => {
    const response = await adminApiClient.delete(`/users/${userId}`);
    return response.data;
  },

  // Stores
  getStores: async (skip = 0, limit = 100) => {
    const response = await adminApiClient.get(`/stores?skip=${skip}&limit=${limit}`);
    return response.data;
  },

  // Rules
  getRules: async (skip = 0, limit = 100) => {
    const response = await adminApiClient.get(`/rules?skip=${skip}&limit=${limit}`);
    return response.data;
  },

  // Order Logs
  getOrderLogs: async (skip = 0, limit = 100, statusFilter?: string) => {
    let url = `/order-logs?skip=${skip}&limit=${limit}`;
    if (statusFilter) {
      url += `&status_filter=${statusFilter}`;
    }
    const response = await adminApiClient.get(url);
    return response.data;
  },

  // Audit Logs
  getAuditLogs: async (skip = 0, limit = 50, action?: string): Promise<AdminAuditLog[]> => {
    let url = `/audit-logs?skip=${skip}&limit=${limit}`;
    if (action) {
      url += `&action=${action}`;
    }
    const response = await adminApiClient.get(url);
    return response.data;
  },

  // Admin User Management
  createAdminUser: async (userData: {
    username: string;
    email: string;
    full_name: string;
    password: string;
    role: string;
  }): Promise<AdminUser> => {
    const response = await adminApiClient.post('/users', userData);
    return response.data;
  },

  // Database Management
  getDatabaseInfo: async () => {
    const response = await adminApiClient.get('/database/info');
    return response.data;
  },

  backupDatabase: async () => {
    const response = await adminApiClient.get('/database/backup', {
      responseType: 'blob'
    });
    
    // Create download link
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    
    // Extract filename from content-disposition header or use default
    const contentDisposition = response.headers['content-disposition'];
    let filename = 'shopify_automation_backup.db';
    if (contentDisposition) {
      const filenameMatch = contentDisposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
      if (filenameMatch && filenameMatch[1]) {
        filename = filenameMatch[1].replace(/['"]/g, '');
      }
    }
    
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  },

  restoreDatabase: async (file: File, onProgress?: (progress: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);
    
    const response = await adminApiClient.post('/database/restore', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(progress);
        }
      }
    });
    
    return response.data;
  },
};

export default adminApi;