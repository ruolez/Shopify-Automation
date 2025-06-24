import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { CalendarIcon, DocumentArrowDownIcon, ExclamationTriangleIcon } from '@heroicons/react/24/outline';
import api from '../utils/api';
import LoadingSpinner from '../components/LoadingSpinner';

interface FulfillmentError {
  id: number;
  order_number: string;
  created_at: string;
  rule_name: string;
  location_alias: string;
  target_location_id: string;
  error_message: string;
}

interface LocationError {
  location_alias: string;
  target_location_id: string;
  error_count: number;
  orders: Array<{
    order_number: string;
    created_at: string;
    rule_name: string;
  }>;
}

interface FulfillmentErrorReport {
  total_errors: number;
  date_range: {
    start_date: string | null;
    end_date: string | null;
  };
  location_errors: LocationError[];
  detailed_logs: FulfillmentError[];
}

interface OOSOrder {
  order_number: string;
  created_at: string;
  location_alias: string;
  rule_name: string;
}

interface OOSReport {
  total_oos_orders: number;
  date_range: {
    start_date: string | null;
    end_date: string | null;
  };
  location_summary: Array<{
    location_alias: string;
    order_count: number;
    orders: Array<{
      order_number: string;
      created_at: string;
    }>;
  }>;
  orders: OOSOrder[];
}

const Reports: React.FC = () => {
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');
  const [activeTab, setActiveTab] = useState<'fulfillment-errors' | 'oos-orders'>('fulfillment-errors');

  // Build query params for date filtering
  const getDateParams = () => {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate + 'T00:00:00Z');
    if (endDate) params.append('end_date', endDate + 'T23:59:59Z');
    return params.toString();
  };

  // Fetch fulfillment errors report
  const { data: fulfillmentReport, isLoading: fulfillmentLoading, refetch: refetchFulfillment } = useQuery<FulfillmentErrorReport>({
    queryKey: ['fulfillment-errors-report', startDate, endDate],
    queryFn: async () => {
      const params = getDateParams();
      const response = await api.get(`/reports/fulfillment-errors?${params}`);
      return response.data;
    },
  });

  // Fetch OOS orders report
  const { data: oosReport, isLoading: oosLoading, refetch: refetchOOS } = useQuery<OOSReport>({
    queryKey: ['oos-orders-report', startDate, endDate],
    queryFn: async () => {
      const params = getDateParams();
      const response = await api.get(`/reports/oos-orders?${params}`);
      return response.data;
    },
  });

  const handleRefresh = () => {
    if (activeTab === 'fulfillment-errors') {
      refetchFulfillment();
    } else {
      refetchOOS();
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const exportToCSV = (data: any[], filename: string) => {
    if (!data.length) return;
    
    const headers = Object.keys(data[0]);
    const csvContent = [
      headers.join(','),
      ...data.map(row => 
        headers.map(header => 
          JSON.stringify(row[header] || '')
        ).join(',')
      )
    ].join('\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-8">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <h1 className="text-3xl font-bold text-gray-900 mb-4">Reports</h1>
        <p className="text-gray-600">
          Analyze fulfillment errors and out-of-stock issues to optimize inventory management.
        </p>
      </motion.div>

      {/* Date Range Filter */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="card"
      >
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Date Range Filter</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="label">Start Date</label>
            <div className="relative">
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="input pl-10"
              />
              <CalendarIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
            </div>
          </div>
          <div>
            <label className="label">End Date</label>
            <div className="relative">
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="input pl-10"
              />
              <CalendarIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
            </div>
          </div>
          <div className="flex items-end">
            <button
              onClick={handleRefresh}
              className="btn-primary w-full"
            >
              Generate Report
            </button>
          </div>
        </div>
      </motion.div>

      {/* Tab Navigation */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="card"
      >
        <div className="border-b border-gray-200 mb-6">
          <nav className="-mb-px flex space-x-8">
            <button
              onClick={() => setActiveTab('fulfillment-errors')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'fulfillment-errors'
                  ? 'border-shopify-500 text-shopify-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              Fulfillment Errors
            </button>
            <button
              onClick={() => setActiveTab('oos-orders')}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === 'oos-orders'
                  ? 'border-shopify-500 text-shopify-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              Out of Stock Orders
            </button>
          </nav>
        </div>

        {/* Fulfillment Errors Tab */}
        {activeTab === 'fulfillment-errors' && (
          <div>
            {fulfillmentLoading ? (
              <LoadingSpinner />
            ) : fulfillmentReport ? (
              <div className="space-y-6">
                {/* Summary Stats */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="bg-red-50 p-4 rounded-lg">
                    <div className="flex items-center">
                      <ExclamationTriangleIcon className="h-8 w-8 text-red-600" />
                      <div className="ml-3">
                        <p className="text-sm font-medium text-red-800">Total Errors</p>
                        <p className="text-2xl font-bold text-red-900">{fulfillmentReport.total_errors}</p>
                      </div>
                    </div>
                  </div>
                  <div className="bg-blue-50 p-4 rounded-lg">
                    <div className="flex items-center">
                      <DocumentArrowDownIcon className="h-8 w-8 text-blue-600" />
                      <div className="ml-3">
                        <p className="text-sm font-medium text-blue-800">Affected Locations</p>
                        <p className="text-2xl font-bold text-blue-900">{fulfillmentReport.location_errors.length}</p>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={() => exportToCSV(fulfillmentReport.detailed_logs, 'fulfillment-errors.csv')}
                      className="btn-secondary w-full flex items-center justify-center"
                    >
                      <DocumentArrowDownIcon className="h-4 w-4 mr-2" />
                      Export CSV
                    </button>
                  </div>
                </div>

                {/* Location Summary */}
                <div>
                  <h3 className="text-lg font-medium text-gray-900 mb-4">Errors by Location</h3>
                  <div className="space-y-4">
                    {fulfillmentReport.location_errors.map((location) => (
                      <div key={location.location_alias} className="border border-gray-200 rounded-lg p-4">
                        <div className="flex items-center justify-between mb-3">
                          <div>
                            <h4 className="font-medium text-gray-900">
                              Location Alias: {location.location_alias}
                            </h4>
                            <p className="text-sm text-gray-500">
                              Target Location: {location.target_location_id}
                            </p>
                          </div>
                          <span className="badge badge-red">
                            {location.error_count} error{location.error_count !== 1 ? 's' : ''}
                          </span>
                        </div>
                        <div className="bg-gray-50 p-3 rounded">
                          <p className="text-sm font-medium text-gray-700 mb-2">Recent Orders:</p>
                          <div className="space-y-1">
                            {location.orders.slice(0, 5).map((order, index) => (
                              <div key={index} className="text-sm text-gray-600">
                                {order.order_number} - {formatDate(order.created_at)} ({order.rule_name})
                              </div>
                            ))}
                            {location.orders.length > 5 && (
                              <div className="text-sm text-gray-500">
                                +{location.orders.length - 5} more orders
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Detailed Logs */}
                <div>
                  <h3 className="text-lg font-medium text-gray-900 mb-4">Detailed Error Logs</h3>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Order
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Date
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Rule
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Location
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Error
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {fulfillmentReport.detailed_logs.map((log) => (
                          <tr key={log.id}>
                            <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                              {log.order_number}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {formatDate(log.created_at)}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {log.rule_name}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {log.location_alias}
                            </td>
                            <td className="px-6 py-4 text-sm text-red-600">
                              {log.error_message}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                No fulfillment error data available
              </div>
            )}
          </div>
        )}

        {/* OOS Orders Tab */}
        {activeTab === 'oos-orders' && (
          <div>
            {oosLoading ? (
              <LoadingSpinner />
            ) : oosReport ? (
              <div className="space-y-6">
                {/* Summary Stats */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="bg-amber-50 p-4 rounded-lg">
                    <div className="flex items-center">
                      <ExclamationTriangleIcon className="h-8 w-8 text-amber-600" />
                      <div className="ml-3">
                        <p className="text-sm font-medium text-amber-800">OOS Orders</p>
                        <p className="text-2xl font-bold text-amber-900">{oosReport.total_oos_orders}</p>
                      </div>
                    </div>
                  </div>
                  <div className="bg-blue-50 p-4 rounded-lg">
                    <div className="flex items-center">
                      <DocumentArrowDownIcon className="h-8 w-8 text-blue-600" />
                      <div className="ml-3">
                        <p className="text-sm font-medium text-blue-800">Affected Locations</p>
                        <p className="text-2xl font-bold text-blue-900">{oosReport.location_summary.length}</p>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-end">
                    <button
                      onClick={() => exportToCSV(oosReport.orders, 'oos-orders.csv')}
                      className="btn-secondary w-full flex items-center justify-center"
                    >
                      <DocumentArrowDownIcon className="h-4 w-4 mr-2" />
                      Export CSV
                    </button>
                  </div>
                </div>

                {/* Location Summary */}
                <div>
                  <h3 className="text-lg font-medium text-gray-900 mb-4">OOS Orders by Location</h3>
                  <div className="space-y-4">
                    {oosReport.location_summary.map((location) => (
                      <div key={location.location_alias} className="border border-gray-200 rounded-lg p-4">
                        <div className="flex items-center justify-between mb-3">
                          <h4 className="font-medium text-gray-900">
                            Location: {location.location_alias}
                          </h4>
                          <span className="badge badge-amber">
                            {location.order_count} order{location.order_count !== 1 ? 's' : ''}
                          </span>
                        </div>
                        <div className="bg-gray-50 p-3 rounded">
                          <p className="text-sm font-medium text-gray-700 mb-2">Recent Orders:</p>
                          <div className="space-y-1">
                            {location.orders.slice(0, 5).map((order, index) => (
                              <div key={index} className="text-sm text-gray-600">
                                {order.order_number} - {formatDate(order.created_at)}
                              </div>
                            ))}
                            {location.orders.length > 5 && (
                              <div className="text-sm text-gray-500">
                                +{location.orders.length - 5} more orders
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* All OOS Orders */}
                <div>
                  <h3 className="text-lg font-medium text-gray-900 mb-4">All Out of Stock Orders</h3>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Order
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Date
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Rule
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                            Location
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {oosReport.orders.map((order, index) => (
                          <tr key={index}>
                            <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                              {order.order_number}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {formatDate(order.created_at)}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {order.rule_name}
                            </td>
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                              {order.location_alias}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500">
                No out of stock order data available
              </div>
            )}
          </div>
        )}
      </motion.div>
    </div>
  );
};

export default Reports;