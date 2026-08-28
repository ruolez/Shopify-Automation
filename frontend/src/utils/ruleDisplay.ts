import type {
  Rule,
  RuleAction,
  RuleCondition,
  RuleConditionGroup,
} from "../types";

export type RuleGroups = { active: Rule[]; inactive: Rule[] };

export const humanize = (value: string): string => value.replace(/_/g, " ");

const byPriorityThenId = (a: Rule, b: Rule): number =>
  a.priority - b.priority || a.id - b.id;

export const groupRulesByStatus = (rules: Rule[]): RuleGroups => ({
  active: rules.filter((rule) => rule.is_active).sort(byPriorityThenId),
  inactive: rules.filter((rule) => !rule.is_active).sort(byPriorityThenId),
});

export const normalizeConditions = (
  conditions: Rule["conditions"] | null | undefined,
): RuleConditionGroup => {
  if (Array.isArray(conditions)) {
    return { operator: "AND", conditions };
  }
  if (conditions && Array.isArray(conditions.conditions)) {
    return {
      operator: conditions.operator === "OR" ? "OR" : "AND",
      conditions: conditions.conditions,
    };
  }
  return { operator: "AND", conditions: [] };
};

const stringifyValue = (value: unknown): string => {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(stringifyValue).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

export const formatConditionLabel = (condition: RuleCondition): string =>
  [
    humanize(condition.field ?? ""),
    humanize(condition.operator ?? ""),
    stringifyValue(condition.value),
  ]
    .filter((part) => part !== "")
    .join(" ");

export const formatActionLabel = (action: RuleAction): string => {
  const params = action.parameters ?? {};
  switch (action.type) {
    case "add_tag":
      return `Add tag: ${stringifyValue(params.tags)}`;
    case "remove_tag":
      return `Remove tag: ${stringifyValue(params.tags)}`;
    case "set_fulfillment_location":
      return `Set location: ${stringifyValue(params.location_id)}`;
    case "place_on_hold":
      return `Hold: ${humanize(stringifyValue(params.reason))}`;
    default:
      return humanize(action.type ?? "");
  }
};

const searchableText = (rule: Rule): string =>
  [
    rule.name,
    rule.description ?? "",
    ...normalizeConditions(rule.conditions).conditions.map(
      formatConditionLabel,
    ),
    ...(rule.actions ?? []).map(formatActionLabel),
  ]
    .join(" ")
    .toLowerCase();

export const filterRules = (rules: Rule[], query: string): Rule[] => {
  const needle = query.trim().toLowerCase();
  if (needle === "") return rules;
  return rules.filter((rule) => searchableText(rule).includes(needle));
};
