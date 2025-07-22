import React from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  PlusIcon,
  PencilIcon,
  TrashIcon,
  PlayIcon,
  PauseIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";
import api from "../utils/api";
import { Rule } from "../types";
import LoadingSpinner from "../components/LoadingSpinner";
import { formatShortDate } from "../utils/dateFormat";
import { useTimezone } from "../contexts/TimezoneContext";

const Rules: React.FC = () => {
  const queryClient = useQueryClient();
  const { timezone } = useTimezone();

  const { data: rules, isLoading } = useQuery<Rule[]>({
    queryKey: ["rules"],
    queryFn: async () => {
      const response = await api.get("/rules");
      return response.data;
    },
  });

  const deleteRuleMutation = useMutation({
    mutationFn: async (ruleId: number) => {
      await api.delete(`/rules/${ruleId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Rule deleted successfully");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to delete rule");
    },
  });

  const toggleRuleMutation = useMutation({
    mutationFn: async ({ ruleId, rule }: { ruleId: number; rule: Rule }) => {
      const updatedRule = { ...rule, is_active: !rule.is_active };
      const response = await api.put(`/rules/${ruleId}`, updatedRule);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success("Rule updated successfully");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to update rule");
    },
  });

  const activateAllRulesMutation = useMutation({
    mutationFn: async () => {
      const response = await api.put("/rules/bulk/activate");
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success(data.message);
    },
    onError: (error: any) => {
      toast.error(
        error.response?.data?.detail || "Failed to activate all rules",
      );
    },
  });

  const deactivateAllRulesMutation = useMutation({
    mutationFn: async () => {
      const response = await api.put("/rules/bulk/deactivate");
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["rules"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
      toast.success(data.message);
    },
    onError: (error: any) => {
      toast.error(
        error.response?.data?.detail || "Failed to deactivate all rules",
      );
    },
  });

  const handleDeleteRule = (ruleId: number) => {
    if (window.confirm("Are you sure you want to delete this rule?")) {
      deleteRuleMutation.mutate(ruleId);
    }
  };

  const handleToggleRule = (rule: Rule) => {
    toggleRuleMutation.mutate({ ruleId: rule.id, rule });
  };

  const handleActivateAll = () => {
    if (window.confirm("Are you sure you want to activate all rules?")) {
      activateAllRulesMutation.mutate();
    }
  };

  const handleDeactivateAll = () => {
    if (window.confirm("Are you sure you want to deactivate all rules?")) {
      deactivateAllRulesMutation.mutate();
    }
  };

  const formatConditions = (conditions: any) => {
    if (!conditions) return "No conditions";

    // Handle both legacy (array) and new (object) formats
    let conditionsList: any[] = [];
    let logicalOperator = "AND";

    if (Array.isArray(conditions)) {
      // Legacy format
      conditionsList = conditions;
    } else if (conditions.conditions && Array.isArray(conditions.conditions)) {
      // New format
      conditionsList = conditions.conditions;
      logicalOperator = conditions.operator || "AND";
    }

    if (conditionsList.length === 0) return "No conditions";

    // Simple format for the rules list
    const conditionStrings = conditionsList.map((condition) => {
      const field = condition.field?.replace(/_/g, " ") || "";
      const operator = condition.operator?.replace(/_/g, " ") || "";
      const value = condition.value || "";
      return `${field} ${operator} ${value}`;
    });

    const joinWord = logicalOperator === "OR" ? " OR " : " AND ";
    const result = conditionStrings.join(joinWord);

    // Add prefix to indicate the logic when there are multiple conditions
    if (conditionsList.length > 1) {
      return `(${logicalOperator}) ${result}`;
    }

    return result;
  };

  const formatActions = (actions: any[]) => {
    if (!actions || actions.length === 0) return "No actions";

    const actionStrings = actions.map((action) => {
      const type = action.type?.replace(/_/g, " ") || "";
      return type;
    });

    return actionStrings.join(", ");
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-dark-800">
            Rules
          </h1>
          <p className="mt-2 text-gray-600 dark:text-dark-500">
            Manage your order processing rules
          </p>
        </div>
        <div className="flex items-center space-x-3">
          {rules && rules.length > 0 && (
            <>
              <button
                onClick={handleActivateAll}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-green-700 bg-green-100 hover:bg-green-200 dark:bg-green-900/20 dark:text-green-400 dark:hover:bg-green-900/30 focus:outline-none"
                disabled={activateAllRulesMutation.isPending}
              >
                <PlayIcon className="h-5 w-5 mr-2" />
                Start All
              </button>
              <button
                onClick={handleDeactivateAll}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-red-700 bg-red-100 hover:bg-red-200 dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/30 focus:outline-none"
                disabled={deactivateAllRulesMutation.isPending}
              >
                <PauseIcon className="h-5 w-5 mr-2" />
                Pause All
              </button>
            </>
          )}
          <Link to="/rules/new" className="btn-primary flex items-center">
            <PlusIcon className="h-5 w-5 mr-2" />
            Create Rule
          </Link>
        </div>
      </div>

      {rules && rules.length > 0 ? (
        <div className="space-y-4">
          {rules.map((rule, index) => (
            <motion.div
              key={rule.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
              className="card"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center space-x-3">
                    <h3 className="text-lg font-medium text-gray-900 dark:text-dark-800">
                      {rule.name}
                    </h3>
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        rule.is_active
                          ? "bg-green-100 text-green-800 dark:bg-green-900/20 dark:text-green-400"
                          : "bg-red-100 text-red-800 dark:bg-red-900/20 dark:text-red-400"
                      }`}
                    >
                      {rule.is_active ? "Active" : "Inactive"}
                    </span>
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900/20 dark:text-blue-400">
                      Priority: {rule.priority}
                    </span>
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900/20 dark:text-purple-400">
                      Delay: {rule.delay_ms}ms
                    </span>
                  </div>

                  {rule.description && (
                    <p className="text-sm text-gray-600 dark:text-dark-500 mt-1">
                      {rule.description}
                    </p>
                  )}

                  <div className="mt-3 space-y-2">
                    <div>
                      <span className="text-sm font-medium text-gray-700 dark:text-dark-600">
                        Conditions:{" "}
                      </span>
                      <span className="text-sm text-gray-600 dark:text-dark-500">
                        {formatConditions(rule.conditions)}
                      </span>
                    </div>
                    <div>
                      <span className="text-sm font-medium text-gray-700 dark:text-dark-600">
                        Actions:{" "}
                      </span>
                      <span className="text-sm text-gray-600 dark:text-dark-500">
                        {formatActions(rule.actions)}
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-gray-400 dark:text-dark-300 mt-3">
                    Created: {formatShortDate(rule.created_at, timezone)}
                  </p>
                </div>

                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => handleToggleRule(rule)}
                    className={`p-2 rounded-lg transition-colors ${
                      rule.is_active
                        ? "text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                        : "text-green-600 hover:bg-green-50 dark:hover:bg-green-900/20"
                    }`}
                    title={rule.is_active ? "Deactivate rule" : "Activate rule"}
                  >
                    {rule.is_active ? (
                      <PauseIcon className="h-5 w-5" />
                    ) : (
                      <PlayIcon className="h-5 w-5" />
                    )}
                  </button>

                  <Link
                    to={`/rules/${rule.id}/edit`}
                    className="p-2 text-gray-600 hover:bg-gray-50 dark:text-dark-500 dark:hover:bg-dark-200 rounded-lg transition-colors"
                    title="Edit rule"
                  >
                    <PencilIcon className="h-5 w-5" />
                  </Link>

                  <button
                    onClick={() => handleDeleteRule(rule.id)}
                    className="p-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                    title="Delete rule"
                  >
                    <TrashIcon className="h-5 w-5" />
                  </button>
                </div>
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center py-12"
        >
          <div className="max-w-md mx-auto">
            <div className="mx-auto h-12 w-12 text-gray-400">
              <svg fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1}
                  d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1}
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
              </svg>
            </div>
            <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-dark-800">
              No rules
            </h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-dark-400">
              Get started by creating your first automation rule.
            </p>
            <div className="mt-6">
              <Link to="/rules/new" className="btn-primary flex items-center">
                <PlusIcon className="h-5 w-5 mr-2" />
                Create Rule
              </Link>
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
};

export default Rules;
