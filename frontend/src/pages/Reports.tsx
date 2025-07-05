import React, { useState, useMemo } from 'react';
import { motion } from 'framer-motion';
import { useQuery, useMutation } from '@tanstack/react-query';
import { DocumentArrowDownIcon, ExclamationTriangleIcon, ChevronUpIcon, ChevronDownIcon, BeakerIcon, XMarkIcon, CalendarIcon, FunnelIcon } from '@heroicons/react/24/outline';
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
  const [productSortField, setProductSortField] = useState<string>('total_incidents');
  const [productSortOrder, setProductSortOrder] = useState<'asc' | 'desc'>('desc');

  // Preset date ranges
  const datePresets = [
    {
      label: 'Today',
      getValue: () => {
        const today = new Date();
        const dateStr = today.getFullYear() + '-' + 
          String(today.getMonth() + 1).padStart(2, '0') + '-' + 
          String(today.getDate()).padStart(2, '0');
        return {
          start: dateStr,
          end: dateStr
        };
      }
    },
    {
      label: 'Last 7 days',
      getValue: () => {
        const end = new Date();
        const start = new Date();
        start.setDate(start.getDate() - 6); // 7 days including today
        
        const endStr = end.getFullYear() + '-' + 
          String(end.getMonth() + 1).padStart(2, '0') + '-' + 
          String(end.getDate()).padStart(2, '0');
        const startStr = start.getFullYear() + '-' + 
          String(start.getMonth() + 1).padStart(2, '0') + '-' + 
          String(start.getDate()).padStart(2, '0');
        
        return {
          start: startStr,
          end: endStr
        };
      }
    },
    {
      label: 'Last 30 days',
      getValue: () => {
        const end = new Date();
        const start = new Date();
        start.setDate(start.getDate() - 29); // 30 days including today
        
        const endStr = end.getFullYear() + '-' + 
          String(end.getMonth() + 1).padStart(2, '0') + '-' + 
          String(end.getDate()).padStart(2, '0');
        const startStr = start.getFullYear() + '-' + 
          String(start.getMonth() + 1).padStart(2, '0') + '-' + 
          String(start.getDate()).padStart(2, '0');
        
        return {
          start: startStr,
          end: endStr
        };
      }
    },
    {
      label: 'This month',
      getValue: () => {
        const now = new Date();
        const start = new Date(now.getFullYear(), now.getMonth(), 1);
        
        const endStr = now.getFullYear() + '-' + 
          String(now.getMonth() + 1).padStart(2, '0') + '-' + 
          String(now.getDate()).padStart(2, '0');
        const startStr = start.getFullYear() + '-' + 
          String(start.getMonth() + 1).padStart(2, '0') + '-' + 
          String(start.getDate()).padStart(2, '0');
        
        return {
          start: startStr,
          end: endStr
        };
      }
    }
  ];

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

  const handleDatePreset = (preset: any) => {
    const dateRange = preset.getValue();
    setStartDate(dateRange.start);
    setEndDate(dateRange.end);
  };

  const handleClearFilters = () => {
    setRuleFilter('');
    setLocationFilter('');
    setSelectedOrders(new Set());
  };

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

  const handleProductSort = (field: string) => {
    if (productSortField === field) {
      setProductSortOrder(productSortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setProductSortField(field);
      setProductSortOrder('asc');
    }
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
      let aValue: any = a[sortField];
      let bValue: any = b[sortField];
      
      if (sortField === 'created_at') {
        aValue = new Date(aValue as string).getTime();
        bValue = new Date(bValue as string).getTime();
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

  const sortedProductAnalysisData = useMemo(() => {
    if (!productAnalysisData?.products) return [];
    
    return [...productAnalysisData.products].sort((a, b) => {
      let aValue = a[productSortField];
      let bValue = b[productSortField];
      
      // Handle different data types
      if (typeof aValue === 'string') {
        aValue = aValue.toLowerCase();
        bValue = bValue.toLowerCase();
      }
      
      // Handle null/undefined values
      if (aValue == null) aValue = '';
      if (bValue == null) bValue = '';
      
      if (productSortOrder === 'asc') {
        return aValue < bValue ? -1 : aValue > bValue ? 1 : 0;
      } else {
        return aValue > bValue ? -1 : aValue < bValue ? 1 : 0;
      }
    });
  }, [productAnalysisData?.products, productSortField, productSortOrder]);

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
    <div className="space-y-6">
      {/* Page Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Reports</h1>
        <p className="text-gray-600">
          Analyze out-of-stock orders to optimize inventory management.
        </p>
      </motion.div>

      {/* Unified Control Panel */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-white rounded-lg shadow-sm border border-gray-200"
      >
        <div className="p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-lg font-semibold text-gray-900 flex items-center">
              <CalendarIcon className="h-5 w-5 mr-2 text-gray-500" />
              Report Configuration
            </h2>
            <div className="flex items-center space-x-2">
              {(startDate || endDate || ruleFilter || locationFilter) && (
                <button
                  onClick={handleClearFilters}
                  className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
                >
                  <XMarkIcon className="h-4 w-4 mr-1" />
                  Clear Filters
                </button>
              )}
              <button
                onClick={handleRefresh}
                disabled={oosLoading}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 disabled:opacity-50"
              >
                {oosLoading ? (
                  <LoadingSpinner size="sm" className="mr-2" />
                ) : (
                  <DocumentArrowDownIcon className="h-4 w-4 mr-2" />
                )}
                Generate Report
              </button>
            </div>
          </div>

          {/* Date Range Section */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Date Inputs */}
            <div className="space-y-4">
              <h3 className="text-sm font-medium text-gray-900">Date Range</h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Start Date</label>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm text-sm focus:outline-none focus:ring-shopify-500 focus:border-shopify-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">End Date</label>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm text-sm focus:outline-none focus:ring-shopify-500 focus:border-shopify-500"
                  />
                </div>
              </div>
            </div>

            {/* Quick Date Presets */}
            <div className="space-y-4">
              <h3 className="text-sm font-medium text-gray-900">Quick Select</h3>
              <div className="grid grid-cols-2 gap-2">
                {datePresets.map((preset, index) => (
                  <button
                    key={index}
                    onClick={() => handleDatePreset(preset)}
                    className="px-3 py-2 text-xs font-medium text-gray-700 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Filters Section */}
          <div className="border-t border-gray-200 pt-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-gray-900 flex items-center">
                <FunnelIcon className="h-4 w-4 mr-2 text-gray-500" />
                Data Filters
              </h3>
              {(ruleFilter || locationFilter) && (
                <div className="flex items-center space-x-2">
                  {ruleFilter && (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                      Rule: {ruleFilter}
                      <button
                        onClick={() => setRuleFilter('')}
                        className="ml-1.5 h-3 w-3 rounded-full inline-flex items-center justify-center text-blue-400 hover:bg-blue-200 hover:text-blue-500"
                      >
                        <XMarkIcon className="h-2 w-2" />
                      </button>
                    </span>
                  )}
                  {locationFilter && (
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                      Location: {locationFilter}
                      <button
                        onClick={() => setLocationFilter('')}
                        className="ml-1.5 h-3 w-3 rounded-full inline-flex items-center justify-center text-green-400 hover:bg-green-200 hover:text-green-500"
                      >
                        <XMarkIcon className="h-2 w-2" />
                      </button>
                    </span>
                  )}
                </div>
              )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Filter by Rule</label>
                <select
                  value={ruleFilter}
                  onChange={(e) => setRuleFilter(e.target.value)}
                  className="block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm text-sm focus:outline-none focus:ring-shopify-500 focus:border-shopify-500"
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
                <label className="block text-xs font-medium text-gray-700 mb-1">Filter by Location</label>
                <select
                  value={locationFilter}
                  onChange={(e) => setLocationFilter(e.target.value)}
                  className="block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm text-sm focus:outline-none focus:ring-shopify-500 focus:border-shopify-500"
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
          </div>
        </div>
      </motion.div>

      {/* Results Section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="bg-white rounded-lg shadow-sm border border-gray-200"
      >
        <div className="p-6">
          {oosLoading ? (
            <div className="flex items-center justify-center py-12">
              <LoadingSpinner />
            </div>
          ) : oosReport ? (
            <div className="space-y-6">
              {/* Enhanced Action Bar */}
              <div className="border-b border-gray-200 pb-4">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between space-y-3 sm:space-y-0">
                  <div className="flex flex-col sm:flex-row sm:items-center space-y-2 sm:space-y-0 sm:space-x-4">
                    <h3 className="text-lg font-medium text-gray-900">
                      Out of Stock Orders
                    </h3>
                    {filteredAndSortedOrders.length > 0 && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 w-fit">
                        {filteredAndSortedOrders.length} orders
                      </span>
                    )}
                  </div>
                  <div className="flex flex-col sm:flex-row items-stretch sm:items-center space-y-2 sm:space-y-0 sm:space-x-2">
                    <button
                      onClick={() => exportToCSV(filteredAndSortedOrders, 'oos-orders.csv')}
                      disabled={filteredAndSortedOrders.length === 0}
                      className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <DocumentArrowDownIcon className="h-4 w-4 mr-1.5" />
                      Export All
                    </button>
                    {selectedOrders.size > 0 && (
                      <>
                        <button
                          onClick={() => exportToCSV(
                            filteredAndSortedOrders.filter(order => selectedOrders.has(order.order_number)),
                            'selected-oos-orders.csv'
                          )}
                          className="inline-flex items-center px-3 py-1.5 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
                        >
                          <DocumentArrowDownIcon className="h-4 w-4 mr-1.5" />
                          Export Selected ({selectedOrders.size})
                        </button>
                        <button
                          onClick={handleAnalyzeSelected}
                          disabled={analyzeOrders.isPending}
                          className="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 disabled:opacity-50"
                        >
                          {analyzeOrders.isPending ? (
                            <LoadingSpinner size="sm" className="mr-1.5" />
                          ) : (
                            <BeakerIcon className="h-4 w-4 mr-1.5" />
                          )}
                          Analyze Products
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* Data Table */}
              {filteredAndSortedOrders.length > 0 ? (
                <div className="overflow-x-auto border border-gray-200 rounded-lg">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                          <input
                            type="checkbox"
                            checked={selectedOrders.size === filteredAndSortedOrders.length && filteredAndSortedOrders.length > 0}
                            onChange={handleSelectAll}
                            className="h-4 w-4 text-shopify-600 focus:ring-shopify-500 border-gray-300 rounded"
                          />
                        </th>
                        <th 
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                          onClick={() => handleSort('order_number')}
                        >
                          <div className="flex items-center">
                            Order Number
                            {sortField === 'order_number' && (
                              sortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                            )}
                          </div>
                        </th>
                        <th 
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                          onClick={() => handleSort('created_at')}
                        >
                          <div className="flex items-center">
                            Date Created
                            {sortField === 'created_at' && (
                              sortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                            )}
                          </div>
                        </th>
                        <th 
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                          onClick={() => handleSort('rule_name')}
                        >
                          <div className="flex items-center">
                            Processing Rule
                            {sortField === 'rule_name' && (
                              sortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                            )}
                          </div>
                        </th>
                        <th 
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                          onClick={() => handleSort('location_alias')}
                        >
                          <div className="flex items-center">
                            Target Location
                            {sortField === 'location_alias' && (
                              sortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                            )}
                          </div>
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {filteredAndSortedOrders.map((order, index) => (
                        <tr key={index} className="hover:bg-blue-50 transition-colors cursor-pointer" onClick={() => handleSelectOrder(order.order_number)}>
                          <td className="px-4 py-4 whitespace-nowrap">
                            <input
                              type="checkbox"
                              checked={selectedOrders.has(order.order_number)}
                              onChange={() => handleSelectOrder(order.order_number)}
                              onClick={(e) => e.stopPropagation()}
                              className="h-4 w-4 text-shopify-600 focus:ring-shopify-500 border-gray-300 rounded"
                            />
                          </td>
                          <td className="px-4 py-4 whitespace-nowrap">
                            <div className="text-sm font-medium text-gray-900">{order.order_number}</div>
                          </td>
                          <td className="px-4 py-4 whitespace-nowrap">
                            <div className="text-sm text-gray-500">{formatDate(order.created_at)}</div>
                          </td>
                          <td className="px-4 py-4 whitespace-nowrap">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                              {order.rule_name}
                            </span>
                          </td>
                          <td className="px-4 py-4 whitespace-nowrap">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                              {order.location_alias}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-center py-12">
                  <ExclamationTriangleIcon className="mx-auto h-12 w-12 text-gray-400" />
                  <h3 className="mt-2 text-sm font-medium text-gray-900">No orders found</h3>
                  <p className="mt-1 text-sm text-gray-500">
                    {(ruleFilter || locationFilter) 
                      ? 'Try adjusting your filters to see more results.'
                      : 'No out-of-stock orders found for the selected date range.'
                    }
                  </p>
                  {(ruleFilter || locationFilter) && (
                    <div className="mt-4">
                      <button
                        onClick={handleClearFilters}
                        className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
                      >
                        Clear Filters
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="text-center py-12">
              <ExclamationTriangleIcon className="mx-auto h-12 w-12 text-gray-400" />
              <h3 className="mt-2 text-sm font-medium text-gray-900">No data available</h3>
              <p className="mt-1 text-sm text-gray-500">
                Set a date range and click "Generate Report" to analyze out-of-stock orders.
              </p>
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
            className="bg-white rounded-lg p-4 sm:p-6 max-w-6xl w-full max-h-[90vh] overflow-hidden"
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

            <div className="mb-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
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
                    <th 
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                      onClick={() => handleProductSort('product_title')}
                    >
                      <div className="flex items-center">
                        Product
                        {productSortField === 'product_title' && (
                          productSortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                        )}
                      </div>
                    </th>
                    <th 
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                      onClick={() => handleProductSort('sku')}
                    >
                      <div className="flex items-center">
                        SKU
                        {productSortField === 'sku' && (
                          productSortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                        )}
                      </div>
                    </th>
                    <th 
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                      onClick={() => handleProductSort('vendor')}
                    >
                      <div className="flex items-center">
                        Vendor
                        {productSortField === 'vendor' && (
                          productSortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                        )}
                      </div>
                    </th>
                    <th 
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                      onClick={() => handleProductSort('total_incidents')}
                    >
                      <div className="flex items-center">
                        Incidents
                        {productSortField === 'total_incidents' && (
                          productSortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                        )}
                      </div>
                    </th>
                    <th 
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 transition-colors"
                      onClick={() => handleProductSort('total_quantity_affected')}
                    >
                      <div className="flex items-center">
                        Total Qty
                        {productSortField === 'total_quantity_affected' && (
                          productSortOrder === 'asc' ? <ChevronUpIcon className="ml-1 h-4 w-4" /> : <ChevronDownIcon className="ml-1 h-4 w-4" />
                        )}
                      </div>
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Locations
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {sortedProductAnalysisData.map((product: any, index: number) => (
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

            <div className="mt-4 flex flex-col sm:flex-row sm:justify-end space-y-2 sm:space-y-0 sm:space-x-2">
              <button
                onClick={() => exportToCSV(sortedProductAnalysisData, 'product-analysis.csv')}
                className="inline-flex items-center justify-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
              >
                <DocumentArrowDownIcon className="h-4 w-4 mr-2" />
                Export CSV
              </button>
              <button
                onClick={() => setShowProductAnalysis(false)}
                className="inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500"
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