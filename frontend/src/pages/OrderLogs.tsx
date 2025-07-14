import React, { useState, useMemo, useEffect } from "react";
import { motion } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { formatDate } from "../utils/dateFormat";
import { useTimezone } from "../contexts/TimezoneContext";
import {
  CheckCircleIcon,
  XCircleIcon,
  InformationCircleIcon,
  ArrowPathIcon,
  PlayIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ChevronUpIcon,
  ChevronDownIcon as SortDownIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";
import api from "../utils/api";
import LoadingSpinner from "../components/LoadingSpinner";

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

interface GroupedOrderLog {
  order_number: string;
  order_id: string;
  store_name: string;
  logs: OrderLog[];
  latest_date: string;
  has_failed: boolean;
  has_success: boolean;
}

type SortField =
  | "order_number"
  | "store_name"
  | "latest_date"
  | "status"
  | "action_count";
type SortDirection = "asc" | "desc";

const OrderLogs: React.FC = () => {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [storeFilter, setStoreFilter] = useState<string>("");
  const [ruleFilter, setRuleFilter] = useState<string>("");
  const [dateFilter, setDateFilter] = useState<string>("");
  const [customDateFrom, setCustomDateFrom] = useState<string>("");
  const [customDateTo, setCustomDateTo] = useState<string>("");
  const [selectedOrders, setSelectedOrders] = useState<Set<string>>(new Set());
  const [selectedRule, setSelectedRule] = useState<string>("");
  const [expandedOrders, setExpandedOrders] = useState<Set<string>>(new Set());
  const [sortField, setSortField] = useState<SortField>("latest_date");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [isAllResultsSelected, setIsAllResultsSelected] = useState<boolean>(false);
  const [allResultsCount, setAllResultsCount] = useState<number>(0);
  const [showGlobalSelection, setShowGlobalSelection] = useState<boolean>(false);

  const queryClient = useQueryClient();
  const { timezone, dateFormat } = useTimezone();

  // Calculate date range based on filter with proper timezone handling
  const getDateRange = (filter: string) => {
    const now = new Date();

    switch (filter) {
      case "today":
        // Get start and end of today in user's timezone, then convert to UTC
        const todayStart = new Date(
          now.getFullYear(),
          now.getMonth(),
          now.getDate(),
        );
        const todayEnd = new Date(
          now.getFullYear(),
          now.getMonth(),
          now.getDate(),
          23,
          59,
          59,
          999,
        );
        return {
          from: todayStart.toISOString(),
          to: todayEnd.toISOString(),
        };
      case "week":
        // Calculate week start (Sunday) in user's timezone
        const weekStart = new Date(
          now.getFullYear(),
          now.getMonth(),
          now.getDate(),
        );
        weekStart.setDate(weekStart.getDate() - weekStart.getDay());
        weekStart.setHours(0, 0, 0, 0);
        return {
          from: weekStart.toISOString(),
          to: now.toISOString(),
        };
      case "month":
        // Start of current month in user's timezone
        const monthStart = new Date(
          now.getFullYear(),
          now.getMonth(),
          1,
          0,
          0,
          0,
          0,
        );
        return {
          from: monthStart.toISOString(),
          to: now.toISOString(),
        };
      case "year":
        // Start of current year in user's timezone
        const yearStart = new Date(now.getFullYear(), 0, 1, 0, 0, 0, 0);
        return {
          from: yearStart.toISOString(),
          to: now.toISOString(),
        };
      case "custom":
        if (!customDateFrom || !customDateTo) {
          return { from: null, to: null };
        }

        // Parse dates in user's local timezone and convert to UTC
        // This ensures the date boundaries represent the actual day in user's timezone
        const fromDate = new Date(customDateFrom + "T00:00:00");
        const toDate = new Date(customDateTo + "T23:59:59");

        return {
          from: fromDate.toISOString(),
          to: toDate.toISOString(),
        };
      default:
        return { from: null, to: null };
    }
  };

  // Debounce search input
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      setSearchQuery(searchInput);
      setPage(1); // Reset to first page when search changes
    }, 500); // 500ms delay

    return () => clearTimeout(timeoutId);
  }, [searchInput]);

  // Reset global selection when filters change
  useEffect(() => {
    setSelectedOrders(new Set());
    setShowGlobalSelection(false);
    setIsAllResultsSelected(false);
    setAllResultsCount(0);
  }, [
    searchQuery,
    statusFilter,
    storeFilter,
    ruleFilter,
    dateFilter,
    customDateFrom,
    customDateTo,
  ]);

  const { data: stores } = useQuery({
    queryKey: ["stores"],
    queryFn: async () => {
      const response = await api.get("/stores");
      return response.data;
    },
  });

  const { data: rules } = useQuery({
    queryKey: ["rules"],
    queryFn: async () => {
      const response = await api.get("/rules");
      return response.data;
    },
  });

  const { data, isLoading, refetch } = useQuery<LogsResponse>({
    queryKey: [
      "order-logs",
      page,
      searchQuery,
      statusFilter,
      storeFilter,
      ruleFilter,
      dateFilter,
      customDateFrom,
      customDateTo,
      sortField,
      sortDirection,
    ],
    queryFn: async () => {
      const params = new URLSearchParams({
        page: page.toString(),
        per_page: "50",
        sort_field: sortField,
        sort_direction: sortDirection,
      });

      if (searchQuery) params.append("search", searchQuery);
      if (statusFilter) params.append("status", statusFilter);
      if (storeFilter) params.append("store_id", storeFilter);
      if (ruleFilter) params.append("rule_id", ruleFilter);

      // Add date filtering
      const dateRange = getDateRange(dateFilter);
      if (dateRange.from) params.append("date_from", dateRange.from);
      if (dateRange.to) params.append("date_to", dateRange.to);

      const response = await api.get(`/order-logs?${params}`);
      return response.data;
    },
  });

  // Query for all order IDs (for global selection)
  const { data: allOrderIdsData, refetch: refetchAllOrderIds } = useQuery({
    queryKey: [
      "order-logs-all-ids",
      searchQuery,
      statusFilter,
      storeFilter,
      ruleFilter,
      dateFilter,
      customDateFrom,
      customDateTo,
    ],
    queryFn: async () => {
      const params = new URLSearchParams();

      if (searchQuery) params.append("search", searchQuery);
      if (statusFilter) params.append("status", statusFilter);
      if (storeFilter) params.append("store_id", storeFilter);
      if (ruleFilter) params.append("rule_id", ruleFilter);

      // Add date filtering
      const dateRange = getDateRange(dateFilter);
      if (dateRange.from) params.append("date_from", dateRange.from);
      if (dateRange.to) params.append("date_to", dateRange.to);

      const response = await api.get(`/order-logs/all-order-ids?${params}`);
      return response.data;
    },
    enabled: showGlobalSelection, // Only fetch when global selection is needed
  });

  // Group logs (sorting is now handled by backend)
  const groupedLogs = useMemo(() => {
    if (!data?.logs) return [];

    // Group logs by order number - logs are returned in backend sort order
    const grouped = new Map<string, GroupedOrderLog>();

    data.logs.forEach((log) => {
      const key = log.order_number;
      if (!grouped.has(key)) {
        grouped.set(key, {
          order_number: log.order_number,
          order_id: log.order_id,
          store_name: log.store_name,
          logs: [],
          latest_date: log.created_at,
          has_failed: false,
          has_success: false,
        });
      }

      const group = grouped.get(key)!;
      group.logs.push(log);

      // Update latest date
      if (new Date(log.created_at) > new Date(group.latest_date)) {
        group.latest_date = log.created_at;
      }

      // Track status flags - only count actual failures, not info/skipped
      if (log.status === "error" || log.status === "failed")
        group.has_failed = true;
      if (log.status === "match" || log.status === "success")
        group.has_success = true;
      // Note: 'info' and 'skipped' are neutral and don't affect group status
    });

    // Convert to array - maintain backend sort order
    const groupedArray = Array.from(grouped.values());

    return groupedArray;
  }, [data?.logs]);

  const retryOrders = useMutation({
    mutationFn: async (data: { order_ids: string[]; rule_id?: number }) => {
      const response = await api.post("/order-logs/retry", data);
      return response.data;
    },
    onSuccess: (result) => {
      toast.success(
        `Retry completed: ${result.processed_count} processed, ${result.failed_count} failed`,
      );
      queryClient.invalidateQueries({ queryKey: ["order-logs"] });
      queryClient.invalidateQueries({ queryKey: ["order-logs-all-ids"] });
      setSelectedOrders(new Set());
      setSelectedRule("");
      setShowGlobalSelection(false);
      setIsAllResultsSelected(false);
      setAllResultsCount(0);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to retry orders");
    },
  });

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "match":
        return <CheckCircleIcon className="h-5 w-5 text-green-500" />;
      case "skipped":
        return <InformationCircleIcon className="h-5 w-5 text-gray-500" />;
      case "error":
        return <XCircleIcon className="h-5 w-5 text-red-500" />;
      // Legacy status support
      case "success":
        return <CheckCircleIcon className="h-5 w-5 text-green-500" />;
      case "failed":
        return <XCircleIcon className="h-5 w-5 text-red-500" />;
      case "info":
        return <InformationCircleIcon className="h-5 w-5 text-blue-500" />;
      default:
        return <InformationCircleIcon className="h-5 w-5 text-blue-500" />;
    }
  };

  const getActionLabel = (action: string) => {
    if (action.startsWith("applied_rule_")) {
      return "Applied Rule";
    }
    switch (action) {
      case "no_rules_matched":
        return "No Rules Matched";
      case "processing_error":
        return "Processing Error";
      case "retry_processing":
        return "Retry Processing";
      default:
        return action;
    }
  };

  const getGroupStatus = (group: GroupedOrderLog) => {
    if (group.has_failed) return "error";
    if (group.has_success) return "match";
    return "skipped";
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDirection("asc");
    }
    // Reset to page 1 when sorting changes
    setPage(1);
  };

  const getSortIcon = (field: SortField) => {
    if (sortField !== field) {
      return <ChevronUpIcon className="h-4 w-4 text-gray-400" />;
    }
    return sortDirection === "asc" ? (
      <ChevronUpIcon className="h-4 w-4 text-gray-700" />
    ) : (
      <SortDownIcon className="h-4 w-4 text-gray-700" />
    );
  };

  const toggleOrderExpansion = (orderNumber: string) => {
    const newExpanded = new Set(expandedOrders);
    if (newExpanded.has(orderNumber)) {
      newExpanded.delete(orderNumber);
    } else {
      newExpanded.add(orderNumber);
    }
    setExpandedOrders(newExpanded);
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
    if (selectedOrders.size === groupedLogs.length && !isAllResultsSelected) {
      // If all current page orders are selected, deselect all
      setSelectedOrders(new Set());
      setShowGlobalSelection(false);
      setIsAllResultsSelected(false);
    } else {
      // Select all orders on current page
      const allOrderIds = new Set(groupedLogs.map((group) => group.order_id));
      setSelectedOrders(allOrderIds);
      setShowGlobalSelection(true);
      setIsAllResultsSelected(false);
    }
  };

  const handleGlobalSelection = () => {
    if (isAllResultsSelected) {
      // Deselect global, go back to page selection
      const allOrderIds = new Set(groupedLogs.map((group) => group.order_id));
      setSelectedOrders(allOrderIds);
      setIsAllResultsSelected(false);
    } else {
      // Select all results globally
      if (allOrderIdsData) {
        setSelectedOrders(new Set(allOrderIdsData.order_ids));
        setAllResultsCount(allOrderIdsData.total_count);
        setIsAllResultsSelected(true);
      }
    }
  };

  const handleRetryWithAllRules = () => {
    if (selectedOrders.size === 0) return;
    retryOrders.mutate({
      order_ids: Array.from(selectedOrders),
    });
  };

  const handleRetryWithSpecificRule = () => {
    if (selectedOrders.size === 0 || !selectedRule) return;
    retryOrders.mutate({
      order_ids: Array.from(selectedOrders),
      rule_id: parseInt(selectedRule),
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
      <div className="card">
        <div className="px-4 py-5 sm:p-6">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h3 className="text-lg font-medium leading-6 text-gray-900 dark:text-dark-800">
                Order Processing Logs
              </h3>
              <p className="mt-1 text-sm text-gray-500 dark:text-dark-400">
                View all order processing activities and rule applications
              </p>
            </div>
            <button 
              onClick={() => {
                refetch();
                refetchAllOrderIds();
              }} 
              className="btn-secondary"
            >
              <ArrowPathIcon className="h-4 w-4 mr-2" />
              Refresh
            </button>
          </div>

          {/* Filters */}
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-6">
            <div>
              <label
                htmlFor="date-filter"
                className="block text-sm font-semibold text-gray-900 dark:text-dark-800 mb-2"
              >
                Date Range
              </label>
              <div className="space-y-1">
                <select
                  id="date-filter"
                  value={dateFilter}
                  onChange={(e) => {
                    setDateFilter(e.target.value);
                    if (e.target.value !== "custom") {
                      setCustomDateFrom("");
                      setCustomDateTo("");
                    }
                    setPage(1);
                  }}
                  className="input"
                >
                  <option value="">All Time</option>
                  <option value="today">Today</option>
                  <option value="week">This Week</option>
                  <option value="month">This Month</option>
                  <option value="year">This Year</option>
                  <option value="custom">Custom Range</option>
                </select>

                {dateFilter === "custom" && (
                  <div className="flex space-x-2">
                    <div className="flex-1">
                      <input
                        type="date"
                        value={customDateFrom}
                        onChange={(e) => {
                          setCustomDateFrom(e.target.value);
                          setPage(1);
                        }}
                        className="input text-xs"
                        placeholder="From"
                      />
                    </div>
                    <div className="flex-1">
                      <input
                        type="date"
                        value={customDateTo}
                        onChange={(e) => {
                          setCustomDateTo(e.target.value);
                          setPage(1);
                        }}
                        className="input text-xs"
                        placeholder="To"
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div>
              <label
                htmlFor="search-filter"
                className="block text-sm font-semibold text-gray-900 dark:text-dark-800 mb-2"
              >
                Search Order Number
              </label>
              <input
                id="search-filter"
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Enter order number..."
                className="input"
              />
            </div>

            <div>
              <label
                htmlFor="status-filter"
                className="block text-sm font-semibold text-gray-900 dark:text-dark-800 mb-2"
              >
                Status
              </label>
              <select
                id="status-filter"
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setPage(1);
                }}
                className="input"
              >
                <option value="">All Statuses</option>
                <option value="match">Match</option>
                <option value="skipped">Skipped</option>
                <option value="error">Error</option>
              </select>
            </div>

            <div>
              <label
                htmlFor="store-filter"
                className="block text-sm font-semibold text-gray-900 dark:text-dark-800 mb-2"
              >
                Store
              </label>
              <select
                id="store-filter"
                value={storeFilter}
                onChange={(e) => {
                  setStoreFilter(e.target.value);
                  setPage(1);
                }}
                className="input"
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
              <label
                htmlFor="rule-filter"
                className="block text-sm font-semibold text-gray-900 dark:text-dark-800 mb-2"
              >
                Rule
              </label>
              <select
                id="rule-filter"
                value={ruleFilter}
                onChange={(e) => {
                  setRuleFilter(e.target.value);
                  setPage(1);
                }}
                className="input"
              >
                <option value="">All Rules</option>
                {rules?.map((rule: any) => (
                  <option key={rule.id} value={rule.id}>
                    {rule.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Logs table */}
          {groupedLogs.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-gray-500 dark:text-dark-400">
                No order logs found
              </p>
            </div>
          ) : (
            <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 md:rounded-lg dark:ring-dark-200">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-dark-200">
                <thead className="table-header">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider">
                      <div className="flex items-center space-x-2">
                        <input
                          type="checkbox"
                          checked={
                            (selectedOrders.size === groupedLogs.length &&
                              groupedLogs.length > 0) ||
                            isAllResultsSelected
                          }
                          onChange={handleSelectAll}
                          className="h-4 w-4 text-shopify-600 focus:ring-shopify-500 border-gray-300 rounded"
                        />
                        
                        {/* Compact selection display */}
                        {showGlobalSelection && data?.pagination.total > groupedLogs.length ? (
                          <div className="flex items-center space-x-1">
                            <span className="text-xs text-gray-700 dark:text-dark-600">
                              {isAllResultsSelected ? (
                                <span>Select All ({allResultsCount})</span>
                              ) : (
                                <span>Select All ({groupedLogs.length})</span>
                              )}
                            </span>
                            {!isAllResultsSelected && (
                              <button
                                onClick={handleGlobalSelection}
                                className="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-200 underline ml-1"
                              >
                                All {data.pagination.total}
                              </button>
                            )}
                            {isAllResultsSelected && (
                              <button
                                onClick={handleGlobalSelection}
                                className="text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-200 underline ml-1"
                              >
                                Page Only
                              </button>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-gray-700 dark:text-dark-600">
                            Select All ({data?.pagination.total || 0})
                          </span>
                        )}
                      </div>
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider">
                      <button
                        onClick={() => handleSort("order_number")}
                        className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                      >
                        <span>Order</span>
                        {getSortIcon("order_number")}
                      </button>
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider">
                      <button
                        onClick={() => handleSort("store_name")}
                        className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                      >
                        <span>Store</span>
                        {getSortIcon("store_name")}
                      </button>
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider">
                      <button
                        onClick={() => handleSort("action_count")}
                        className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                      >
                        <span>Actions</span>
                        {getSortIcon("action_count")}
                      </button>
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider">
                      <button
                        onClick={() => handleSort("status")}
                        className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                      >
                        <span>Status</span>
                        {getSortIcon("status")}
                      </button>
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider">
                      <button
                        onClick={() => handleSort("latest_date")}
                        className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                      >
                        <span>Latest Activity</span>
                        {getSortIcon("latest_date")}
                      </button>
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider">
                      Expand
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-dark-100 divide-y divide-gray-200 dark:divide-dark-200">
                  {groupedLogs.map((group) => (
                    <React.Fragment key={group.order_number}>
                      {/* Main row for each order */}
                      <tr className="table-row">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <input
                            type="checkbox"
                            checked={selectedOrders.has(group.order_id)}
                            onChange={() => handleSelectOrder(group.order_id)}
                            className="h-4 w-4 text-shopify-600 focus:ring-shopify-500 border-gray-300 rounded"
                          />
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-dark-800">
                          {group.order_number}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-dark-500">
                          {group.store_name}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-dark-500">
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400">
                            {group.logs.length} action
                            {group.logs.length !== 1 ? "s" : ""}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center">
                            {getStatusIcon(getGroupStatus(group))}
                            <span className="ml-2 text-sm text-gray-500 dark:text-dark-500 capitalize">
                              {group.has_failed && group.has_success
                                ? "Mixed"
                                : group.has_failed
                                  ? "Error"
                                  : group.has_success
                                    ? "Match"
                                    : "Skipped"}
                            </span>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-dark-500">
                          {formatDate(group.latest_date, {
                            timezone,
                            dateFormat,
                          })}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <button
                            onClick={() =>
                              toggleOrderExpansion(group.order_number)
                            }
                            className="p-1 text-gray-400 hover:text-gray-600 dark:text-dark-400 dark:hover:text-dark-600 rounded"
                          >
                            {expandedOrders.has(group.order_number) ? (
                              <ChevronDownIcon className="h-4 w-4" />
                            ) : (
                              <ChevronRightIcon className="h-4 w-4" />
                            )}
                          </button>
                        </td>
                      </tr>

                      {/* Expanded rows showing individual log entries */}
                      {expandedOrders.has(group.order_number) &&
                        group.logs.map((log) => (
                          <tr
                            key={log.id}
                            className="bg-gray-50 dark:bg-dark-50"
                          >
                            <td className="px-6 py-2"></td>
                            <td className="px-6 py-2 text-xs text-gray-500 dark:text-dark-400">
                              #{log.id}
                            </td>
                            <td className="px-6 py-2 text-xs text-gray-500 dark:text-dark-400">
                              -
                            </td>
                            <td className="px-6 py-2 text-xs text-gray-500 dark:text-dark-400">
                              {getActionLabel(log.action)}
                            </td>
                            <td className="px-6 py-2">
                              <div className="flex items-center">
                                {getStatusIcon(log.status)}
                                <span className="ml-2 text-xs text-gray-500 dark:text-dark-400 capitalize">
                                  {log.status}
                                </span>
                              </div>
                            </td>
                            <td className="px-6 py-2 text-xs text-gray-500 dark:text-dark-400">
                              {formatDate(log.created_at, {
                                timezone,
                                dateFormat,
                              })}
                            </td>
                            <td className="px-6 py-2">
                              <div className="text-xs text-gray-500 dark:text-dark-400 break-words">
                                {log.error_message ? (
                                  <span className="text-red-600 dark:text-red-400">
                                    {log.error_message}
                                  </span>
                                ) : log.details?.rule_name ? (
                                  <span>Rule: {log.details.rule_name}</span>
                                ) : log.details?.message ? (
                                  <span>{log.details.message}</span>
                                ) : (
                                  "-"
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Retry Action Bar */}
          {selectedOrders.size > 0 && (
            <div className="mt-4 bg-gray-50 dark:bg-dark-100 p-4 rounded-lg border border-gray-200 dark:border-dark-200">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-4">
                  <span className="text-sm font-medium text-gray-700 dark:text-dark-600">
                    {selectedOrders.size} order
                    {selectedOrders.size !== 1 ? "s" : ""} selected
                    {isAllResultsSelected && (
                      <span className="ml-1 text-blue-600 dark:text-blue-400">
                        (across all pages)
                      </span>
                    )}
                    {!isAllResultsSelected && showGlobalSelection && (
                      <span className="ml-1 text-gray-500 dark:text-dark-400">
                        (current page only)
                      </span>
                    )}
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
                    className="block w-48 text-sm border-gray-300 dark:border-dark-300 bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 rounded-md shadow-sm focus:border-shopify-500 focus:ring-shopify-500"
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
                    className="inline-flex items-center px-3 py-2 border border-gray-300 dark:border-dark-300 text-sm leading-4 font-medium rounded-md text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-shopify-500 disabled:opacity-50"
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
              <div className="text-sm text-gray-700 dark:text-dark-600">
                Showing page {data.pagination.page} of {data.pagination.pages} (
                {data.pagination.total} unique orders)
              </div>
              <div className="flex space-x-2">
                <button
                  onClick={() => setPage(Math.max(1, page - 1))}
                  disabled={page === 1}
                  className="px-3 py-2 border border-gray-300 dark:border-dark-300 text-sm font-medium rounded-md text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  onClick={() =>
                    setPage(Math.min(data.pagination.pages, page + 1))
                  }
                  disabled={page === data.pagination.pages}
                  className="px-3 py-2 border border-gray-300 dark:border-dark-300 text-sm font-medium rounded-md text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 disabled:opacity-50"
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
