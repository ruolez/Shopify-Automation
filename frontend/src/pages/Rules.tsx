import React, { useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { Disclosure } from "@headlessui/react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  PlusIcon,
  PlayIcon,
  PauseIcon,
  ChevronDownIcon,
  MagnifyingGlassIcon,
  XMarkIcon,
} from "@heroicons/react/24/outline";
import toast from "react-hot-toast";
import api from "../utils/api";
import type { Rule } from "../types";
import LoadingSpinner from "../components/LoadingSpinner";
import RuleCard from "../components/RuleCard";
import { useTimezone } from "../contexts/TimezoneContext";
import { filterRules, groupRulesByStatus } from "../utils/ruleDisplay";

const RULES_QUERY_KEY = ["rules"];

const cardMotion = (index: number) => ({
  layout: true,
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { delay: Math.min(index, 8) * 0.04 },
});

const Rules: React.FC = () => {
  const queryClient = useQueryClient();
  const { timezone } = useTimezone();
  const [search, setSearch] = useState("");

  const { data: rules, isLoading } = useQuery<Rule[]>({
    queryKey: RULES_QUERY_KEY,
    queryFn: async () => {
      const response = await api.get("/rules");
      return response.data;
    },
  });

  const invalidateRules = () => {
    queryClient.invalidateQueries({ queryKey: RULES_QUERY_KEY });
    queryClient.invalidateQueries({ queryKey: ["dashboard-stats"] });
  };

  const deleteRuleMutation = useMutation({
    mutationFn: async (ruleId: number) => {
      await api.delete(`/rules/${ruleId}`);
    },
    onSuccess: () => {
      invalidateRules();
      toast.success("Rule deleted successfully");
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || "Failed to delete rule");
    },
  });

  const toggleRuleMutation = useMutation({
    mutationFn: async (rule: Rule) => {
      const response = await api.put(`/rules/${rule.id}`, {
        ...rule,
        is_active: !rule.is_active,
      });
      return response.data;
    },
    onMutate: async (rule: Rule) => {
      await queryClient.cancelQueries({ queryKey: RULES_QUERY_KEY });
      const previous = queryClient.getQueryData<Rule[]>(RULES_QUERY_KEY);
      queryClient.setQueryData<Rule[]>(RULES_QUERY_KEY, (current) =>
        (current ?? []).map((item) =>
          item.id === rule.id ? { ...item, is_active: !item.is_active } : item,
        ),
      );
      return { previous };
    },
    onError: (error: any, _rule, context) => {
      if (context?.previous) {
        queryClient.setQueryData(RULES_QUERY_KEY, context.previous);
      }
      toast.error(error.response?.data?.detail || "Failed to update rule");
    },
    onSettled: invalidateRules,
  });

  const activateAllRulesMutation = useMutation({
    mutationFn: async () => {
      const response = await api.put("/rules/bulk/activate");
      return response.data;
    },
    onSuccess: (data) => {
      invalidateRules();
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
      invalidateRules();
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

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  const allRules = rules ?? [];
  const totals = groupRulesByStatus(allRules);
  const { active, inactive } = groupRulesByStatus(
    filterRules(allRules, search),
  );
  const isSearching = search.trim() !== "";
  const nothingMatches =
    isSearching && active.length === 0 && inactive.length === 0;

  const renderCard = (rule: Rule, index: number, executionIndex?: number) => (
    <motion.div key={rule.id} {...cardMotion(index)}>
      <RuleCard
        rule={rule}
        executionIndex={executionIndex}
        timezone={timezone}
        isToggling={
          toggleRuleMutation.isPending &&
          toggleRuleMutation.variables?.id === rule.id
        }
        onToggle={(r) => toggleRuleMutation.mutate(r)}
        onDelete={handleDeleteRule}
      />
    </motion.div>
  );

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
          {allRules.length > 0 && (
            <>
              <button
                onClick={handleActivateAll}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-green-700 bg-green-100 hover:bg-green-200 dark:bg-green-900/20 dark:text-green-400 dark:hover:bg-green-900/30 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={
                  activateAllRulesMutation.isPending ||
                  totals.inactive.length === 0
                }
                title={
                  totals.inactive.length === 0
                    ? "All rules are already active"
                    : "Activate all rules"
                }
              >
                <PlayIcon className="h-5 w-5 mr-2" />
                Start All
              </button>
              <button
                onClick={handleDeactivateAll}
                className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-red-700 bg-red-100 hover:bg-red-200 dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/30 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={
                  deactivateAllRulesMutation.isPending ||
                  totals.active.length === 0
                }
                title={
                  totals.active.length === 0
                    ? "No active rules to pause"
                    : "Deactivate all rules"
                }
              >
                <PauseIcon className="h-5 w-5 mr-2" />
                Pause All
              </button>
            </>
          )}
          <Link
            to="/rules/new"
            className="btn-primary inline-flex items-center"
          >
            <PlusIcon className="h-5 w-5 mr-2" />
            Create Rule
          </Link>
        </div>
      </div>

      {allRules.length > 0 ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-sm">
              <span className="inline-flex items-center rounded-full bg-gray-100 px-3 py-1 font-medium text-gray-700 dark:bg-dark-200 dark:text-dark-700">
                {allRules.length} total
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-3 py-1 font-medium text-green-800 dark:bg-green-900/20 dark:text-green-400">
                <span className="h-2 w-2 rounded-full bg-green-500" />
                {totals.active.length} active
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-3 py-1 font-medium text-gray-600 dark:bg-dark-200 dark:text-dark-500">
                <span className="h-2 w-2 rounded-full bg-gray-400" />
                {totals.inactive.length} inactive
              </span>
            </div>
            <div className="relative w-full max-w-xs">
              <MagnifyingGlassIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search rules…"
                aria-label="Search rules"
                className="input pl-9 pr-8"
              />
              {isSearching && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  aria-label="Clear search"
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-gray-400 hover:text-gray-600 dark:hover:text-dark-700"
                >
                  <XMarkIcon className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>

          {nothingMatches ? (
            <div className="rounded-lg border border-dashed border-gray-300 py-10 text-center text-sm text-gray-500 dark:border-dark-300 dark:text-dark-400">
              No rules match “{search.trim()}”.{" "}
              <button
                type="button"
                onClick={() => setSearch("")}
                className="font-medium text-shopify-600 hover:underline"
              >
                Clear search
              </button>
            </div>
          ) : (
            <>
              <section
                aria-labelledby="active-rules-heading"
                className="space-y-3"
              >
                <div className="flex items-baseline gap-3">
                  <h2
                    id="active-rules-heading"
                    className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-gray-700 dark:text-dark-700"
                  >
                    <span className="h-2.5 w-2.5 rounded-full bg-green-500" />
                    Active ({active.length})
                  </h2>
                  {active.length > 0 && (
                    <span className="text-xs text-gray-400 dark:text-dark-400">
                      Runs in this order, top to bottom
                    </span>
                  )}
                </div>
                {active.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-700/50 dark:bg-amber-900/10 dark:text-amber-300">
                    {isSearching
                      ? "No active rules match your search."
                      : "No active rules — orders are not being processed. Enable a rule below or create one."}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {active.map((rule, index) =>
                      renderCard(rule, index, index + 1),
                    )}
                  </div>
                )}
              </section>

              {inactive.length > 0 && (
                <Disclosure defaultOpen>
                  {({ open }) => (
                    <section
                      aria-labelledby="inactive-rules-heading"
                      className="space-y-3"
                    >
                      <Disclosure.Button className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-gray-500 hover:text-gray-700 dark:text-dark-500 dark:hover:text-dark-700">
                        <span className="h-2.5 w-2.5 rounded-full bg-gray-400" />
                        <span id="inactive-rules-heading">
                          Inactive ({inactive.length})
                        </span>
                        <ChevronDownIcon
                          className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
                        />
                      </Disclosure.Button>
                      <Disclosure.Panel className="space-y-3">
                        {inactive.map((rule, index) => renderCard(rule, index))}
                      </Disclosure.Panel>
                    </section>
                  )}
                </Disclosure>
              )}
            </>
          )}
        </>
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
              <Link
                to="/rules/new"
                className="btn-primary inline-flex items-center"
              >
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
