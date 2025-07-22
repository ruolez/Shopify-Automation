import React, { useState, useMemo } from "react";
import { motion } from "framer-motion";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  DocumentArrowDownIcon,
  ExclamationTriangleIcon,
  ChevronUpIcon,
  ChevronDownIcon,
  BeakerIcon,
  XMarkIcon,
  CalendarIcon,
  FunnelIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";
import api from "../utils/api";
import LoadingSpinner from "../components/LoadingSpinner";
import { formatShortDate, formatFullDateTime } from "../utils/dateFormat";
import { useTimezone } from "../contexts/TimezoneContext";

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

type SortField = "order_number" | "created_at" | "rule_name" | "location_alias";
type SortOrder = "asc" | "desc";

const Reports: React.FC = () => {
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const [ruleFilter, setRuleFilter] = useState<string>("");
  const [locationFilter, setLocationFilter] = useState<string>("");
  const [sortField, setSortField] = useState<SortField>("created_at");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [selectedOrders, setSelectedOrders] = useState<Set<string>>(new Set());
  const [showProductAnalysis, setShowProductAnalysis] = useState(false);
  const [productAnalysisData, setProductAnalysisData] = useState<any>(null);
  const [productSortField, setProductSortField] =
    useState<string>("total_incidents");
  const [productSortOrder, setProductSortOrder] = useState<"asc" | "desc">(
    "desc",
  );
  const { timezone, dateFormat } = useTimezone();

  // Preset date ranges
  const datePresets = [
    {
      label: "Today",
      getValue: () => {
        const today = new Date();
        const dateStr =
          today.getFullYear() +
          "-" +
          String(today.getMonth() + 1).padStart(2, "0") +
          "-" +
          String(today.getDate()).padStart(2, "0");
        return {
          start: dateStr,
          end: dateStr,
        };
      },
    },
    {
      label: "Last 7 days",
      getValue: () => {
        const end = new Date();
        const start = new Date();
        start.setDate(start.getDate() - 6); // 7 days including today

        const endStr =
          end.getFullYear() +
          "-" +
          String(end.getMonth() + 1).padStart(2, "0") +
          "-" +
          String(end.getDate()).padStart(2, "0");
        const startStr =
          start.getFullYear() +
          "-" +
          String(start.getMonth() + 1).padStart(2, "0") +
          "-" +
          String(start.getDate()).padStart(2, "0");

        return {
          start: startStr,
          end: endStr,
        };
      },
    },
    {
      label: "Last 30 days",
      getValue: () => {
        const end = new Date();
        const start = new Date();
        start.setDate(start.getDate() - 29); // 30 days including today

        const endStr =
          end.getFullYear() +
          "-" +
          String(end.getMonth() + 1).padStart(2, "0") +
          "-" +
          String(end.getDate()).padStart(2, "0");
        const startStr =
          start.getFullYear() +
          "-" +
          String(start.getMonth() + 1).padStart(2, "0") +
          "-" +
          String(start.getDate()).padStart(2, "0");

        return {
          start: startStr,
          end: endStr,
        };
      },
    },
    {
      label: "This month",
      getValue: () => {
        const now = new Date();
        const start = new Date(now.getFullYear(), now.getMonth(), 1);

        const endStr =
          now.getFullYear() +
          "-" +
          String(now.getMonth() + 1).padStart(2, "0") +
          "-" +
          String(now.getDate()).padStart(2, "0");
        const startStr =
          start.getFullYear() +
          "-" +
          String(start.getMonth() + 1).padStart(2, "0") +
          "-" +
          String(start.getDate()).padStart(2, "0");

        return {
          start: startStr,
          end: endStr,
        };
      },
    },
  ];

  // Build query params for date filtering with proper timezone handling
  const getDateParams = () => {
    const params = new URLSearchParams();
    if (startDate) {
      // Create date in user's local timezone, then convert to UTC
      const fromDate = new Date(startDate + "T00:00:00");
      params.append("start_date", fromDate.toISOString());
    }
    if (endDate) {
      // Create date in user's local timezone, then convert to UTC
      const toDate = new Date(endDate + "T23:59:59");
      params.append("end_date", toDate.toISOString());
    }
    return params.toString();
  };

  // Fetch OOS orders report
  const {
    data: oosReport,
    isLoading: oosLoading,
    refetch: refetchOOS,
  } = useQuery<OOSReport>({
    queryKey: ["oos-orders-report", startDate, endDate],
    queryFn: async () => {
      const params = getDateParams();
      const response = await api.get(`/reports/oos-orders?${params}`);
      return response.data;
    },
  });

  // Analyze selected orders mutation
  const analyzeOrders = useMutation({
    mutationFn: async (orderIds: string[]) => {
      const response = await api.post("/reports/oos-products/analyze", {
        order_ids: orderIds,
      });
      return response.data;
    },
    onSuccess: (data) => {
      setProductAnalysisData(data);
      setShowProductAnalysis(true);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to analyze orders");
    },
  });

  const handleDatePreset = (preset: any) => {
    const dateRange = preset.getValue();
    setStartDate(dateRange.start);
    setEndDate(dateRange.end);
    // Trigger report refresh after setting dates
    setTimeout(() => {
      refetchOOS();
    }, 100);
  };

  const handleClearFilters = () => {
    setRuleFilter("");
    setLocationFilter("");
    setSelectedOrders(new Set());
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortOrder("asc");
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
    if (
      selectedOrders.size === filteredAndSortedOrders.length &&
      filteredAndSortedOrders.length > 0
    ) {
      setSelectedOrders(new Set());
    } else {
      const allOrderIds = new Set(
        filteredAndSortedOrders.map((order) => order.order_number),
      );
      setSelectedOrders(allOrderIds);
    }
  };

  const handleAnalyzeSelected = () => {
    if (selectedOrders.size === 0) {
      toast.error("Please select at least one order to analyze");
      return;
    }
    analyzeOrders.mutate(Array.from(selectedOrders));
  };

  const handleProductSort = (field: string) => {
    if (productSortField === field) {
      setProductSortOrder(productSortOrder === "asc" ? "desc" : "asc");
    } else {
      setProductSortField(field);
      setProductSortOrder("asc");
    }
  };

  const filteredAndSortedOrders = useMemo(() => {
    if (!oosReport?.orders) return [];

    let filtered = oosReport.orders;

    // Apply filters
    if (ruleFilter) {
      filtered = filtered.filter((order) =>
        order.rule_name.toLowerCase().includes(ruleFilter.toLowerCase()),
      );
    }

    if (locationFilter) {
      filtered = filtered.filter((order) =>
        order.location_alias
          .toLowerCase()
          .includes(locationFilter.toLowerCase()),
      );
    }

    // Apply sorting
    return filtered.sort((a, b) => {
      let aValue: any = a[sortField];
      let bValue: any = b[sortField];

      if (sortField === "created_at") {
        aValue = new Date(aValue as string).getTime();
        bValue = new Date(bValue as string).getTime();
      }

      if (sortOrder === "asc") {
        return aValue < bValue ? -1 : aValue > bValue ? 1 : 0;
      } else {
        return aValue > bValue ? -1 : aValue < bValue ? 1 : 0;
      }
    });
  }, [oosReport?.orders, ruleFilter, locationFilter, sortField, sortOrder]);

  const uniqueRules = useMemo(() => {
    if (!oosReport?.orders) return [];
    return [
      ...new Set(oosReport.orders.map((order) => order.rule_name)),
    ].sort();
  }, [oosReport?.orders]);

  const uniqueLocations = useMemo(() => {
    if (!oosReport?.orders) return [];
    return [
      ...new Set(oosReport.orders.map((order) => order.location_alias)),
    ].sort();
  }, [oosReport?.orders]);

  const sortedProductAnalysisData = useMemo(() => {
    if (!productAnalysisData?.products) return [];

    return [...productAnalysisData.products].sort((a, b) => {
      let aValue = a[productSortField];
      let bValue = b[productSortField];

      // Handle different data types
      if (typeof aValue === "string") {
        aValue = aValue.toLowerCase();
        bValue = bValue.toLowerCase();
      }

      // Handle null/undefined values
      if (aValue == null) aValue = "";
      if (bValue == null) bValue = "";

      if (productSortOrder === "asc") {
        return aValue < bValue ? -1 : aValue > bValue ? 1 : 0;
      } else {
        return aValue > bValue ? -1 : aValue < bValue ? 1 : 0;
      }
    });
  }, [productAnalysisData?.products, productSortField, productSortOrder]);

  // Use centralized date formatting utility

  const exportToCSV = (data: any[], filename: string) => {
    if (!data.length) return;

    const headers = Object.keys(data[0]);
    const csvContent = [
      headers.join(","),
      ...data.map((row) =>
        headers.map((header) => JSON.stringify(row[header] || "")).join(","),
      ),
    ].join("\n");

    const blob = new Blob([csvContent], { type: "text/csv" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
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
        <h1 className="text-3xl font-bold text-gray-900 dark:text-dark-800 mb-2">
          Reports
        </h1>
        <p className="text-gray-600 dark:text-dark-500">
          Analyze out-of-stock orders to optimize inventory management.
        </p>
      </motion.div>

      {/* Compact Control Bar */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="card border border-gray-200 dark:border-dark-200 p-3"
      >
        <div className="flex flex-wrap items-center gap-3">
          {/* Date Range with Dropdown */}
          <div className="relative group">
            <button className="inline-flex items-center px-3 py-1.5 text-sm border border-gray-300 dark:border-dark-300 rounded-md bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 focus:outline-none">
              <CalendarIcon className="h-4 w-4 mr-1.5 text-gray-500" />
              <span className="text-gray-700 dark:text-dark-600">
                {startDate || endDate ? (
                  <>
                    {startDate ? formatShortDate(startDate, timezone) : "Start"}
                    {" - "}
                    {endDate ? formatShortDate(endDate, timezone) : "End"}
                  </>
                ) : (
                  "Date Range"
                )}
              </span>
              <ChevronDownIcon className="h-4 w-4 ml-1 text-gray-400" />
            </button>

            {/* Dropdown Menu */}
            <div className="absolute left-0 top-full mt-1 w-72 bg-white dark:bg-dark-100 rounded-md shadow-lg border border-gray-200 dark:border-dark-200 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-10">
              <div className="p-3 space-y-3">
                {/* Quick Presets */}
                <div className="grid grid-cols-2 gap-1">
                  {datePresets.map((preset, index) => (
                    <button
                      key={index}
                      onClick={() => handleDatePreset(preset)}
                      className="px-2 py-1 text-xs text-gray-700 dark:text-dark-600 hover:bg-gray-100 dark:hover:bg-dark-200 rounded transition-colors"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>

                <div className="border-t pt-3">
                  <div className="grid grid-cols-2 gap-2">
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      placeholder="Start"
                      className="input text-xs px-2 py-1"
                    />
                    <input
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      placeholder="End"
                      className="input text-xs px-2 py-1"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Inline Filters */}
          <div className="flex items-center gap-2">
            <FunnelIcon className="h-4 w-4 text-gray-400" />
            <select
              value={ruleFilter}
              onChange={(e) => setRuleFilter(e.target.value)}
              className="input text-sm px-2 py-1.5"
            >
              <option value="">All Rules</option>
              {uniqueRules.map((rule) => (
                <option key={rule} value={rule}>
                  {rule}
                </option>
              ))}
            </select>

            <select
              value={locationFilter}
              onChange={(e) => setLocationFilter(e.target.value)}
              className="input text-sm px-2 py-1.5"
            >
              <option value="">All Locations</option>
              {uniqueLocations.map((location) => (
                <option key={location} value={location}>
                  {location}
                </option>
              ))}
            </select>
          </div>

          {/* Active Filters Pills */}
          {(startDate || endDate || ruleFilter || locationFilter) && (
            <div className="flex items-center gap-2 flex-1">
              <div className="flex flex-wrap gap-1">
                {(startDate || endDate) && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-700">
                    {startDate && formatShortDate(startDate, timezone)}
                    {startDate && endDate && " - "}
                    {endDate && formatShortDate(endDate, timezone)}
                    <button
                      onClick={() => {
                        setStartDate("");
                        setEndDate("");
                      }}
                      className="ml-1 hover:text-gray-900 dark:hover:text-dark-800"
                    >
                      <XMarkIcon className="h-3 w-3" />
                    </button>
                  </span>
                )}
                {ruleFilter && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-blue-100 text-blue-800">
                    {ruleFilter}
                    <button
                      onClick={() => setRuleFilter("")}
                      className="ml-1 hover:text-blue-900"
                    >
                      <XMarkIcon className="h-3 w-3" />
                    </button>
                  </span>
                )}
                {locationFilter && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-800">
                    {locationFilter}
                    <button
                      onClick={() => setLocationFilter("")}
                      className="ml-1 hover:text-green-900"
                    >
                      <XMarkIcon className="h-3 w-3" />
                    </button>
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex items-center gap-2 ml-auto">
            {(startDate || endDate || ruleFilter || locationFilter) && (
              <button
                onClick={handleClearFilters}
                className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors"
                title="Clear all filters"
              >
                <XMarkIcon className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </motion.div>

      {/* Results Section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="bg-white dark:bg-dark-100 rounded-lg shadow-sm border border-gray-200 dark:border-dark-200"
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
                    <h3 className="text-lg font-medium text-gray-900 dark:text-dark-800">
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
                      onClick={() =>
                        exportToCSV(filteredAndSortedOrders, "oos-orders.csv")
                      }
                      disabled={filteredAndSortedOrders.length === 0}
                      className="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-dark-300 text-sm font-medium rounded-md text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <DocumentArrowDownIcon className="h-4 w-4 mr-1.5" />
                      Export All
                    </button>
                    {selectedOrders.size > 0 && (
                      <>
                        <button
                          onClick={() =>
                            exportToCSV(
                              filteredAndSortedOrders.filter((order) =>
                                selectedOrders.has(order.order_number),
                              ),
                              "selected-oos-orders.csv",
                            )
                          }
                          className="inline-flex items-center px-3 py-1.5 border border-gray-300 dark:border-dark-300 text-sm font-medium rounded-md text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 focus:outline-none"
                        >
                          <DocumentArrowDownIcon className="h-4 w-4 mr-1.5" />
                          Export Selected ({selectedOrders.size})
                        </button>
                        <button
                          onClick={handleAnalyzeSelected}
                          disabled={analyzeOrders.isPending}
                          className="inline-flex items-center px-3 py-1.5 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none disabled:opacity-50"
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
                <div className="overflow-x-auto border border-gray-200 dark:border-dark-200 rounded-lg">
                  <table className="min-w-full divide-y divide-gray-200 dark:divide-dark-200">
                    <thead className="bg-gray-50 dark:bg-dark-200">
                      <tr>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider">
                          <input
                            type="checkbox"
                            checked={
                              selectedOrders.size ===
                                filteredAndSortedOrders.length &&
                              filteredAndSortedOrders.length > 0
                            }
                            onChange={handleSelectAll}
                            className="h-4 w-4 text-shopify-600 border-gray-300 rounded focus:outline-none"
                          />
                        </th>
                        <th
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors"
                          onClick={() => handleSort("order_number")}
                        >
                          <div className="flex items-center">
                            Order Number
                            {sortField === "order_number" &&
                              (sortOrder === "asc" ? (
                                <ChevronUpIcon className="ml-1 h-4 w-4" />
                              ) : (
                                <ChevronDownIcon className="ml-1 h-4 w-4" />
                              ))}
                          </div>
                        </th>
                        <th
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors"
                          onClick={() => handleSort("created_at")}
                        >
                          <div className="flex items-center">
                            Date Created
                            {sortField === "created_at" &&
                              (sortOrder === "asc" ? (
                                <ChevronUpIcon className="ml-1 h-4 w-4" />
                              ) : (
                                <ChevronDownIcon className="ml-1 h-4 w-4" />
                              ))}
                          </div>
                        </th>
                        <th
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors"
                          onClick={() => handleSort("rule_name")}
                        >
                          <div className="flex items-center">
                            Processing Rule
                            {sortField === "rule_name" &&
                              (sortOrder === "asc" ? (
                                <ChevronUpIcon className="ml-1 h-4 w-4" />
                              ) : (
                                <ChevronDownIcon className="ml-1 h-4 w-4" />
                              ))}
                          </div>
                        </th>
                        <th
                          className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors"
                          onClick={() => handleSort("location_alias")}
                        >
                          <div className="flex items-center">
                            Target Location
                            {sortField === "location_alias" &&
                              (sortOrder === "asc" ? (
                                <ChevronUpIcon className="ml-1 h-4 w-4" />
                              ) : (
                                <ChevronDownIcon className="ml-1 h-4 w-4" />
                              ))}
                          </div>
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-dark-100 divide-y divide-gray-200 dark:divide-dark-200">
                      {filteredAndSortedOrders.map((order, index) => (
                        <tr
                          key={index}
                          className="hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors cursor-pointer"
                          onClick={() => handleSelectOrder(order.order_number)}
                        >
                          <td className="px-4 py-4 whitespace-nowrap">
                            <input
                              type="checkbox"
                              checked={selectedOrders.has(order.order_number)}
                              onChange={() =>
                                handleSelectOrder(order.order_number)
                              }
                              onClick={(e) => e.stopPropagation()}
                              className="h-4 w-4 text-shopify-600 border-gray-300 rounded focus:outline-none"
                            />
                          </td>
                          <td className="px-4 py-4 whitespace-nowrap">
                            <div className="text-sm font-medium text-gray-900 dark:text-dark-800">
                              {order.order_number}
                            </div>
                          </td>
                          <td className="px-4 py-4 whitespace-nowrap">
                            <div className="text-sm text-gray-500">
                              {formatFullDateTime(
                                order.created_at,
                                timezone,
                                dateFormat,
                              )}
                            </div>
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
                  <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-dark-800">
                    No orders found
                  </h3>
                  <p className="mt-1 text-sm text-gray-500">
                    {ruleFilter || locationFilter
                      ? "Try adjusting your filters to see more results."
                      : "No out-of-stock orders found for the selected date range."}
                  </p>
                  {(ruleFilter || locationFilter) && (
                    <div className="mt-4">
                      <button
                        onClick={handleClearFilters}
                        className="inline-flex items-center px-3 py-2 border border-gray-300 dark:border-dark-300 text-sm font-medium rounded-md text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 focus:outline-none"
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
              <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-dark-800">
                No data available
              </h3>
              <p className="mt-1 text-sm text-gray-500">
                Set a date range and click "Generate Report" to analyze
                out-of-stock orders.
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
          className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center p-4 z-50"
          onClick={() => setShowProductAnalysis(false)}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className="bg-white dark:bg-dark-100 rounded-lg p-4 sm:p-6 max-w-6xl w-full max-h-[90vh] overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-semibold text-gray-900 dark:text-dark-800">
                Product Analysis Results
              </h2>
              <button
                onClick={() => setShowProductAnalysis(false)}
                className="text-gray-400 dark:text-dark-400 hover:text-gray-500 dark:hover:text-dark-500"
              >
                <span className="sr-only">Close</span>
                <svg
                  className="h-6 w-6"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>

            <div className="mb-4 grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="bg-red-50 p-4 rounded-lg">
                <div className="flex items-center">
                  <ExclamationTriangleIcon className="h-8 w-8 text-red-600" />
                  <div className="ml-3">
                    <p className="text-sm font-medium text-red-800">
                      Total OOS Incidents
                    </p>
                    <p className="text-2xl font-bold text-red-900">
                      {productAnalysisData.total_oos_incidents}
                    </p>
                  </div>
                </div>
              </div>
              <div className="bg-blue-50 p-4 rounded-lg">
                <div className="flex items-center">
                  <BeakerIcon className="h-8 w-8 text-blue-600" />
                  <div className="ml-3">
                    <p className="text-sm font-medium text-blue-800">
                      Unique Products
                    </p>
                    <p className="text-2xl font-bold text-blue-900">
                      {productAnalysisData.unique_products}
                    </p>
                  </div>
                </div>
              </div>
              <div className="bg-amber-50 p-4 rounded-lg">
                <div className="flex items-center">
                  <DocumentArrowDownIcon className="h-8 w-8 text-amber-600" />
                  <div className="ml-3">
                    <p className="text-sm font-medium text-amber-800">
                      Orders Analyzed
                    </p>
                    <p className="text-2xl font-bold text-amber-900">
                      {productAnalysisData.selected_orders ||
                        selectedOrders.size}
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="overflow-y-auto max-h-[60vh]">
              <table className="min-w-full divide-y divide-gray-200 dark:divide-dark-200">
                <thead className="bg-gray-50 dark:bg-dark-200 sticky top-0">
                  <tr>
                    <th
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors"
                      onClick={() => handleProductSort("product_title")}
                    >
                      <div className="flex items-center">
                        Product
                        {productSortField === "product_title" &&
                          (productSortOrder === "asc" ? (
                            <ChevronUpIcon className="ml-1 h-4 w-4" />
                          ) : (
                            <ChevronDownIcon className="ml-1 h-4 w-4" />
                          ))}
                      </div>
                    </th>
                    <th
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors"
                      onClick={() => handleProductSort("sku")}
                    >
                      <div className="flex items-center">
                        SKU
                        {productSortField === "sku" &&
                          (productSortOrder === "asc" ? (
                            <ChevronUpIcon className="ml-1 h-4 w-4" />
                          ) : (
                            <ChevronDownIcon className="ml-1 h-4 w-4" />
                          ))}
                      </div>
                    </th>
                    <th
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors"
                      onClick={() => handleProductSort("vendor")}
                    >
                      <div className="flex items-center">
                        Vendor
                        {productSortField === "vendor" &&
                          (productSortOrder === "asc" ? (
                            <ChevronUpIcon className="ml-1 h-4 w-4" />
                          ) : (
                            <ChevronDownIcon className="ml-1 h-4 w-4" />
                          ))}
                      </div>
                    </th>
                    <th
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors"
                      onClick={() => handleProductSort("total_incidents")}
                    >
                      <div className="flex items-center">
                        Incidents
                        {productSortField === "total_incidents" &&
                          (productSortOrder === "asc" ? (
                            <ChevronUpIcon className="ml-1 h-4 w-4" />
                          ) : (
                            <ChevronDownIcon className="ml-1 h-4 w-4" />
                          ))}
                      </div>
                    </th>
                    <th
                      className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider cursor-pointer hover:bg-gray-100 dark:hover:bg-dark-300 transition-colors"
                      onClick={() =>
                        handleProductSort("total_quantity_affected")
                      }
                    >
                      <div className="flex items-center">
                        Total Qty
                        {productSortField === "total_quantity_affected" &&
                          (productSortOrder === "asc" ? (
                            <ChevronUpIcon className="ml-1 h-4 w-4" />
                          ) : (
                            <ChevronDownIcon className="ml-1 h-4 w-4" />
                          ))}
                      </div>
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 uppercase tracking-wider">
                      Locations
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white dark:bg-dark-100 divide-y divide-gray-200 dark:divide-dark-200">
                  {sortedProductAnalysisData.map(
                    (product: any, index: number) => (
                      <tr
                        key={index}
                        className="hover:bg-gray-50 dark:hover:bg-dark-200"
                      >
                        <td className="px-6 py-4 text-sm">
                          <div>
                            <div className="font-medium text-gray-900 dark:text-dark-800">
                              {product.product_title}
                            </div>
                            {product.variant_title &&
                              product.variant_title !== "Default Title" && (
                                <div className="text-gray-500">
                                  {product.variant_title}
                                </div>
                              )}
                            {product.product_type && (
                              <div className="text-xs text-gray-400">
                                {product.product_type}
                              </div>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {product.sku || "-"}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {product.vendor || "-"}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-red-600">
                          {product.total_incidents}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-dark-800">
                          {product.total_quantity_affected}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-500">
                          <div className="max-w-xs">
                            {product.locations_affected
                              ?.slice(0, 2)
                              .map((location: string, idx: number) => (
                                <span
                                  key={idx}
                                  className="inline-block bg-gray-100 rounded-full px-2 py-1 text-xs mr-1 mb-1"
                                >
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
                    ),
                  )}
                </tbody>
              </table>
            </div>

            <div className="mt-4 flex flex-col sm:flex-row sm:justify-end space-y-2 sm:space-y-0 sm:space-x-2">
              <button
                onClick={() =>
                  exportToCSV(sortedProductAnalysisData, "product-analysis.csv")
                }
                className="inline-flex items-center justify-center px-4 py-2 border border-gray-300 dark:border-dark-300 text-sm font-medium rounded-md text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 focus:outline-none"
              >
                <DocumentArrowDownIcon className="h-4 w-4 mr-2" />
                Export CSV
              </button>
              <button
                onClick={() => setShowProductAnalysis(false)}
                className="inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 focus:outline-none"
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
