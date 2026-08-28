import React from "react";
import { Link } from "react-router-dom";
import { Switch } from "@headlessui/react";
import { PencilIcon, TrashIcon } from "@heroicons/react/24/outline";
import type { Rule } from "../types";
import { formatShortDate } from "../utils/dateFormat";
import {
  formatActionLabel,
  formatConditionLabel,
  normalizeConditions,
} from "../utils/ruleDisplay";

type RuleCardProps = {
  rule: Rule;
  executionIndex?: number;
  timezone: string;
  isToggling: boolean;
  onToggle: (rule: Rule) => void;
  onDelete: (ruleId: number) => void;
};

const metaChip =
  "inline-flex items-center rounded-md bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-dark-200 dark:text-dark-600";
const conditionChip =
  "inline-flex items-center rounded-md border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs text-gray-700 dark:border-dark-300 dark:bg-dark-200 dark:text-dark-700";
const actionChip =
  "inline-flex items-center rounded-md bg-shopify-200/40 px-2 py-0.5 text-xs font-medium text-shopify-800 dark:bg-shopify-800/30 dark:text-shopify-200";

const RuleCard: React.FC<RuleCardProps> = ({
  rule,
  executionIndex,
  timezone,
  isToggling,
  onToggle,
  onDelete,
}) => {
  const { operator, conditions } = normalizeConditions(rule.conditions);
  const actions = rule.actions ?? [];

  return (
    <div
      data-testid={`rule-card-${rule.id}`}
      className={`card p-4 ${
        rule.is_active
          ? ""
          : "border-dashed opacity-60 hover:opacity-100 focus-within:opacity-100"
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            {executionIndex !== undefined && (
              <span className="inline-flex h-6 min-w-[1.75rem] items-center justify-center rounded-md bg-green-100 px-1.5 font-mono text-xs font-semibold text-green-800 dark:bg-green-900/30 dark:text-green-300">
                #{executionIndex}
              </span>
            )}
            <h3 className="truncate text-base font-semibold text-gray-900 dark:text-dark-800">
              {rule.name}
            </h3>
            <span className={metaChip}>Priority {rule.priority}</span>
            {rule.delay_ms > 0 && (
              <span className={metaChip}>⏱ {rule.delay_ms} ms</span>
            )}
          </div>

          {rule.description && (
            <p className="mt-1 text-sm text-gray-600 dark:text-dark-500">
              {rule.description}
            </p>
          )}

          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="w-16 shrink-0 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-dark-400">
                When
              </span>
              {conditions.length === 0 ? (
                <span className="text-xs italic text-gray-400 dark:text-dark-400">
                  No conditions
                </span>
              ) : (
                <>
                  {conditions.length > 1 && (
                    <span className="inline-flex items-center rounded-md bg-blue-100 px-1.5 py-0.5 text-[10px] font-bold text-blue-800 dark:bg-blue-900/30 dark:text-blue-300">
                      {operator}
                    </span>
                  )}
                  {conditions.map((condition, index) => (
                    <span key={index} className={conditionChip}>
                      {formatConditionLabel(condition)}
                    </span>
                  ))}
                </>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="w-16 shrink-0 text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-dark-400">
                Then
              </span>
              {actions.length === 0 ? (
                <span className="text-xs italic text-gray-400 dark:text-dark-400">
                  No actions
                </span>
              ) : (
                actions.map((action, index) => (
                  <span key={index} className={actionChip}>
                    {formatActionLabel(action)}
                  </span>
                ))
              )}
            </div>
          </div>

          <p className="mt-3 text-xs text-gray-400 dark:text-dark-300">
            Created {formatShortDate(rule.created_at, timezone)}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <Switch
            checked={rule.is_active}
            onChange={() => onToggle(rule)}
            disabled={isToggling}
            title={rule.is_active ? "Deactivate rule" : "Activate rule"}
            className={`${
              rule.is_active ? "bg-shopify-600" : "bg-gray-300 dark:bg-dark-300"
            } relative mr-2 inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none disabled:opacity-50`}
          >
            <span className="sr-only">Toggle rule active status</span>
            <span
              className={`${
                rule.is_active ? "translate-x-6" : "translate-x-1"
              } inline-block h-4 w-4 transform rounded-full bg-white transition-transform`}
            />
          </Switch>
          <Link
            to={`/rules/${rule.id}/edit`}
            className="rounded-lg p-2 text-gray-600 transition-colors hover:bg-gray-50 dark:text-dark-500 dark:hover:bg-dark-200"
            title="Edit rule"
          >
            <PencilIcon className="h-5 w-5" />
          </Link>
          <button
            type="button"
            onClick={() => onDelete(rule.id)}
            className="rounded-lg p-2 text-red-600 transition-colors hover:bg-red-50 dark:hover:bg-red-900/20"
            title="Delete rule"
          >
            <TrashIcon className="h-5 w-5" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default RuleCard;
