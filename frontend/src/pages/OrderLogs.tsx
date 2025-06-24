import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { format } from 'date-fns';
import {
  CheckCircleIcon,
  XCircleIcon,
  InformationCircleIcon,
  ArrowPathIcon,
  PlayIcon,
} from '@heroicons/react/24/outline';
import toast from 'react-hot-toast';
import api from '../utils/api';
import LoadingSpinner from '../components/LoadingSpinner';

interface OrderLog {
  id: number;
  store_id: number;
  store_name: string;
  order_id: string;
  order_number: string;
  action: string;
  status: string;
  details: any;
  error_message: string | null;
  created_at: string;
}

interface LogsResponse {
  logs: OrderLog[];
  pagination: {
    total: number;
    page: number;
    per_page: number;
    pages: number;
  };
}

const OrderLogs: React.FC = () => {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [storeFilter, setStoreFilter] = useState<string>('');
  const [selectedOrders, setSelectedOrders] = useState<Set<string>>(new Set());
  const [selectedRule, setSelectedRule] = useState<string>('');
  
  const queryClient = useQueryClient();

  const { data: stores } = useQuery({
    queryKey: ['stores'],
    queryFn: async () => {
      const response = await api.get('/stores');
      return response.data;
    },
  });

  const { data: rules } = useQuery({
    queryKey: ['rules'],
    queryFn: async () => {
      const response = await api.get('/rules');
      return response.data;
    },
  });

  const { data, isLoading, refetch } = useQuery<LogsResponse>({
    queryKey: ['order-logs', page, statusFilter, storeFilter],
    queryFn: async () => {
      const params = new URLSearchParams({
        page: page.toString(),
        per_page: '50',
      });
      
      if (statusFilter) params.append('status', statusFilter);
      if (storeFilter) params.append('store_id', storeFilter);
      
      const response = await api.get(`/order-logs?${params}`);
      return response.data;
    },
  });

  const retryOrders = useMutation({
    mutationFn: async (data: { order_ids: string[]; rule_id?: number }) => {
      const response = await api.post('/order-logs/retry', data);
      return response.data;
    },
    onSuccess: (result) => {
      toast.success(`Retry completed: ${result.processed_count} processed, ${result.failed_count} failed`);
      queryClient.invalidateQueries({ queryKey: ['order-logs'] });
      setSelectedOrders(new Set());
      setSelectedRule('');
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to retry orders');
    },
  });

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'success':
        return <CheckCircleIcon className="h-5 w-5 text-green-500" />;
      case 'failed':
        return <XCircleIcon className="h-5 w-5 text-red-500" />;
      default:
        return <InformationCircleIcon className="h-5 w-5 text-blue-500" />;
    }
  };

  const getActionLabel = (action: string) => {
    if (action.startsWith('applied_rule_')) {
      return 'Applied Rule';
    }
    switch (action) {
      case 'no_rules_matched':
        return 'No Rules Matched';
      case 'processing_error':
        return 'Processing Error';
      case 'retry_processing':
        return 'Retry Processing';
      default:
        return action;
    }
  };

  const handleSelectOrder = (orderId: string) => {
    const newSelected = new Set(selectedOrders);
    if (newSelected.has(orderId)) {
      newSelected.delete(orderId);
    } else {
      newSelected.add(orderId);
    }
    setSelectedOrders(newSelected);
  };

  const handleSelectAll = () => {
    if (selectedOrders.size === data?.logs.length) {
      setSelectedOrders(new Set());
    } else {
      const allOrderIds = new Set(data?.logs.map(log => log.order_id) || []);
      setSelectedOrders(allOrderIds);
    }
  };

  const handleRetryWithAllRules = () => {
    if (selectedOrders.size === 0) return;
    retryOrders.mutate({
      order_ids: Array.from(selectedOrders)
    });
  };

  const handleRetryWithSpecificRule = () => {
    if (selectedOrders.size === 0 || !selectedRule) return;
    retryOrders.mutate({
      order_ids: Array.from(selectedOrders),
      rule_id: parseInt(selectedRule)
    });
  };

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      <div className="bg-white shadow rounded-lg">
        <div className="px-4 py-5 sm:p-6">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h3 className="text-lg font-medium leading-6 text-gray-900">
                Order Processing Logs
              </h3>
              <p className="mt-1 text-sm text-gray-500">
                View all order processing activities and rule applications
              </p>
            </div>
            <button
              onClick={() => refetch()}
              className="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
            >
              <ArrowPathIcon className="h-4 w-4 mr-2" />
              Refresh
            </button>
          </div>

          {/* Filters */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div>
              <label htmlFor="store-filter" className="block text-sm font-medium text-gray-700">
                Store
              </label>
              <select
                id="store-filter"
                value={storeFilter}
                onChange={(e) => {
                  setStoreFilter(e.target.value);
                  setPage(1);
                }}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-shopify-500 focus:ring-shopify-500 sm:text-sm"
              >
                <option value="">All Stores</option>
                {stores?.map((store: any) => (
                  <option key={store.id} value={store.id}>
                    {store.shop_name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="status-filter" className="block text-sm font-medium text-gray-700">
                Status
              </label>
              <select
                id="status-filter"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setPage(1);
                }}
                className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-shopify-500 focus:ring-shopify-500 sm:text-sm"
              >
                <option value="">All Statuses</option>
                <option value="success">Success</option>
                <option value="failed">Failed</option>
                <option value="info">Info</option>
              </select>
            </div>
          </div>

          {/* Logs table */}
          {data?.logs.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-gray-500">No order logs found</p>
            </div>
          ) : (
            <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 md:rounded-lg">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      <input
                        type="checkbox"
                        checked={selectedOrders.size === data?.logs.length && data?.logs.length > 0}
                        onChange={handleSelectAll}
                        className="h-4 w-4 text-shopify-600 focus:ring-shopify-500 border-gray-300 rounded"
                      />
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Order
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Store
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Action
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Details
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Date
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {data?.logs.map((log) => (
                    <tr key={log.id}>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <input
                          type="checkbox"
                          checked={selectedOrders.has(log.order_id)}
                          onChange={() => handleSelectOrder(log.order_id)}
                          className="h-4 w-4 text-shopify-600 focus:ring-shopify-500 border-gray-300 rounded"
                        />
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        {log.order_number}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {log.store_name}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {getActionLabel(log.action)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center">
                          {getStatusIcon(log.status)}
                          <span className="ml-2 text-sm text-gray-500 capitalize">
                            {log.status}
                          </span>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        {log.error_message ? (
                          <span className="text-red-600">{log.error_message}</span>
                        ) : log.details?.rule_name ? (
                          <span>Rule: {log.details.rule_name}</span>
                        ) : log.details?.message ? (
                          <span>{log.details.message}</span>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {format(new Date(log.created_at), 'MMM d, yyyy HH:mm')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Retry Action Bar */}
          {selectedOrders.size > 0 && (
            <div className="mt-4 bg-gray-50 p-4 rounded-lg border border-gray-200">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <span className="text-sm font-medium text-gray-700">
                    {selectedOrders.size} order{selectedOrders.size !== 1 ? 's' : ''} selected
                  </span>
                  
                  <button
                    onClick={handleRetryWithAllRules}
                    disabled={retryOrders.isPending}
                    className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 disabled:opacity-50"
                  >
                    {retryOrders.isPending ? (
                      <LoadingSpinner size="sm" className="mr-2" />
                    ) : (
                      <PlayIcon className="h-4 w-4 mr-2" />
                    )}
                    Retry with All Rules
                  </button>
                </div>

                <div className="flex items-center space-x-2">
                  <select
                    value={selectedRule}
                    onChange={(e) => setSelectedRule(e.target.value)}
                    className="block w-48 text-sm border-gray-300 rounded-md shadow-sm focus:border-shopify-500 focus:ring-shopify-500"
                  >
                    <option value="">Select a specific rule...</option>
                    {rules?.map((rule: any) => (
                      <option key={rule.id} value={rule.id}>
                        {rule.name}
                      </option>
                    ))}
                  </select>
                  
                  <button
                    onClick={handleRetryWithSpecificRule}
                    disabled={retryOrders.isPending || !selectedRule}
                    className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 disabled:opacity-50"
                  >
                    {retryOrders.isPending ? (
                      <LoadingSpinner size="sm" className="mr-2" />
                    ) : (
                      <PlayIcon className="h-4 w-4 mr-2" />
                    )}
                    Retry with Rule
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Pagination */}
          {data && data.pagination.pages > 1 && (
            <div className="mt-4 flex justify-between items-center">
              <div className="text-sm text-gray-700">
                Showing page {data.pagination.page} of {data.pagination.pages}
              </div>
              <div className="flex space-x-2">
                <button
                  onClick={() => setPage(Math.max(1, page - 1))}
                  disabled={page === 1}
                  className="px-3 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage(Math.min(data.pagination.pages, page + 1))}
                  disabled={page === data.pagination.pages}
                  className="px-3 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
};

export default OrderLogs;