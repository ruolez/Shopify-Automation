import React, { useState, useRef, useEffect } from "react";
import { motion } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Disclosure } from "@headlessui/react";
import {
  ShieldExclamationIcon,
  MagnifyingGlassIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  ExclamationTriangleIcon,
  PlusIcon,
  CogIcon,
  TrashIcon,
  PencilIcon,
  FunnelIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";
import api from "../utils/api";
import { fraudApi, type FraudAnalysisResult, type FraudAnalysisFilters } from "../utils/fraudApi";
import { fraudRuleApi, type FraudRule } from "../utils/fraudRuleApi";
import { Store } from "../types";
import LoadingSpinner from "../components/LoadingSpinner";
import FraudRuleBuilder from "../components/FraudRuleBuilder";
import { useTimezone } from "../contexts/TimezoneContext";
import { formatDate } from "../utils/dateFormat";

type SortField = "order_name" | "risk_level" | "customer_name" | "order_total" | "analysis_timestamp";
type SortDirection = "asc" | "desc";

const FraudDetection: React.FC = () => {
  const queryClient = useQueryClient();
  const { dateFormat, timezone } = useTimezone();
  
  // State for manual analysis
  const [selectedStoreId, setSelectedStoreId] = useState<number | "">("");
  const [orderName, setOrderName] = useState("");
  const [analysisResult, setAnalysisResult] =
    useState<FraudAnalysisResult | null>(null);

  // State for fraud rule management
  const [showRuleBuilder, setShowRuleBuilder] = useState(false);
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null);

  // State for sorting
  const [sortField, setSortField] = useState<SortField>("analysis_timestamp");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  // State for fraud results
  const [fraudFilters, setFraudFilters] = useState<FraudAnalysisFilters>({
    limit: 100,
    skip: 0,
    sort_field: sortField,
    sort_direction: sortDirection,
  });

  // State for matched rules filter
  const [selectedRules, setSelectedRules] = useState<string[]>([]);
  const [showRuleFilter, setShowRuleFilter] = useState(false);
  const ruleFilterRef = useRef<HTMLDivElement>(null);

  // State for hold functionality
  const [holdingOrderId, setHoldingOrderId] = useState<string | null>(null);

  // State for showing archived analyses
  const [showArchived, setShowArchived] = useState(false);

  // Fetch stores for dropdown
  const { data: stores, isLoading: storesLoading } = useQuery<Store[]>({
    queryKey: ["stores"],
    queryFn: async () => {
      const response = await api.get("/stores");
      return response.data;
    },
  });

  // Fetch fraud rules
  const { data: fraudRules, isLoading: rulesLoading } = useQuery<FraudRule[]>({
    queryKey: ["fraud-rules"],
    queryFn: fraudRuleApi.listRules,
  });

  // Fetch user settings for duplicate detection days
  const { data: userSettings, refetch: refetchSettings } = useQuery({
    queryKey: ["settings"],
    queryFn: async () => {
      const response = await api.get("/settings");
      console.log("Fraud Detection: Fetched settings", response.data);
      return response.data;
    },
    staleTime: 30000, // Consider data fresh for 30 seconds
    refetchInterval: 30000, // Refetch every 30 seconds instead of 5
  });

  // Update filters when sorting changes
  React.useEffect(() => {
    setFraudFilters(prev => ({
      ...prev,
      sort_field: sortField,
      sort_direction: sortDirection,
    }));
  }, [sortField, sortDirection]);

  // Force refetch settings on mount
  React.useEffect(() => {
    refetchSettings();
  }, [refetchSettings]);

  // Handle click outside rule filter
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (ruleFilterRef.current && !ruleFilterRef.current.contains(event.target as Node)) {
        setShowRuleFilter(false);
      }
    };

    if (showRuleFilter) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showRuleFilter]);

  // Fetch fraud analysis results
  const { data: fraudResults, isLoading: resultsLoading } = useQuery({
    queryKey: ["fraud-analyses", fraudFilters, sortField, sortDirection, selectedRules, showArchived],
    queryFn: () => {
      if (showArchived) {
        return fraudApi.getArchivedFraudAnalyses({
          ...fraudFilters,
          sort_field: sortField,
          sort_direction: sortDirection,
        });
      } else {
        return fraudApi.getFraudAnalyses({
          ...fraudFilters,
          sort_field: sortField,
          sort_direction: sortDirection,
          matched_rules: selectedRules.length > 0 ? selectedRules.join(',') : undefined,
        });
      }
    },
  });

  // Fetch all matched rules for filter dropdown
  const { data: allMatchedRules, error: matchedRulesError } = useQuery({
    queryKey: ["fraud-matched-rules"],
    queryFn: async () => {
      const response = await api.get("/fraud-detection/matched-rules");
      console.log("Matched rules API response:", response.data);
      return response.data;
    },
  });

  // Fetch intersection counts when rules are selected
  const { data: intersectionCounts } = useQuery({
    queryKey: ["fraud-rule-intersection-counts", selectedRules],
    queryFn: async () => {
      if (selectedRules.length === 0) return null;
      const response = await api.get("/fraud-detection/rule-intersection-counts", {
        params: {
          selected_rules: selectedRules.join(',')
        }
      });
      console.log("Intersection counts response:", response.data);
      return response.data;
    },
    enabled: selectedRules.length > 0,
  });

  // Log any errors with matched rules
  if (matchedRulesError) {
    console.error("Error fetching matched rules:", matchedRulesError);
  }

  // Analyze order mutation
  const analyzeOrderMutation = useMutation({
    mutationFn: async () => {
      if (!selectedStoreId || !orderName.trim()) {
        throw new Error("Please select a store and enter an order name");
      }
      
      // First, trigger the analysis
      const createResponse = await fraudApi.analyzeOrder(Number(selectedStoreId), orderName.trim());
      
      // Then fetch the detailed analysis
      const detailedAnalysis = await fraudApi.getFraudAnalysis(createResponse.analysis_id);
      
      return detailedAnalysis;
    },
    onSuccess: (data) => {
      setAnalysisResult(data);
      queryClient.invalidateQueries({ queryKey: ["fraud-analyses"] });
      toast.success("Order analysis completed successfully");
    },
    onError: (error: any) => {
      toast.error(
        error.message ||
          error.response?.data?.detail ||
          "Failed to analyze order",
      );
      setAnalysisResult(null);
    },
  });

  // Delete fraud rule mutation
  const deleteRuleMutation = useMutation({
    mutationFn: fraudRuleApi.deleteRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fraud-rules"] });
      toast.success("Fraud rule deleted successfully");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to delete fraud rule");
    },
  });

  // Toggle fraud rule mutation
  const toggleRuleMutation = useMutation({
    mutationFn: fraudRuleApi.toggleRule,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fraud-rules"] });
      toast.success("Fraud rule status updated");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to update fraud rule");
    },
  });

  // Manual archive mutation
  const manualArchiveMutation = useMutation({
    mutationFn: ({ analysisId, archiveReason }: { analysisId: number; archiveReason: string }) =>
      fraudApi.manuallyArchiveAnalysis(analysisId, archiveReason),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["fraud-analyses"] });
      queryClient.invalidateQueries({ queryKey: ["fraud-analyses-archived"] });
      toast.success(`Order ${data.order_name} archived successfully`);
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to archive fraud analysis");
    },
  });

  // Bulk archive mutation
  const bulkArchiveMutation = useMutation({
    mutationFn: fraudApi.bulkArchiveFulfilledCancelled,
    retry: false, // Disable retries
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["fraud-analyses"] });
      queryClient.invalidateQueries({ queryKey: ["fraud-analyses-archived"] });
      // Use the message from the backend which is more informative
      if (data.archived_count > 0) {
        toast.success(data.message);
      } else {
        // react-hot-toast doesn't have toast.info, so we use the default toast with a custom icon
        toast(data.message, {
          icon: 'ℹ️',
          style: {
            background: '#3B82F6',
            color: '#fff',
          },
        });
      }
    },
    onError: (error: any) => {
      // Check if it's a 403 error
      if (error.response?.status === 403) {
        toast.error("Authentication error. Please refresh the page and try again.");
      } else {
        const errorMessage = error.response?.data?.detail || error.message || "Failed to run bulk archive process";
        toast.error(errorMessage);
      }
    },
  });

  const handleAnalyze = () => {
    analyzeOrderMutation.mutate();
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !analyzeOrderMutation.isPending && selectedStoreId && orderName.trim()) {
      handleAnalyze();
    }
  };

  const handleRuleCreated = () => {
    setShowRuleBuilder(false);
    queryClient.invalidateQueries({ queryKey: ["fraud-rules"] });
  };

  const handleRuleUpdated = () => {
    setEditingRuleId(null);
    setShowRuleBuilder(false);
    queryClient.invalidateQueries({ queryKey: ["fraud-rules"] });
  };

  const handleEditRule = (ruleId: number) => {
    setEditingRuleId(ruleId);
    // Close the top rule builder if open
    setShowRuleBuilder(false);
  };

  const handleDeleteRule = (ruleId: number) => {
    if (window.confirm("Are you sure you want to delete this fraud rule?")) {
      deleteRuleMutation.mutate(ruleId);
    }
  };

  const handleToggleRule = (ruleId: number) => {
    toggleRuleMutation.mutate(ruleId);
  };

  const getRiskLevelBadge = (riskLevel: string) => {
    switch (riskLevel.toLowerCase()) {
      case "high":
        return "inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-200";
      case "medium":
        return "inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-orange-100 text-orange-800 dark:bg-orange-800 dark:text-orange-200";
      case "low":
        return "inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-200";
      default:
        return "inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200";
    }
  };

  const getShopifyRiskBadge = (riskLevel: string) => {
    switch (riskLevel?.toLowerCase()) {
      case "high":
        return "inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-200";
      case "medium":
        return "inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-orange-100 text-orange-800 dark:bg-orange-800 dark:text-orange-200";
      case "low":
        return "inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-200";
      case "none":
        return "inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-200";
      default:
        return "inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200";
    }
  };

  const getBooleanBadge = (value: boolean | null) => {
    if (value === null || value === undefined) {
      return <span className="text-sm text-gray-500">N/A</span>;
    }
    return value ? (
      <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-200">
        Yes
      </span>
    ) : (
      <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-200">
        No
      </span>
    );
  };


  const getBillingOutsideUSBadge = (value: boolean | null) => {
    if (value === null || value === undefined) {
      return <span className="text-sm text-gray-500">N/A</span>;
    }
    return value ? (
      <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-200">
        Yes
      </span>
    ) : (
      <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-200">
        No
      </span>
    );
  };

  const getFirstTimeCustomerBadge = (value: boolean | null) => {
    if (value === null || value === undefined) {
      return <span className="text-sm text-gray-500">N/A</span>;
    }
    return value ? (
      <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-200">
        Yes
      </span>
    ) : (
      <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-200">
        No
      </span>
    );
  };

  const getShippingStateBadge = (value: string | null) => {
    if (!value) {
      return <span className="text-sm text-gray-500">N/A</span>;
    }
    return (
      <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-blue-100 text-blue-800 dark:bg-blue-800 dark:text-blue-200">
        {value}
      </span>
    );
  };

  const getMatchedRules = (analysis: any) => {
    const rules = getMatchedRulesList(analysis);
    
    if (rules.length === 0) {
      return (
        <span className="inline-flex px-2 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300">
          No rules matched
        </span>
      );
    }
    
    return (
      <div className="flex flex-wrap gap-1">
        {rules.map((rule, index) => (
          <span
            key={index}
            className="inline-flex px-2 py-1 text-xs font-medium rounded-full bg-blue-100 text-blue-800 dark:bg-blue-800 dark:text-blue-200"
          >
            {rule}
          </span>
        ))}
      </div>
    );
  };

  const getMatchedRulesList = (analysis: any): string[] => {
    const rules: string[] = [];
    
    if (analysis.rule_processing_results?.results) {
      analysis.rule_processing_results.results
        .filter((result: any) => result.matched)
        .forEach((result: any) => {
          if (result.rule_name && !rules.includes(result.rule_name)) {
            rules.push(result.rule_name);
          }
        });
    }
    
    return rules;
  };

  // Get all unique matched rules from API endpoint
  const getAllUniqueMatchedRules = (): string[] => {
    // Use the rules from the API endpoint if available
    if (allMatchedRules?.rules) {
      console.log("Using API rules:", allMatchedRules.rules);
      return allMatchedRules.rules;
    }
    
    // Fallback to deriving from current results if API data not available yet
    console.log("API rules not available, using fallback");
    const uniqueRules = new Set<string>();
    
    if (fraudResults?.analyses) {
      fraudResults.analyses.forEach((analysis) => {
        const rules = getMatchedRulesList(analysis);
        rules.forEach(rule => uniqueRules.add(rule));
      });
    }
    
    // Add "No rules matched" as an option
    uniqueRules.add("No rules matched");
    
    const rulesArray = Array.from(uniqueRules).sort();
    console.log("Fallback rules:", rulesArray);
    return rulesArray;
  };

  // Get count of analyses that would match if this rule was added to current selection
  const getRuleMatchCount = (ruleName: string): number => {
    // If rules are selected, use intersection counts
    if (selectedRules.length > 0 && intersectionCounts?.rule_counts) {
      const count = intersectionCounts.rule_counts[ruleName];
      if (count !== undefined) {
        return count;
      }
    }
    
    // Otherwise, show the total count for each rule from the server
    if (allMatchedRules?.rule_counts && allMatchedRules.rule_counts[ruleName] !== undefined) {
      return allMatchedRules.rule_counts[ruleName];
    }
    return 0;
  };

  // No longer need client-side filtering since it's done server-side
  const filteredResults = fraudResults?.analyses || [];

  const handleSort = (field: SortField) => {
    if (field === sortField) {
      // Toggle direction if same field
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      // New field, default to asc
      setSortField(field);
      setSortDirection("asc");
    }
  };

  const getSortIcon = (field: SortField) => {
    if (field !== sortField) {
      return null; // No icon for unsorted columns
    }
    
    return sortDirection === "asc" ? (
      <ChevronUpIcon className="h-4 w-4" />
    ) : (
      <ChevronDownIcon className="h-4 w-4" />
    );
  };

  const handleRuleFilterToggle = (rule: string) => {
    setSelectedRules(prev => {
      if (prev.includes(rule)) {
        return prev.filter(r => r !== rule);
      } else {
        return [...prev, rule];
      }
    });
  };

  const handleClearRuleFilter = () => {
    setSelectedRules([]);
  };

  const handleHoldOrder = async (analysis: any) => {
    try {
      setHoldingOrderId(analysis.shopify_order_id);
      
      // Convert order ID to Shopify GID format if needed
      const orderGid = analysis.shopify_order_id.startsWith('gid://shopify/Order/') 
        ? analysis.shopify_order_id 
        : `gid://shopify/Order/${analysis.shopify_order_id}`;
      
      // Get all fulfillment orders for this order (each represents work instructions for a location)
      let fulfillmentResponse;
      try {
        // Use query parameters to avoid URL encoding issues
        console.log(`Getting fulfillment orders for: ${orderGid}`);
        fulfillmentResponse = await api.get(
          `/fulfillment-orders?order_id=${encodeURIComponent(orderGid)}&store_id=${analysis.store_id}`
        );
      } catch (error: any) {
        // If order by ID fails, try to find by name
        if (error.response?.status === 404 || error.response?.status === 400) {
          console.log(`Order lookup by ID failed, trying by name: ${analysis.order_name}`);
          try {
            // Try to get order by name first, then get fulfillment orders
            const orderResponse = await api.get(
              `/debug/order-data/${analysis.store_id}?order_name=${analysis.order_name}`
            );
            
            if (orderResponse.data?.order_info?.id) {
              const foundOrderGid = orderResponse.data.order_info.id;
              console.log(`Fallback using found GID: ${foundOrderGid}`);
              fulfillmentResponse = await api.get(
                `/fulfillment-orders?order_id=${encodeURIComponent(foundOrderGid)}&store_id=${analysis.store_id}`
              );
            } else {
              throw new Error("Order not found by name");
            }
          } catch (nameError: any) {
            throw error; // Re-throw the original error
          }
        } else {
          throw error;
        }
      }
      
      const fulfillmentOrders = fulfillmentResponse.data.fulfillment_orders;
      
      if (!fulfillmentOrders || fulfillmentOrders.length === 0) {
        const debugInfo = fulfillmentResponse.data.debug_info || "Unknown reason";
        const orderStatus = fulfillmentResponse.data.order_status || "unknown";
        
        // For unfulfilled orders, suggest alternative action
        if (orderStatus === "UNFULFILLED") {
          toast.error(`Order ${analysis.order_name} is unfulfilled but has no fulfillment orders yet. This may be a new order - fulfillment orders are typically created automatically by Shopify. Try again in a few minutes.`);
        } else {
          toast.error(`No fulfillment orders found for order ${analysis.order_name}. Status: ${orderStatus}. ${debugInfo}`);
        }
        
        console.log("Order lookup debug info:", fulfillmentResponse.data);
        return;
      }
      
      // Apply hold to each fulfillment order that isn't already on hold
      let successCount = 0;
      let errorCount = 0;
      let alreadyHeldCount = 0;
      let holdErrors: string[] = [];
      
      console.log(`Processing ${fulfillmentOrders.length} fulfillment orders for order ${analysis.order_name}`);
      
      for (const fo of fulfillmentOrders) {
        console.log(`Fulfillment order ${fo.id}: status=${fo.status}`);
        
        if (fo.status === "ON_HOLD") {
          alreadyHeldCount++;
          console.log(`Fulfillment order ${fo.id} already on hold, skipping`);
          continue;
        }
        
        try {
          console.log(`Applying hold to fulfillment order ${fo.id}...`);
          const holdResponse = await api.post(
            `/fulfillment-order-hold?fulfillment_order_id=${encodeURIComponent(fo.id)}&store_id=${analysis.store_id}&reason=HIGH_RISK_OF_FRAUD&reason_notes=${encodeURIComponent('Flagged by fraud detection system')}&notify_merchant=true`
          );
          
          successCount++;
          console.log(`Successfully held fulfillment order ${fo.id}`, holdResponse.data);
        } catch (error: any) {
          errorCount++;
          const errorMsg = error.response?.data?.detail || error.message || "Unknown error";
          holdErrors.push(`FO ${fo.id}: ${errorMsg}`);
          console.error(`Failed to hold fulfillment order ${fo.id}:`, error);
        }
      }
      
      // Provide detailed feedback
      if (successCount > 0) {
        toast.success(
          `Order ${analysis.order_name}: ${successCount} fulfillment order(s) put on hold` +
          (alreadyHeldCount > 0 ? ` (${alreadyHeldCount} already on hold)` : "")
        );
      } else if (alreadyHeldCount > 0) {
        toast(`Order ${analysis.order_name}: All ${alreadyHeldCount} fulfillment orders already on hold`, {
          icon: 'ℹ️',
        });
      } else if (successCount === 0 && errorCount === 0) {
        toast(`Order ${analysis.order_name}: No fulfillment orders available to hold`, {
          icon: '⚠️',
        });
      }
      
      if (errorCount > 0) {
        toast.error(`Failed to hold ${errorCount} fulfillment order(s): ${holdErrors.join(", ")}`);
      }
      
    } catch (error: any) {
      console.error("Failed to hold fulfillment orders:", error);
      toast.error(
        error.response?.data?.detail || 
        "Failed to put fulfillment orders on hold"
      );
    } finally {
      setHoldingOrderId(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* Section 1: Fraud Processing Results - MOVED TO TOP */}
      <Disclosure defaultOpen>
        {({ open }) => (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-white dark:bg-dark-100 shadow rounded-lg"
          >
            <Disclosure.Button className="flex w-full justify-between items-center px-4 py-5 sm:px-6 text-left focus:outline-none">
              <div className="flex items-center space-x-3">
                <ExclamationTriangleIcon className="h-6 w-6 text-yellow-600 dark:text-yellow-400" />
                <div>
                  <h3 className="text-lg leading-6 font-medium text-gray-900 dark:text-dark-800">
                    Fraud Processing Results
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-dark-500">
                    View processed orders and fraud analysis history
                  </p>
                </div>
              </div>
              <ChevronDownIcon
                className={`${open ? "rotate-180 transform" : ""} h-5 w-5 text-gray-500`}
              />
            </Disclosure.Button>
            <Disclosure.Panel>
              <div className="px-4 pb-5 sm:px-6">
                {/* Filters - Horizontal Layout with Sections */}
                <div className="mb-6 bg-gray-50 dark:bg-dark-200 rounded-lg p-4">
                  <div className="flex items-center gap-6">
                    {/* Section 1: Core Filters */}
                    <div className="flex items-center gap-4 flex-1">
                      {/* Risk Level */}
                      <div className="w-32">
                        <label className="block text-xs font-medium text-gray-600 dark:text-dark-400 mb-1">
                          Risk Level
                        </label>
                        <select
                          value={fraudFilters.risk_level || ""}
                          onChange={(e) =>
                            setFraudFilters({
                              ...fraudFilters,
                              risk_level: e.target.value as "low" | "medium" | "high" | undefined,
                            })
                          }
                          className="w-full px-3 py-2 text-sm border border-gray-300 dark:!border-gray-600 rounded-md shadow-sm bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600"
                        >
                          <option value="">All</option>
                          <option value="low">Low</option>
                          <option value="medium">Medium</option>
                          <option value="high">High</option>
                        </select>
                      </div>

                      {/* Search */}
                      <div className="flex-1 max-w-xs">
                        <label className="block text-xs font-medium text-gray-600 dark:text-dark-400 mb-1">
                          Search
                        </label>
                        <input
                          type="text"
                          value={fraudFilters.search || ""}
                          onChange={(e) =>
                            setFraudFilters({
                              ...fraudFilters,
                              search: e.target.value || undefined,
                            })
                          }
                          placeholder="Order name or customer..."
                          className="w-full px-3 py-2 text-sm border border-gray-300 dark:!border-gray-600 rounded-md shadow-sm bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600"
                        />
                      </div>

                      {/* Store Filter */}
                      <div className="w-48">
                        <label className="block text-xs font-medium text-gray-600 dark:text-dark-400 mb-1">
                          Store
                        </label>
                        <select
                          value={fraudFilters.store_id || ""}
                          onChange={(e) =>
                            setFraudFilters({
                              ...fraudFilters,
                              store_id: e.target.value ? Number(e.target.value) : undefined,
                            })
                          }
                          className="w-full px-3 py-2 text-sm border border-gray-300 dark:!border-gray-600 rounded-md shadow-sm bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600"
                        >
                          <option value="">All Stores</option>
                          {stores
                            ?.filter((store) => store.is_active)
                            .map((store) => (
                              <option key={store.id} value={store.id}>
                                {store.shop_name}
                              </option>
                            ))}
                        </select>
                      </div>
                    </div>

                    {/* Divider */}
                    <div className="h-12 w-px bg-gray-300 dark:bg-gray-600"></div>

                    {/* Section 2: Advanced Filters */}
                    <div className="relative" ref={ruleFilterRef}>
                      <button
                        onClick={() => setShowRuleFilter(!showRuleFilter)}
                        className="inline-flex items-center px-4 py-2 border border-gray-300 shadow-sm text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none dark:bg-dark-100 dark:border-dark-200 dark:text-dark-600 dark:hover:bg-dark-200 mt-5"
                      >
                        <FunnelIcon className={`h-4 w-4 mr-2 ${selectedRules.length > 0 ? 'text-orange-600 dark:text-orange-400' : 'text-gray-400'}`} />
                        <span>Filter Rules</span>
                        {selectedRules.length > 0 && (
                          <span className="ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800 dark:bg-orange-800 dark:text-orange-200">
                            {selectedRules.length}
                          </span>
                        )}
                      </button>
                      
                      {/* Rule Filter Dropdown */}
                      {showRuleFilter && (
                        <div className="absolute right-0 z-30 mt-3 w-64 bg-white dark:bg-dark-100 rounded-md shadow-lg border border-gray-200 dark:border-dark-200">
                          <div className="p-3">
                            <div className="flex items-center justify-between mb-3">
                              <span className="text-sm font-semibold text-gray-900 dark:text-white">
                                Filter by Rule (AND)
                              </span>
                              {selectedRules.length > 0 && (
                                <button
                                  onClick={handleClearRuleFilter}
                                  className="text-xs text-orange-600 hover:text-orange-700 dark:text-orange-400 dark:hover:text-orange-300 font-medium"
                                >
                                  Clear All
                                </button>
                              )}
                            </div>
                            <div className="max-h-72 overflow-y-auto space-y-0.5">
                              {getAllUniqueMatchedRules().map((rule) => {
                                const matchCount = getRuleMatchCount(rule);
                                const isSelected = selectedRules.includes(rule);
                                return (
                                  <label
                                    key={rule}
                                    className={`flex items-center justify-between px-2 py-1.5 hover:bg-gray-50 dark:hover:bg-dark-200 cursor-pointer rounded-md transition-colors ${
                                      isSelected ? 'bg-orange-50 dark:bg-orange-900/20' : ''
                                    }`}
                                  >
                                    <div className="flex items-center flex-1 min-w-0">
                                      <input
                                        type="checkbox"
                                        checked={isSelected}
                                        onChange={() => handleRuleFilterToggle(rule)}
                                        className="h-4 w-4 text-orange-600 border-gray-300 dark:border-gray-600 rounded flex-shrink-0 focus:outline-none"
                                      />
                                      <span className="ml-2 text-sm text-gray-700 dark:text-gray-200 break-words">
                                        {rule}
                                      </span>
                                    </div>
                                    <span className={`ml-2 text-xs flex-shrink-0 ${
                                      isSelected 
                                        ? 'text-orange-600 dark:text-orange-400 font-semibold' 
                                        : matchCount > 0 
                                          ? 'text-gray-500 dark:text-gray-400' 
                                          : 'text-gray-400 dark:text-gray-500'
                                    }`}>
                                      {`(${matchCount})`}
                                    </span>
                                  </label>
                                );
                              })}
                            </div>
                            <div className="mt-2 px-2 py-1 text-xs text-gray-500 dark:text-gray-400">
                              {selectedRules.length > 0 
                                ? "Numbers show analyses matching selected + each rule" 
                                : "Numbers show total analyses per rule"}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Divider */}
                    <div className="h-12 w-px bg-gray-300 dark:bg-gray-600"></div>

                    {/* Section 3: Actions */}
                    <div className="flex items-center gap-3">
                      {/* View Toggle */}
                      <button
                        onClick={() => {
                          setShowArchived(!showArchived);
                          // Reset pagination when toggling
                          setFraudFilters({ ...fraudFilters, skip: 0 });
                        }}
                        className={`inline-flex items-center px-4 py-2 text-sm font-medium rounded-md transition-colors mt-5 ${
                          showArchived
                            ? 'bg-orange-100 text-orange-800 hover:bg-orange-200 dark:bg-orange-800 dark:text-orange-200 dark:hover:bg-orange-700'
                            : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-200 dark:hover:bg-gray-600'
                        }`}
                        title={showArchived ? "Show unfulfilled orders" : "Show archived orders"}
                      >
                        {showArchived ? 'Archived' : 'Unfulfilled'}
                      </button>

                      {/* Reconcile Button */}
                      <button
                        onClick={() => bulkArchiveMutation.mutate()}
                        disabled={bulkArchiveMutation.isPending}
                        className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-purple-600 hover:bg-purple-700 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed mt-5"
                        title="Check all orders and archive fulfilled/cancelled ones"
                      >
                        {bulkArchiveMutation.isPending ? (
                          <>
                            <LoadingSpinner size="xs" />
                            <span className="ml-2">Processing...</span>
                          </>
                        ) : (
                          "Reconcile"
                        )}
                      </button>

                      {/* Reset Filters */}
                      <button
                        onClick={() => {
                          setFraudFilters({ limit: 100, skip: 0 });
                          setSelectedRules([]);
                          setShowArchived(false);
                        }}
                        className="p-2 border border-gray-300 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-50 focus:outline-none dark:border-dark-200 dark:text-dark-400 dark:hover:text-dark-600 dark:hover:bg-dark-200 mt-5"
                        title="Reset all filters"
                      >
                        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>

                {/* Selected rules indicator */}
                {selectedRules.length > 0 && (
                  <div className="mb-4 text-sm text-gray-600 dark:text-dark-400">
                    Showing orders matching ALL selected rules: {selectedRules.slice(0, 3).join(", ")}
                    {selectedRules.length > 3 && ` and ${selectedRules.length - 3} more`}
                  </div>
                )}

                {/* Results Table */}
                {resultsLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <LoadingSpinner size="lg" />
                  </div>
                ) : (
                  <div className="overflow-hidden shadow ring-1 ring-black ring-opacity-5 md:rounded-lg">
                    <table className="min-w-full divide-y divide-gray-300 dark:divide-dark-200">
                      <thead className="bg-gray-50 dark:bg-dark-200">
                        <tr>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 tracking-wider w-24">
                            <button
                              onClick={() => handleSort("order_name")}
                              className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                            >
                              <span>Order</span>
                              {getSortIcon("order_name")}
                            </button>
                          </th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 tracking-wider w-28">
                            <button
                              onClick={() => handleSort("risk_level")}
                              className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                            >
                              <span>Risk level</span>
                              {getSortIcon("risk_level")}
                            </button>
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 tracking-wider">
                            <button
                              onClick={() => handleSort("customer_name")}
                              className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                            >
                              <span>Customer</span>
                              {getSortIcon("customer_name")}
                            </button>
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 tracking-wider">
                            <button
                              onClick={() => handleSort("order_total")}
                              className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                            >
                              <span>Total</span>
                              {getSortIcon("order_total")}
                            </button>
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 tracking-wider w-96">
                            Matched rules
                          </th>
                          <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-dark-400 tracking-wider">
                            <button
                              onClick={() => handleSort("analysis_timestamp")}
                              className="flex items-center space-x-1 hover:text-gray-700 dark:hover:text-dark-600"
                            >
                              <span>Date</span>
                              {getSortIcon("analysis_timestamp")}
                            </button>
                          </th>
                          <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-dark-400 tracking-wider">
                            Actions
                          </th>
                        </tr>
                      </thead>
                      <tbody className="bg-white dark:bg-dark-100 divide-y divide-gray-200 dark:divide-dark-200">
                        {filteredResults.length > 0 ? (
                          filteredResults.map((analysis) => (
                            <tr key={analysis.id} className={analysis.is_archived ? "bg-gray-50 dark:bg-dark-200" : ""}>
                              <td className="px-4 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-dark-800">
                                <div className="flex items-center space-x-2">
                                  <span>{analysis.order_name}</span>
                                  {analysis.is_archived && (
                                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                                      analysis.archive_reason === 'order_fulfilled' 
                                        ? 'bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-200' 
                                        : analysis.archive_reason === 'order_cancelled'
                                        ? 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200'
                                        : 'bg-blue-100 text-blue-800 dark:bg-blue-800 dark:text-blue-200'
                                    }`}>
                                      {analysis.archive_reason === 'order_fulfilled' ? 'Fulfilled' : 
                                       analysis.archive_reason === 'order_cancelled' ? 'Cancelled' :
                                       'Manual Archive'}
                                    </span>
                                  )}
                                </div>
                              </td>
                              <td className="px-4 py-4 whitespace-nowrap">
                                <span
                                  className={getRiskLevelBadge(
                                    analysis.shopify_fraud_risk_level || "unknown"
                                  )}
                                >
                                  {(analysis.shopify_fraud_risk_level || "UNKNOWN").toUpperCase()}
                                </span>
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-dark-800">
                                {analysis.customer_name || "N/A"}
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-dark-800">
                                ${analysis.current_order_total || "N/A"}
                              </td>
                              <td className="px-6 py-4">
                                <div className="max-w-md">
                                  {getMatchedRules(analysis)}
                                </div>
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-dark-400">
                                {(() => {
                                  // For archived orders, timestamps are already in user's timezone
                                  if (analysis.is_archived && analysis.analysis_timestamp) {
                                    const timestamp = analysis.analysis_timestamp;
                                    // Timestamps like "2025-07-17 22:57:27.114560" are already in Chicago time
                                    // Parse and format without creating a Date object to avoid timezone issues
                                    const match = timestamp.match(/(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})/);
                                    if (match) {
                                      const [, , month, day, hour, minute] = match;
                                      const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
                                      const monthName = monthNames[parseInt(month) - 1];
                                      const dayNum = parseInt(day);
                                      let hours = parseInt(hour);
                                      const minutes = minute;
                                      const ampm = hours >= 12 ? 'PM' : 'AM';
                                      hours = hours % 12 || 12;
                                      
                                      return `${monthName} ${dayNum}, ${hours}:${minutes} ${ampm}`;
                                    }
                                  }
                                  
                                  // For non-archived orders, apply normal timezone conversion
                                  return formatDate(analysis.analysis_timestamp, { timezone, dateFormat });
                                })()}
                              </td>
                              <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                                {!analysis.is_archived ? (
                                  <div className="flex items-center space-x-2">
                                    <button
                                      onClick={() => handleHoldOrder(analysis)}
                                      disabled={holdingOrderId === analysis.shopify_order_id}
                                      className="inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded-md text-white bg-amber-600 hover:bg-amber-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-amber-500 disabled:opacity-50 disabled:cursor-not-allowed"
                                      title="Put fulfillment orders on hold"
                                    >
                                      {holdingOrderId === analysis.shopify_order_id ? (
                                        <LoadingSpinner size="xs" />
                                      ) : (
                                        "Hold"
                                      )}
                                    </button>
                                    <button
                                      onClick={() => manualArchiveMutation.mutate({ 
                                        analysisId: analysis.id, 
                                        archiveReason: "manual_archive" 
                                      })}
                                      disabled={manualArchiveMutation.isPending}
                                      className="inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded-md text-white bg-purple-600 hover:bg-purple-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-purple-500 disabled:opacity-50 disabled:cursor-not-allowed"
                                      title="Archive this analysis for testing"
                                    >
                                      {manualArchiveMutation.isPending ? (
                                        <LoadingSpinner size="xs" />
                                      ) : (
                                        "Archive"
                                      )}
                                    </button>
                                  </div>
                                ) : (
                                  <span className="text-xs text-gray-500 dark:text-gray-400">Archived</span>
                                )}
                              </td>
                            </tr>
                          ))
                        ) : (
                          <tr>
                            <td
                              colSpan={7}
                              className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-dark-400 text-center"
                            >
                              No fraud analysis results found
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Results count info */}
                {selectedRules.length > 0 && fraudResults && (
                  <div className="mt-4 text-sm text-gray-600 dark:text-dark-400">
                    Showing {filteredResults.length} of {fraudResults.analyses.length} results
                    {filteredResults.length !== fraudResults.analyses.length && (
                      <span className="ml-2 text-orange-600 dark:text-orange-400">
                        (filtered by matched rules)
                      </span>
                    )}
                  </div>
                )}

                {/* Results count and pagination */}
                {fraudResults && fraudResults.total > 0 && (
                  <div className="mt-6">
                    {/* Always show the total count */}
                    <div className="text-sm text-gray-700 dark:text-dark-300 text-center mb-4">
                      Showing {fraudFilters.skip! + 1} to{" "}
                      {Math.min(fraudFilters.skip! + fraudFilters.limit!, fraudResults.total)} of{" "}
                      {fraudResults.total} results
                    </div>
                    
                    {/* Only show pagination buttons if there's more than one page */}
                    {fraudResults.total > fraudFilters.limit! && (
                      <div className="flex items-center justify-center space-x-2">
                        <button
                          onClick={() =>
                            setFraudFilters({
                              ...fraudFilters,
                              skip: Math.max(0, fraudFilters.skip! - fraudFilters.limit!),
                            })
                          }
                          disabled={fraudFilters.skip === 0}
                          className="px-4 py-2 border border-gray-300 dark:border-dark-200 rounded-md text-sm font-medium text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Previous
                        </button>
                        <button
                          onClick={() =>
                            setFraudFilters({
                              ...fraudFilters,
                              skip: fraudFilters.skip! + fraudFilters.limit!,
                            })
                          }
                          disabled={fraudFilters.skip! + fraudFilters.limit! >= fraudResults.total}
                          className="px-4 py-2 border border-gray-300 dark:border-dark-200 rounded-md text-sm font-medium text-gray-700 dark:text-dark-600 bg-white dark:bg-dark-100 hover:bg-gray-50 dark:hover:bg-dark-200 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          Next
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </Disclosure.Panel>
          </motion.div>
        )}
      </Disclosure>

      {/* Section 2: Fraud Rules Management */}
      <Disclosure>
        {({ open }) => (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="bg-white dark:bg-dark-100 shadow rounded-lg"
          >
            <Disclosure.Button className="flex w-full justify-between items-center px-4 py-5 sm:px-6 text-left focus:outline-none">
              <div className="flex items-center space-x-3">
                <CogIcon className="h-6 w-6 text-red-600 dark:text-red-400" />
                <div>
                  <h3 className="text-lg leading-6 font-medium text-gray-900 dark:text-dark-800">
                    Fraud Rules Management
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-dark-500">
                    Create and manage automated fraud detection rules
                  </p>
                </div>
              </div>
              <ChevronDownIcon
                className={`${open ? "rotate-180 transform" : ""} h-5 w-5 text-gray-500`}
              />
            </Disclosure.Button>
            <Disclosure.Panel>
              <div className="px-4 pb-5 sm:px-6">
                {/* Rule Builder Toggle */}
                {!showRuleBuilder && (
                  <div className="mb-6">
                    <button
                      onClick={() => {
                        setEditingRuleId(null);
                        setShowRuleBuilder(true);
                      }}
                      className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700 dark:bg-gray-700 dark:hover:bg-gray-600 focus:outline-none"
                    >
                      <PlusIcon className="h-4 w-4 mr-2" />
                      Create Fraud Rule
                    </button>
                  </div>
                )}

                {/* Rule Builder */}
                {showRuleBuilder && (
                  <div className="mb-6 border border-gray-200 dark:border-dark-200 rounded-lg p-6">
                    <FraudRuleBuilder
                      isEmbedded={true}
                      existingRuleId={undefined}
                      onRuleCreated={handleRuleCreated}
                      onRuleUpdated={handleRuleUpdated}
                      onCancel={() => {
                        setShowRuleBuilder(false);
                        setEditingRuleId(null);
                      }}
                    />
                  </div>
                )}

                {/* Rules List */}
                {rulesLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <LoadingSpinner size="lg" />
                  </div>
                ) : (
                  <div className="space-y-4">
                    {fraudRules && fraudRules.length > 0 ? (
                      fraudRules.map((rule) => (
                        <div key={rule.id}>
                          {editingRuleId === rule.id ? (
                            // Show inline editor for this rule
                            <div className="border border-gray-200 dark:border-dark-200 rounded-lg p-6 bg-gray-50 dark:bg-dark-200">
                              <FraudRuleBuilder
                                isEmbedded={true}
                                existingRuleId={rule.id}
                                onRuleCreated={handleRuleCreated}
                                onRuleUpdated={handleRuleUpdated}
                                onCancel={() => {
                                  setEditingRuleId(null);
                                }}
                              />
                            </div>
                          ) : (
                            // Show normal rule display
                            <div className="border border-gray-200 dark:border-dark-200 rounded-lg p-4">
                              <div className="flex items-center justify-between">
                                <div className="flex-1">
                                  <div className="flex items-center space-x-3">
                                    <h4 className="text-lg font-medium text-gray-900 dark:text-dark-800">
                                      {rule.name}
                                    </h4>
                                    <span
                                      className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                                        rule.is_active
                                          ? "bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-200"
                                          : "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200"
                                      }`}
                                    >
                                      {rule.is_active ? "Active" : "Inactive"}
                                    </span>
                                    <span className="inline-flex px-2 py-1 text-xs font-semibold rounded-full bg-purple-100 text-purple-800 dark:bg-purple-800 dark:text-purple-200">
                                      Priority: {rule.priority}
                                    </span>
                                  </div>
                                  {rule.description && (
                                    <p className="mt-1 text-sm text-gray-600 dark:text-dark-500">
                                      {rule.description}
                                    </p>
                                  )}
                                  <p className="mt-1 text-xs text-gray-500 dark:text-dark-400">
                                    Created: {formatDate(rule.created_at, { timezone, dateFormat })}
                                  </p>
                                </div>
                                <div className="flex items-center space-x-2">
                                  <button
                                    onClick={() => handleToggleRule(rule.id)}
                                    disabled={toggleRuleMutation.isPending}
                                    className={`inline-flex items-center px-3 py-1 border border-transparent text-xs font-medium rounded-md ${
                                      rule.is_active
                                        ? "text-yellow-700 bg-yellow-100 hover:bg-yellow-200 dark:bg-yellow-800 dark:text-yellow-200"
                                        : "text-green-700 bg-green-100 hover:bg-green-200 dark:bg-green-800 dark:text-green-200"
                                    } focus:outline-none disabled:opacity-50`}
                                  >
                                    {rule.is_active ? "Deactivate" : "Activate"}
                                  </button>
                                  <button
                                    onClick={() => handleEditRule(rule.id)}
                                    className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-dark-600"
                                  >
                                    <PencilIcon className="h-4 w-4" />
                                  </button>
                                  <button
                                    onClick={() => handleDeleteRule(rule.id)}
                                    disabled={deleteRuleMutation.isPending}
                                    className="p-2 text-red-400 hover:text-red-600 disabled:opacity-50"
                                  >
                                    <TrashIcon className="h-4 w-4" />
                                  </button>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      ))
                    ) : (
                      <div className="text-center py-8">
                        <ShieldExclamationIcon className="mx-auto h-12 w-12 text-gray-400" />
                        <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-dark-800">
                          No fraud rules
                        </h3>
                        <p className="mt-1 text-sm text-gray-500 dark:text-dark-400">
                          Get started by creating your first fraud detection rule.
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </Disclosure.Panel>
          </motion.div>
        )}
      </Disclosure>

      {/* Section 3: Manual Analysis */}
      <Disclosure>
        {({ open }) => (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-white dark:bg-dark-100 shadow rounded-lg"
          >
            <Disclosure.Button className="flex w-full justify-between items-center px-4 py-5 sm:px-6 text-left focus:outline-none">
              <div className="flex items-center space-x-3">
                <MagnifyingGlassIcon className="h-6 w-6 text-orange-600 dark:text-orange-400" />
                <div>
                  <h3 className="text-lg leading-6 font-medium text-gray-900 dark:text-dark-800">
                    Manual Order Analysis
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-dark-500">
                    Analyze specific orders for fraud indicators
                  </p>
                </div>
              </div>
              <ChevronDownIcon
                className={`${open ? "rotate-180 transform" : ""} h-5 w-5 text-gray-500`}
              />
            </Disclosure.Button>
            <Disclosure.Panel>
              <div className="px-4 pb-5 sm:px-6">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                  {/* Store Selector */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-dark-300 mb-2">
                      Select Store
                    </label>
                    <select
                      value={selectedStoreId}
                      onChange={(e) =>
                        setSelectedStoreId(
                          e.target.value === "" ? "" : Number(e.target.value),
                        )
                      }
                      className="w-full px-3 py-2 border border-gray-300 dark:!border-gray-600 rounded-md shadow-sm bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600"
                      disabled={storesLoading}
                    >
                      <option value="">Choose a store...</option>
                      {stores
                        ?.filter((store) => store.is_active)
                        .map((store) => (
                          <option key={store.id} value={store.id}>
                            {store.shop_name}
                          </option>
                        ))}
                    </select>
                  </div>

                  {/* Order Name Input */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 dark:text-dark-300 mb-2">
                      Order Name
                    </label>
                    <input
                      type="text"
                      value={orderName}
                      onChange={(e) => setOrderName(e.target.value)}
                      onKeyPress={handleKeyPress}
                      placeholder="e.g., PW110446"
                      className="w-full px-3 py-2 border border-gray-300 dark:!border-gray-600 rounded-md shadow-sm bg-white dark:bg-dark-100 text-gray-900 dark:text-dark-800 focus:outline-none focus:!ring-0 focus:!border-gray-300 dark:focus:!border-gray-600"
                    />
                  </div>

                  {/* Analyze Button */}
                  <div className="flex items-end">
                    <button
                      onClick={handleAnalyze}
                      disabled={
                        analyzeOrderMutation.isPending ||
                        !selectedStoreId ||
                        !orderName.trim()
                      }
                      className="w-full inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-orange-600 hover:bg-orange-700 dark:bg-orange-500 dark:hover:bg-orange-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {analyzeOrderMutation.isPending ? (
                        <LoadingSpinner size="sm" />
                      ) : (
                        <>
                          <MagnifyingGlassIcon className="h-4 w-4 mr-2" />
                          Analyze Order
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {/* Loading State */}
                {analyzeOrderMutation.isPending && (
                  <div className="flex items-center justify-center py-8">
                    <LoadingSpinner size="lg" />
                    <span className="ml-3 text-gray-600 dark:text-dark-400">
                      Analyzing order...
                    </span>
                  </div>
                )}

                {/* Analysis Results */}
                {analysisResult && (
                  <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mt-6 space-y-6"
                  >
                    {/* Shopify Fraud Risk Assessment */}
                    <div className="bg-gray-50 dark:bg-dark-200 rounded-lg p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <h4 className="text-lg font-medium text-gray-900 dark:text-dark-800">
                            Shopify Fraud Risk for Order{" "}
                            {analysisResult.analysis.order_name}
                          </h4>
                          <p className="text-sm text-gray-600 dark:text-dark-400">
                            Store: {analysisResult.store_name}
                          </p>
                        </div>
                        <div className="text-right">
                          {analysisResult.analysis.shopify_fraud_risk_level !== undefined && (
                            <span
                              className={getShopifyRiskBadge(
                                analysisResult.analysis.shopify_fraud_risk_level || 'NONE',
                              )}
                            >
                              {(analysisResult.analysis.shopify_fraud_risk_level || 'NONE').toUpperCase()} RISK
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Fraud Detection Details */}
                    <div className="bg-white dark:bg-dark-100 border border-gray-200 dark:border-dark-200 rounded-lg overflow-hidden">
                      <div className="px-4 py-5 sm:p-6">
                        <h4 className="text-lg font-medium text-gray-900 dark:text-dark-800 mb-4">
                          Fraud Detection Results
                        </h4>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                          {/* Customer name */}
                          <div className="flex justify-between items-center py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300">
                              Customer Name
                            </span>
                            <span className="text-sm font-medium text-gray-900 dark:text-dark-800">
                              {analysisResult.analysis.customer_name || "N/A"}
                            </span>
                          </div>

                          {/* Order total */}
                          <div className="flex justify-between items-center py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300">
                              Order Total
                            </span>
                            <div className="text-right">
                              <div className="text-sm font-medium text-gray-900 dark:text-dark-800">
                                ${analysisResult.analysis.current_order_total || "N/A"}
                              </div>
                              {analysisResult.analysis.previous_order_total && (
                                <div className="text-xs text-gray-500 dark:text-dark-400">
                                  Previous: ${analysisResult.analysis.previous_order_total}
                                </div>
                              )}
                            </div>
                          </div>

                          {/* First-time customer */}
                          <div className="flex justify-between items-center py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300">
                              First-time Customer
                            </span>
                            {getFirstTimeCustomerBadge(analysisResult.analysis.is_first_time_customer)}
                          </div>

                          {/* Transaction attempts */}
                          <div className="flex justify-between items-center py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300">
                              Transaction Attempts
                            </span>
                            <span className="text-sm font-medium text-gray-900 dark:text-dark-800">
                              {analysisResult.analysis.transaction_attempts_count || "N/A"}
                            </span>
                          </div>

                          {/* Same billing/shipping address */}
                          <div className="flex justify-between items-center py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300">
                              Same Billing
                            </span>
                            {getBooleanBadge(analysisResult.analysis.same_billing_shipping)}
                          </div>

                          {/* Duplicate within configurable days */}
                          <div className="flex justify-between items-center py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300">
                              Duplicate within {userSettings?.duplicate_detection_days || 7} Days
                            </span>
                            {getBooleanBadge(analysisResult.analysis.duplicate_within_7days)}
                          </div>

                          {/* Billing address outside US */}
                          <div className="flex justify-between items-center py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300">
                              Billing Address Outside US
                            </span>
                            {getBillingOutsideUSBadge(analysisResult.analysis.billing_address_outside_us)}
                          </div>

                          {/* Shipping state */}
                          <div className="flex justify-between items-center py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300">
                              Shipping State
                            </span>
                            {getShippingStateBadge(analysisResult.analysis.shipping_state)}
                          </div>

                          {/* Previous order delivery status */}
                          <div className="flex justify-between items-center py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300">
                              Previous Order Delivery Status
                            </span>
                            <span className="text-sm font-medium text-gray-900 dark:text-dark-800">
                              {analysisResult.analysis.previous_order_delivery_status || "N/A"}
                            </span>
                          </div>

                          {/* Customer notes */}
                          <div className="py-2 border-b border-gray-200 dark:border-dark-200">
                            <span className="text-sm font-medium text-gray-700 dark:text-dark-300 block mb-2">
                              Notes
                            </span>
                            <span className="text-sm font-medium text-gray-900 dark:text-dark-800 block">
                              {analysisResult.analysis.customer_notes || "None"}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Raw Data Accordion */}
                    <Disclosure>
                      {({ open }) => (
                        <>
                          <Disclosure.Button className="flex w-full justify-between rounded-lg bg-gray-100 dark:bg-dark-200 px-4 py-2 text-left text-sm font-medium text-gray-900 dark:text-dark-800 hover:bg-gray-200 dark:hover:bg-dark-300 focus:outline-none">
                            <span>Raw Analysis Data (for fine-tuning)</span>
                            <ChevronDownIcon
                              className={`${open ? "rotate-180 transform" : ""} h-5 w-5 text-gray-500`}
                            />
                          </Disclosure.Button>
                          <Disclosure.Panel className="px-4 pt-4 pb-2 text-sm text-gray-500 dark:text-dark-400">
                            <pre className="bg-gray-50 dark:bg-dark-200 p-4 rounded-md overflow-auto text-xs">
                              {JSON.stringify(analysisResult, null, 2)}
                            </pre>
                          </Disclosure.Panel>
                        </>
                      )}
                    </Disclosure>
                  </motion.div>
                )}
              </div>
            </Disclosure.Panel>
          </motion.div>
        )}
      </Disclosure>
    </div>
  );
};

export default FraudDetection;