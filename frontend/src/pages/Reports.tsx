import React, { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import { useQuery, useMutation } from '@tanstack/react-query';
import { DocumentArrowDownIcon, ExclamationTriangleIcon, ChevronUpIcon, ChevronDownIcon, BeakerIcon } from '@heroicons/react/24/outline';
import toast from 'react-hot-toast';
import api from '../utils/api';
import LoadingSpinner from '../components/LoadingSpinner';

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
  orders: OOSOrder[];
}

type SortField = 'order_number' | 'created_at' | 'rule_name' | 'location_alias';
type SortOrder = 'asc' | 'desc';

const Reports: React.FC = () => {
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');
  const [ruleFilter, setRuleFilter] = useState<string>('');
  const [locationFilter, setLocationFilter] = useState<string>('');
  const [sortField, setSortField] = useState<SortField>('created_at');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [selectedOrders, setSelectedOrders] = useState<Set<string>>(new Set());
  const [showProductAnalysis, setShowProductAnalysis] = useState(false);
  const [productAnalysisData, setProductAnalysisData] = useState<any>(null);

  // Build query params for date filtering
  const getDateParams = () => {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate + 'T00:00:00Z');
    if (endDate) params.append('end_date', endDate + 'T23:59:59Z');
    return params.toString();
  };

  // Fetch OOS orders report
  const { data: oosReport, isLoading: oosLoading, refetch: refetchOOS } = useQuery<OOSReport>({
    queryKey: ['oos-orders-report', startDate, endDate],
    queryFn: async () => {
      const params = getDateParams();
      const response = await api.get(`/reports/oos-orders?${params}`);
      return response.data;
    },
  });

  // Analyze selected orders mutation
  const analyzeOrders = useMutation({
    mutationFn: async (orderIds: string[]) => {
      const response = await api.post('/reports/oos-products/analyze', { order_ids: orderIds });
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Analysis completed: ${data.unique_products} unique products found`);
      setProductAnalysisData(data);
      setShowProductAnalysis(true);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to analyze orders');
    },
  });

  const handleRefresh = () => {
    toast.loading('Generating report...', { id: 'report-loading' });
    
    refetchOOS().finally(() => {
      toast.dismiss('report-loading');
      toast.success('OOS orders report updated');
    });
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortOrder('asc');
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
    if (selectedOrders.size === filteredAndSortedOrders.length && filteredAndSortedOrders.length > 0) {
      setSelectedOrders(new Set());
    } else {
      const allOrderIds = new Set(filteredAndSortedOrders.map(order => order.order_number));
      setSelectedOrders(allOrderIds);
    }
  };

  const handleAnalyzeSelected = () => {
    if (selectedOrders.size === 0) {
      toast.error('Please select at least one order to analyze');
      return;
    }
    analyzeOrders.mutate(Array.from(selectedOrders));
  };

  const filteredAndSortedOrders = useMemo(() => {
    if (!oosReport?.orders) return [];
    
    let filtered = oosReport.orders;
    
    // Apply filters
    if (ruleFilter) {
      filtered = filtered.filter(order => 
        order.rule_name.toLowerCase().includes(ruleFilter.toLowerCase())
      );
    }
    
    if (locationFilter) {
      filtered = filtered.filter(order => 
        order.location_alias.toLowerCase().includes(locationFilter.toLowerCase())
      );
    }
    
    // Apply sorting
    return filtered.sort((a, b) => {
      let aValue = a[sortField];
      let bValue = b[sortField];
      
      if (sortField === 'created_at') {
        aValue = new Date(aValue).getTime();
        bValue = new Date(bValue).getTime();
      }
      
      if (sortOrder === 'asc') {
        return aValue < bValue ? -1 : aValue > bValue ? 1 : 0;
      } else {
        return aValue > bValue ? -1 : aValue < bValue ? 1 : 0;
      }
    });
  }, [oosReport?.orders, ruleFilter, locationFilter, sortField, sortOrder]);

  const uniqueRules = useMemo(() => {
    if (!oosReport?.orders) return [];
    return [...new Set(oosReport.orders.map(order => order.rule_name))].sort();
  }, [oosReport?.orders]);

  const uniqueLocations = useMemo(() => {
    if (!oosReport?.orders) return [];
    return [...new Set(oosReport.orders.map(order => order.location_alias))].sort();
  }, [oosReport?.orders]);

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
          Analyze out-of-stock orders to optimize inventory management.
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
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="input"
            />
          </div>
          <div>
            <label className="label">End Date</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="input"
            />
          </div>
          <div className="flex items-end">
            <button
              onClick={handleRefresh}
              className="inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 w-full"
            >
              Generate Report
            </button>
          </div>
        </div>
      </motion.div>

      {/* Out of Stock Orders */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="card"
      >
        <div className="mb-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Out of Stock Orders</h2>
        </div>

        <div>
          {oosLoading ? (
            <LoadingSpinner />
          ) : oosReport ? (
            <div className="space-y-6">
              {/* Summary Stats */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-amber-50 p-4 rounded-lg">
                  <div className="flex items-center">
                    <ExclamationTriangleIcon className="h-8 w-8 text-amber-600" />
                    <div className="ml-3">
                      <p className="text-sm font-medium text-amber-800">Total OOS Orders</p>
                      <p className="text-2xl font-bold text-amber-900">{oosReport.total_oos_orders}</p>
                    </div>
                  </div>
                </div>
                <div className="flex items-end">
                  <button
                    onClick={() => exportToCSV(filteredAndSortedOrders, 'oos-orders.csv')}
                    className="inline-flex items-center justify-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 w-full"
                  >
                    <DocumentArrowDownIcon className="h-4 w-4 mr-2" />
                    Export CSV
                  </button>
                </div>
              </div>

              {/* Filters */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="label">Filter by Rule</label>
                  <select
                    value={ruleFilter}
                    onChange={(e) => setRuleFilter(e.target.value)}
                    className="input"
                  >
                    <option value="">All Rules</option>
                    {uniqueRules.map((rule) => (
                      <option key={rule} value={rule}>
                        {rule}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label">Filter by Location</label>
                  <select
                    value={locationFilter}
                    onChange={(e) => setLocationFilter(e.target.value)}
                    className="input"
                  >
                    <option value="">All Locations</option>
                    {uniqueLocations.map((location) => (
                      <option key={location} value={location}>
                        {location}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Orders Table */}
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-medium text-gray-900">Orders ({filteredAndSortedOrders.length})</h3>
                </div>

                {/* Selection Action Bar */}
                {selectedOrders.size > 0 && (
                  <div className="mb-4 bg-gray-50 p-4 rounded-lg border border-gray-200">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-gray-700">
                        {selectedOrders.size} order{selectedOrders.size !== 1 ? 's' : ''} selected
                      </span>
                      <div className="flex space-x-2">
                        <button
                          onClick={() => exportToCSV(
                            filteredAndSortedOrders.filter(order => selectedOrders.has(order.order_number)),
                            'selected-oos-orders.csv'
                          )}
                          className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
                        >
                          <DocumentArrowDownIcon className="h-4 w-4 mr-2" />
                          Export Selected
                        </button>
                        <button
                          onClick={handleAnalyzeSelected}
                          disabled={analyzeOrders.isPending}
                          className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 disabled:opacity-50"
                        >
                          {analyzeOrders.isPending ? (
                            <LoadingSpinner size="sm" className="mr-2" />
                          ) : (
                            <BeakerIcon className="h-4 w-4 mr-2" />
                          )}
                          Analyze Products
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          <input
                            type="checkbox"
                            checked={selectedOrders.size === filteredAndSortedOrders.length && filteredAndSortedOrders.length > 0}
                            onChange={handleSelectAll}
                            className="h-4 w-4 text-shopify-600 focus:ring-shopify-500 border-gray-300 rounded"
                          />
                        </th>
                        <th 
                          className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                          onClick={() => handleSort('order_number')}
                        >
                          <div className="flex items-center">
                            Order
                            {sortField === 'order_number' && (
                              sortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                            )}
                          </div>
                        </th>
                        <th 
                          className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                          onClick={() => handleSort('created_at')}
                        >
                          <div className="flex items-center">
                            Date
                            {sortField === 'created_at' && (
                              sortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                            )}
                          </div>
                        </th>
                        <th 
                          className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                          onClick={() => handleSort('rule_name')}
                        >
                          <div className="flex items-center">
                            Rule
                            {sortField === 'rule_name' && (
                              sortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                            )}
                          </div>
                        </th>
                        <th 
                          className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100"
                          onClick={() => handleSort('location_alias')}
                        >
                          <div className="flex items-center">
                            Location
                            {sortField === 'location_alias' && (
                              sortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                            )}
                          </div>
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {filteredAndSortedOrders.map((order, index) => (
                        <tr key={index} className="hover:bg-gray-50">
                          <td className="px-6 py-4 whitespace-nowrap">
                            <input
                              type="checkbox"
                              checked={selectedOrders.has(order.order_number)}
                              onChange={() => handleSelectOrder(order.order_number)}
                              className="h-4 w-4 text-shopify-600 focus:ring-shopify-500 border-gray-300 rounded"
                            />
                          </td>
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
      </motion.div>

      {/* Product Analysis Results Modal */}
      {showProductAnalysis && productAnalysisData && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="fixed inset-0 bg-gray-500 bg-opacity-75 flex items-center justify-center p-4 z-50"
          onClick={() => setShowProductAnalysis(false)}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="bg-white rounded-lg p-6 max-w-6xl w-full max-h-[90vh] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold text-gray-900">Product Analysis Results</h2>
              <button
                onClick={() => setShowProductAnalysis(false)}
                className="text-gray-400 hover:text-gray-500"
              >
                <span className="sr-only">Close</span>
                <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="mb-4 grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-red-50 p-4 rounded-lg">
                <div className="flex items-center">
                  <ExclamationTriangleIcon className="h-8 w-8 text-red-600" />
                  <div className="ml-3">
                    <p className="text-sm font-medium text-red-800">Total OOS Incidents</p>
                    <p className="text-2xl font-bold text-red-900">{productAnalysisData.total_oos_incidents}</p>
                  </div>
                </div>
              </div>
              <div className="bg-blue-50 p-4 rounded-lg">
                <div className="flex items-center">
                  <BeakerIcon className="h-8 w-8 text-blue-600" />
                  <div className="ml-3">
                    <p className="text-sm font-medium text-blue-800">Unique Products</p>
                    <p className="text-2xl font-bold text-blue-900">{productAnalysisData.unique_products}</p>
                  </div>
                </div>
              </div>
              <div className="bg-amber-50 p-4 rounded-lg">
                <div className="flex items-center">
                  <DocumentArrowDownIcon className="h-8 w-8 text-amber-600" />
                  <div className="ml-3">
                    <p className="text-sm font-medium text-amber-800">Orders Analyzed</p>
                    <p className="text-2xl font-bold text-amber-900">{productAnalysisData.selected_orders || selectedOrders.size}</p>
                  </div>
                </div>
              </div>
            </div>

            <div className="overflow-y-auto max-h-[60vh]">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Product
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      SKU
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Vendor
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Incidents
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Total Qty
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Locations
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {productAnalysisData.products?.map((product: any, index: number) => (
                    <tr key={index} className="hover:bg-gray-50">
                      <td className="px-6 py-4 text-sm">
                        <div>
                          <div className="font-medium text-gray-900">{product.product_title}</div>
                          {product.variant_title && (
                            <div className="text-gray-500">{product.variant_title}</div>
                          )}
                          {product.product_type && (
                            <div className="text-xs text-gray-400">{product.product_type}</div>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {product.sku || '-'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {product.vendor || '-'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-red-600">
                        {product.total_incidents}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                        {product.total_quantity_affected}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-500">
                        <div className="max-w-xs">
                          {product.locations_affected?.slice(0, 2).map((location: string, idx: number) => (
                            <span key={idx} className="inline-block bg-gray-100 rounded-full px-2 py-1 text-xs mr-1 mb-1">
                              {location}
                            </span>
                          ))}
                          {product.locations_affected?.length > 2 && (
                            <span className="text-xs text-gray-400">
                              +{product.locations_affected.length - 2} more
                            </span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex justify-end space-x-2">
              <button
                onClick={() => exportToCSV(productAnalysisData.products, 'product-analysis.csv')}
                className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
              >
                <DocumentArrowDownIcon className="h-4 w-4 mr-2" />
                Export CSV
              </button>
              <button
                onClick={() => setShowProductAnalysis(false)}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
              >
                Close
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </div>
  );
};

export default Reports;