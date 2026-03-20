import React, { useState } from "react";
import { motion } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BuildingStorefrontIcon,
  CogIcon,
  ChartBarIcon,
  ClockIcon,
  CheckCircleIcon,
  ExclamationCircleIcon,
  ArrowUpIcon,
  ArrowDownIcon,
  ShieldCheckIcon,
  ServerIcon,
  SparklesIcon,
  DocumentTextIcon,
  TrashIcon,
} from "@heroicons/react/24/outline";
import {
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import api from "../utils/api";
import LoadingSpinner from "../components/LoadingSpinner";
import FailedTasksModal from "../components/FailedTasksModal";
import { useTimezone } from "../contexts/TimezoneContext";
import { formatDate } from "../utils/dateFormat";

interface EnhancedDashboardStats {
  processing: {
    orders_today: number;
    orders_last_7_days: number[];
    success_rate: number;
    total_processed: number;
    last_sync: string | null;
    next_sync: string | null;
    is_syncing: boolean;
    sync_enabled: boolean;
  };
  rules: {
    total: number;
    active: number;
    triggered_today: { [key: string]: number };
  };
  stores: {
    total: number;
    active: number;
    activity: { [key: string]: number };
  };
  fraud: {
    analyses_today: number;
    high_risk_count: number;
    active_rules: number;
  };
  system: {
    celery_status: "healthy" | "degraded" | "down";
    failed_tasks: number;
  };
  recent_activity: Array<{
    id: number;
    order_id: string;
    order_number: string;
    store_name: string;
    action: string;
    status: string;
    created_at: string;
  }>;
  recent_errors: Array<{
    id: number;
    order_id: string;
    order_number: string;
    store_name: string;
    action: string;
    error_message: string;
    created_at: string;
  }>;
}

const Dashboard: React.FC = () => {
  const { timezone } = useTimezone();
  const queryClient = useQueryClient();
  const [showFailedTasksModal, setShowFailedTasksModal] = useState(false);
  const [showClearErrorsConfirm, setShowClearErrorsConfirm] = useState(false);
  
  // Use both endpoints - enhanced for new features, basic for compatibility
  const { data: enhancedStats, isLoading: isLoadingEnhanced } = useQuery<EnhancedDashboardStats>({
    queryKey: ["dashboard-enhanced-stats"],
    queryFn: async () => {
      const response = await api.get("/dashboard/enhanced-stats");
      return response.data;
    },
    refetchInterval: 30000, // Auto-refresh every 30 seconds
    retry: 1, // Only retry once to avoid spamming
  });

  const { data: basicStats, isLoading: isLoadingBasic } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: async () => {
      const response = await api.get("/dashboard/stats");
      return response.data;
    },
  });

  // Mutation for clearing error logs
  const clearErrorLogsMutation = useMutation({
    mutationFn: async () => {
      const response = await api.delete("/admin/clear-error-logs");
      return response.data;
    },
    onSuccess: (data) => {
      // Refetch dashboard data to update the UI
      queryClient.invalidateQueries({ queryKey: ["dashboard-enhanced-stats"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      setShowClearErrorsConfirm(false);
      // Show success message (you might want to add a toast notification here)
      alert(`${data.message}`);
    },
    onError: (error: any) => {
      alert(error.response?.data?.detail || "Failed to clear error logs");
    },
  });

  const isLoading = isLoadingEnhanced && isLoadingBasic;
  
  // Use enhanced stats if available, fallback to basic stats
  const stats = enhancedStats || (basicStats ? {
    processing: {
      orders_today: 0,
      orders_last_7_days: [0, 0, 0, 0, 0, 0, 0],
      success_rate: 100,
      total_processed: 0,
      last_sync: null,
      next_sync: null,
      is_syncing: false,
      sync_enabled: false,
    },
    rules: basicStats.rules,
    stores: basicStats.stores,
    fraud: {
      analyses_today: 0,
      high_risk_count: 0,
      active_rules: 0,
    },
    system: {
      celery_status: "healthy" as const,
      failed_tasks: 0,
    },
    recent_activity: basicStats.recent_activity || [],
    recent_errors: [],
  } : null);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  // Prepare chart data
  const last7Days = ["6d ago", "5d ago", "4d ago", "3d ago", "2d ago", "Yesterday", "Today"];
  const orderTrendData = stats?.processing.orders_last_7_days.map((count, index) => ({
    day: last7Days[index],
    orders: count,
  })) || [];

  const successRateData = [
    { name: "Success", value: stats?.processing.success_rate || 0, color: "#10b981" },
    { name: "Error", value: 100 - (stats?.processing.success_rate || 100), color: "#ef4444" },
  ];

  const systemHealthColor = {
    healthy: "text-green-600 bg-green-100",
    degraded: "text-yellow-600 bg-yellow-100",
    down: "text-red-600 bg-red-100",
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "success":
      case "info":
        return <CheckCircleIcon className="h-4 w-4 text-green-500" />;
      case "error":
        return <ExclamationCircleIcon className="h-4 w-4 text-red-500" />;
      default:
        return <ClockIcon className="h-4 w-4 text-gray-500" />;
    }
  };

  const statCards = [
    {
      title: "Total Processed",
      value: stats?.processing.total_processed || 0,
      subValue: "All time",
      icon: DocumentTextIcon,
      color: "text-indigo-600",
      bgColor: "bg-indigo-100",
    },
    {
      title: "Orders Today",
      value: stats?.processing?.orders_today || 0,
      subValue: (stats?.processing?.orders_today ?? 0) > (stats?.processing?.orders_last_7_days?.[5] || 0) ? "↑ from yesterday" : "↓ from yesterday",
      icon: ChartBarIcon,
      color: "text-blue-600",
      bgColor: "bg-blue-100",
      trend: (stats?.processing?.orders_today ?? 0) > (stats?.processing?.orders_last_7_days?.[5] || 0) ? "up" : "down",
    },
    {
      title: "Success Rate",
      value: `${stats?.processing?.success_rate ?? 100}%`,
      subValue: "Today",
      icon: CheckCircleIcon,
      color: (stats?.processing?.success_rate ?? 100) >= 95 ? "text-green-600" : (stats?.processing?.success_rate ?? 100) >= 80 ? "text-yellow-600" : "text-red-600",
      bgColor: (stats?.processing?.success_rate ?? 100) >= 95 ? "bg-green-100" : (stats?.processing?.success_rate ?? 100) >= 80 ? "bg-yellow-100" : "bg-red-100",
    },
    {
      title: "Active Rules",
      value: stats?.rules.active || 0,
      subValue: `of ${stats?.rules.total || 0} total`,
      icon: CogIcon,
      color: "text-purple-600",
      bgColor: "bg-purple-100",
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-dark-800">
            Dashboard
          </h1>
          <p className="mt-2 text-gray-600 dark:text-dark-500">
            Welcome back! Here's what's happening with your automation system.
          </p>
        </div>
        {/* Quick Actions Button Group */}
        <div className="flex space-x-3">
          <a
            href="/stores"
            className="inline-flex items-center px-4 py-2 border border-gray-300 dark:border-dark-300 rounded-md shadow-sm text-sm font-medium text-gray-700 dark:text-dark-700 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200"
          >
            <BuildingStorefrontIcon className="h-4 w-4 mr-2" />
            Manage Stores
          </a>
          <a
            href="/rules/new"
            className="inline-flex items-center px-4 py-2 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-shopify-600 hover:bg-shopify-700"
          >
            <SparklesIcon className="h-4 w-4 mr-2" />
            Create Rule
          </a>
        </div>
      </div>

      {/* System Status and Sync Info */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* System Health */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-4"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center">
              <ServerIcon className="h-5 w-5 text-gray-500 mr-2" />
              <span className="text-sm font-medium text-gray-700 dark:text-dark-600">
                System Health
              </span>
            </div>
            <div className="flex items-center space-x-4">
              <button
                onClick={() => setShowClearErrorsConfirm(true)}
                className="px-3 py-1 text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 rounded-md flex items-center gap-1 transition-colors"
                title="Clear error logs and failed tasks only"
              >
                <TrashIcon className="h-3 w-3" />
                Clear Errors
              </button>
              <span
                className={`px-2 py-1 text-xs font-medium rounded-full ${
                  systemHealthColor[stats?.system.celery_status || "healthy"]
                }`}
              >
                {stats?.system.celery_status || "healthy"}
              </span>
              {(stats?.system?.failed_tasks ?? 0) > 0 && (
                <button
                  onClick={() => setShowFailedTasksModal(true)}
                  className="text-xs text-red-600 hover:text-red-700 hover:underline"
                >
                  {stats?.system?.failed_tasks} failed tasks
                </button>
              )}
            </div>
          </div>
        </motion.div>

        {/* Sync Status */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="card p-4"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center">
              <ClockIcon className="h-5 w-5 text-gray-500 mr-2" />
              <span className="text-sm font-medium text-gray-700 dark:text-dark-600">
                Sync Status
              </span>
            </div>
            <span className="text-sm text-gray-600 dark:text-dark-500">
              {stats?.processing.sync_enabled ? (
                <>
                  Next: {stats?.processing?.next_sync ? formatDate(stats.processing.next_sync, { timezone, dateFormat: "MMM d, h:mm a" }) : "Not scheduled"}
                </>
              ) : (
                <span className="text-yellow-600">Sync disabled</span>
              )}
            </span>
          </div>
        </motion.div>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {statCards.map((stat, index) => (
          <motion.div
            key={stat.title}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 + index * 0.1 }}
            className="card hover:shadow-lg transition-shadow"
          >
            <div className="flex flex-col">
              <div className="flex items-center justify-between mb-2">
                <div
                  className={`p-2 rounded-lg ${stat.bgColor} dark:bg-opacity-20`}
                >
                  <stat.icon
                    className={`h-5 w-5 ${stat.color} dark:opacity-80`}
                  />
                </div>
                {stat.trend && (
                  <div className="flex items-center">
                    {stat.trend === "up" ? (
                      <ArrowUpIcon className="h-4 w-4 text-green-500" />
                    ) : (
                      <ArrowDownIcon className="h-4 w-4 text-red-500" />
                    )}
                  </div>
                )}
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-dark-800">
                {stat.value}
              </p>
              <p className="text-sm text-gray-600 dark:text-dark-500">
                {stat.title}
              </p>
              <p className="text-xs text-gray-500 dark:text-dark-400 mt-1">
                {stat.subValue}
              </p>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Activity Overview - Charts and Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Order Trend Chart - Takes 2 columns */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
          className="card lg:col-span-2"
        >
          <h2 className="text-lg font-semibold text-gray-900 dark:text-dark-800 mb-4">
            7-Day Order Trend
          </h2>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={orderTrendData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="day" stroke="#6b7280" />
              <YAxis stroke="#6b7280" />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#fff",
                  border: "1px solid #e5e7eb",
                  borderRadius: "0.375rem",
                }}
              />
              <Line
                type="monotone"
                dataKey="orders"
                stroke="#6366f1"
                strokeWidth={2}
                dot={{ fill: "#6366f1" }}
              />
            </LineChart>
          </ResponsiveContainer>
        </motion.div>

        {/* Success Rate or Rules Triggered */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.7 }}
          className="card"
        >
          {Object.keys(stats?.rules.triggered_today || {}).length > 0 ? (
            <>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-dark-800 mb-4">
                Active Rules Today
              </h2>
              <div className="space-y-2">
                {Object.entries(stats?.rules.triggered_today || {})
                  .sort(([, a], [, b]) => (b as number) - (a as number))
                  .slice(0, 6)
                  .map(([ruleName, count]) => (
                    <div key={ruleName} className="flex justify-between items-center py-1">
                      <span className="text-sm text-gray-600 dark:text-dark-500 truncate max-w-[150px]">
                        {ruleName}
                      </span>
                      <span className="text-sm font-medium text-gray-900 dark:text-dark-800 bg-gray-100 dark:bg-dark-200 px-2 py-1 rounded">
                        {count as React.ReactNode}
                      </span>
                    </div>
                  ))}
              </div>
            </>
          ) : (
            <>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-dark-800 mb-4">
                Today's Performance
              </h2>
              <div className="flex items-center justify-center h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={successRateData}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={80}
                      fill="#8884d8"
                      dataKey="value"
                    >
                      {successRateData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
                <div className="absolute text-center">
                  <p className="text-2xl font-bold text-gray-900 dark:text-dark-800">
                    {stats?.processing.success_rate || 100}%
                  </p>
                  <p className="text-sm text-gray-600 dark:text-dark-500">Success</p>
                </div>
              </div>
            </>
          )}
        </motion.div>
      </div>

      {/* Activity Feed and Additional Info */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Activity - Takes 2 columns */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.8 }}
          className="card lg:col-span-2"
        >
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-dark-800">
              Recent Activity
            </h2>
            <a
              href="/order-logs"
              className="text-sm text-shopify-600 hover:text-shopify-700"
            >
              View all →
            </a>
          </div>
          <div className="space-y-3 max-h-80 overflow-y-auto">
            {stats?.recent_activity.length === 0 ? (
              <div className="text-center py-8">
                <ChartBarIcon className="h-12 w-12 text-gray-300 dark:text-dark-300 mx-auto mb-3" />
                <p className="text-sm text-gray-500 dark:text-dark-400">
                  No orders processed yet
                </p>
                <p className="text-xs text-gray-400 dark:text-dark-400 mt-1">
                  Orders will appear here once processing begins
                </p>
              </div>
            ) : (
              stats?.recent_activity.map((log: any) => (
                <div
                  key={log.id}
                  className="flex items-start space-x-3 p-3 hover:bg-gray-50 dark:hover:bg-dark-50 rounded-lg transition-colors"
                >
                  {getStatusIcon(log.status)}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900 dark:text-dark-800">
                        {log.order_number}
                      </span>
                      <span className="text-xs text-gray-500 dark:text-dark-400">
                        {formatDate(log.created_at, { timezone, dateFormat: "MMM d, h:mm a" })}
                      </span>
                    </div>
                    <div className="text-sm text-gray-600 dark:text-dark-500 mt-1">
                      {log.store_name} • {
                        log.action.startsWith("applied_rule_") && log.details?.rule_name
                          ? `applied rule: ${log.details.rule_name}`
                          : log.action.replace(/_/g, " ")
                      }
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </motion.div>

        {/* Side Panel - Errors or Fraud or Store Status */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.9 }}
          className="space-y-4"
        >
          {/* Store Status */}
          <div className="card">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-dark-800 mb-3">
              Store Status
            </h3>
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600 dark:text-dark-500">
                  Connected
                </span>
                <span className="font-medium text-gray-900 dark:text-dark-800">
                  {stats?.stores.total || 0}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-600 dark:text-dark-500">
                  Active
                </span>
                <span className="font-medium text-green-600">
                  {stats?.stores.active || 0}
                </span>
              </div>
              {stats?.stores.total === 0 && (
                <a
                  href="/stores"
                  className="text-xs text-shopify-600 hover:text-shopify-700 mt-2 inline-block"
                >
                  Connect your first store →
                </a>
              )}
            </div>
          </div>

          {/* Fraud Detection Summary - Only show if active */}
          {(stats?.fraud?.active_rules ?? 0) > 0 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-dark-800 mb-3 flex items-center">
                <ShieldCheckIcon className="h-4 w-4 mr-1 text-indigo-600" />
                Fraud Detection
              </h3>
              <div className="space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-600 dark:text-dark-500">
                    Checked Today
                  </span>
                  <span className="font-medium text-gray-900 dark:text-dark-800">
                    {stats?.fraud?.analyses_today}
                  </span>
                </div>
                {(stats?.fraud?.high_risk_count ?? 0) > 0 && (
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600 dark:text-dark-500">
                      High Risk (7d)
                    </span>
                    <span className="font-medium text-red-600">
                      {stats?.fraud?.high_risk_count}
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Recent Errors - Only show if there are errors */}
          {stats?.recent_errors && stats.recent_errors.length > 0 && (
            <div className="card border-red-200 dark:border-red-900">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-red-900 dark:text-red-400">
                  Recent Errors
                </h3>
                <button
                  onClick={() => setShowClearErrorsConfirm(true)}
                  className="text-xs text-red-600 hover:text-red-700 flex items-center gap-1"
                  title="Clear error logs only"
                >
                  <TrashIcon className="h-3 w-3" />
                  Clear
                </button>
              </div>
              <div className="space-y-2 max-h-40 overflow-y-auto">
                {stats.recent_errors.slice(0, 3).map((error) => (
                  <div
                    key={error.id}
                    className="text-xs"
                  >
                    <div className="font-medium text-red-800 dark:text-red-400">
                      {error.order_number}
                    </div>
                    <div className="text-red-600 dark:text-red-500 truncate">
                      {error.error_message || "Unknown error"}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      </div>
      {/* Failed Tasks Modal */}
      <FailedTasksModal
        isOpen={showFailedTasksModal}
        onClose={() => setShowFailedTasksModal(false)}
      />

      {/* Clear Error Logs Confirmation Modal */}
      {showClearErrorsConfirm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-white dark:bg-dark-100 rounded-lg p-6 max-w-md w-full mx-4"
          >
            <h3 className="text-lg font-semibold text-gray-900 dark:text-dark-800 mb-4">
              Clear Error Logs and Failed Tasks?
            </h3>
            <p className="text-sm text-gray-600 dark:text-dark-500 mb-6">
              This will permanently delete only error logs and failed system tasks from your system. 
              Successful order processing logs and historical data will be preserved.
              This action cannot be undone.
            </p>
            <div className="flex justify-end space-x-3">
              <button
                onClick={() => setShowClearErrorsConfirm(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-dark-700 bg-gray-100 dark:bg-dark-200 rounded-md hover:bg-gray-200 dark:hover:bg-dark-300"
              >
                Cancel
              </button>
              <button
                onClick={() => clearErrorLogsMutation.mutate()}
                disabled={clearErrorLogsMutation.isPending}
                className="px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-md hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {clearErrorLogsMutation.isPending ? "Clearing..." : "Clear Errors"}
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;