import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { adminApi, AdminUser, SystemStats } from '../utils/adminApi';

const AdminDashboard: React.FC = () => {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [adminUser, setAdminUser] = useState<AdminUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [showPasswordChange, setShowPasswordChange] = useState(false);
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: ''
  });
  const [passwordError, setPasswordError] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const [statsData, userData] = await Promise.all([
        adminApi.getStats(),
        adminApi.getMe()
      ]);
      setStats(statsData);
      setAdminUser(userData);
    } catch (error) {
      console.error('Failed to load dashboard data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('admin_token');
    navigate('/admin/login');
  };

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    setPasswordError('');

    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      setPasswordError('New passwords do not match');
      return;
    }

    try {
      await adminApi.changePassword(passwordForm.currentPassword, passwordForm.newPassword);
      setShowPasswordChange(false);
      setPasswordForm({ currentPassword: '', newPassword: '', confirmPassword: '' });
      alert('Password changed successfully');
    } catch (error: any) {
      setPasswordError(error.response?.data?.detail || 'Failed to change password');
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-lg">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">Admin Dashboard</h1>
              <p className="text-sm text-gray-600">Shopify Automation System</p>
            </div>
            <div className="flex items-center space-x-4">
              <div className="text-sm">
                <span className="text-gray-600">Welcome, </span>
                <span className="font-medium">{adminUser?.full_name}</span>
                <span className="text-gray-500 ml-2">({adminUser?.role})</span>
              </div>
              <button
                onClick={() => setShowPasswordChange(true)}
                className="text-sm bg-gray-100 hover:bg-gray-200 px-3 py-1 rounded"
              >
                Change Password
              </button>
              <button
                onClick={handleLogout}
                className="text-sm bg-red-100 hover:bg-red-200 text-red-800 px-3 py-1 rounded"
              >
                Logout
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Password Change Modal */}
      {showPasswordChange && (
        <div className="fixed inset-0 bg-gray-600 bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-full max-w-md">
            <h3 className="text-lg font-medium mb-4">Change Password</h3>
            <form onSubmit={handlePasswordChange} className="space-y-4">
              {passwordError && (
                <div className="text-red-600 text-sm">{passwordError}</div>
              )}
              <input
                type="password"
                placeholder="Current Password"
                className="w-full p-2 border rounded"
                value={passwordForm.currentPassword}
                onChange={(e) => setPasswordForm(prev => ({ ...prev, currentPassword: e.target.value }))}
                required
              />
              <input
                type="password"
                placeholder="New Password"
                className="w-full p-2 border rounded"
                value={passwordForm.newPassword}
                onChange={(e) => setPasswordForm(prev => ({ ...prev, newPassword: e.target.value }))}
                required
                minLength={8}
              />
              <input
                type="password"
                placeholder="Confirm New Password"
                className="w-full p-2 border rounded"
                value={passwordForm.confirmPassword}
                onChange={(e) => setPasswordForm(prev => ({ ...prev, confirmPassword: e.target.value }))}
                required
              />
              <div className="flex space-x-2">
                <button
                  type="submit"
                  className="flex-1 bg-blue-600 text-white py-2 rounded hover:bg-blue-700"
                >
                  Change Password
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowPasswordChange(false);
                    setPasswordForm({ currentPassword: '', newPassword: '', confirmPassword: '' });
                    setPasswordError('');
                  }}
                  className="flex-1 bg-gray-300 text-gray-700 py-2 rounded hover:bg-gray-400"
                >
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Main Content */}
      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        {/* Stats Grid */}
        <div className="px-4 py-6 sm:px-0">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <div className="bg-white overflow-hidden shadow rounded-lg">
              <div className="p-5">
                <div className="flex items-center">
                  <div className="w-0 flex-1">
                    <dl>
                      <dt className="text-sm font-medium text-gray-500 truncate">Total Users</dt>
                      <dd className="text-lg font-medium text-gray-900">{stats?.total_users}</dd>
                    </dl>
                  </div>
                  <div className="text-sm text-gray-500">
                    {stats?.active_users} active
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-white overflow-hidden shadow rounded-lg">
              <div className="p-5">
                <div className="flex items-center">
                  <div className="w-0 flex-1">
                    <dl>
                      <dt className="text-sm font-medium text-gray-500 truncate">Connected Stores</dt>
                      <dd className="text-lg font-medium text-gray-900">{stats?.total_stores}</dd>
                    </dl>
                  </div>
                  <div className="text-sm text-gray-500">
                    {stats?.active_stores} active
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-white overflow-hidden shadow rounded-lg">
              <div className="p-5">
                <div className="flex items-center">
                  <div className="w-0 flex-1">
                    <dl>
                      <dt className="text-sm font-medium text-gray-500 truncate">Processing Rules</dt>
                      <dd className="text-lg font-medium text-gray-900">{stats?.total_rules}</dd>
                    </dl>
                  </div>
                  <div className="text-sm text-gray-500">
                    {stats?.active_rules} active
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-white overflow-hidden shadow rounded-lg">
              <div className="p-5">
                <div className="flex items-center">
                  <div className="w-0 flex-1">
                    <dl>
                      <dt className="text-sm font-medium text-gray-500 truncate">Processed Orders</dt>
                      <dd className="text-lg font-medium text-gray-900">{stats?.total_processed_orders}</dd>
                    </dl>
                  </div>
                  <div className="text-sm text-gray-500">
                    {stats?.total_order_logs} logs
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="bg-white shadow rounded-lg">
            <div className="px-4 py-5 sm:p-6">
              <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">Quick Actions</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <Link
                  to="/admin/users"
                  className="block p-4 border border-gray-200 rounded-lg hover:border-blue-500 hover:shadow-md transition-all"
                >
                  <div className="text-center">
                    <div className="text-2xl mb-2">👥</div>
                    <div className="text-sm font-medium text-gray-900">Manage Users</div>
                    <div className="text-xs text-gray-500">View and manage user accounts</div>
                  </div>
                </Link>

                <Link
                  to="/admin/stores"
                  className="block p-4 border border-gray-200 rounded-lg hover:border-blue-500 hover:shadow-md transition-all"
                >
                  <div className="text-center">
                    <div className="text-2xl mb-2">🏪</div>
                    <div className="text-sm font-medium text-gray-900">Store Management</div>
                    <div className="text-xs text-gray-500">Monitor connected stores</div>
                  </div>
                </Link>

                <Link
                  to="/admin/rules"
                  className="block p-4 border border-gray-200 rounded-lg hover:border-blue-500 hover:shadow-md transition-all"
                >
                  <div className="text-center">
                    <div className="text-2xl mb-2">⚙️</div>
                    <div className="text-sm font-medium text-gray-900">Processing Rules</div>
                    <div className="text-xs text-gray-500">View automation rules</div>
                  </div>
                </Link>

                <Link
                  to="/admin/logs"
                  className="block p-4 border border-gray-200 rounded-lg hover:border-blue-500 hover:shadow-md transition-all"
                >
                  <div className="text-center">
                    <div className="text-2xl mb-2">📋</div>
                    <div className="text-sm font-medium text-gray-900">System Logs</div>
                    <div className="text-xs text-gray-500">Monitor system activity</div>
                  </div>
                </Link>
              </div>
            </div>
          </div>

          {/* Recent Activity */}
          <div className="mt-8 bg-white shadow rounded-lg">
            <div className="px-4 py-5 sm:p-6">
              <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">Recent Registrations</h3>
              <div className="text-3xl font-bold text-blue-600">{stats?.recent_registrations}</div>
              <div className="text-sm text-gray-500">New users in the last 7 days</div>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};

export default AdminDashboard;