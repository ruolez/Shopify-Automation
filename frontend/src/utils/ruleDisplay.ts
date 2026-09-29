import type {
  MetafieldAggregate,
  Rule,
  RuleAction,
  RuleCondition,
  RuleConditionGroup,
} from "../types";

export const METAFIELD_AGGREGATES: {
  value: MetafieldAggregate;
  label: string;
  short: string;
}[] = [
  { value: "sum", label: "Sum × quantity", short: "sum × qty" },
  { value: "max", label: "Highest item value", short: "highest item" },
  { value: "any", label: "Any item matches", short: "any item" },
  { value: "all", label: "All items match", short: "all items" },
];

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

const conditionSubject = (condition: RuleCondition): string => {
  const metafield = condition.metafield;
  if (condition.field !== "product_metafield" || !metafield) {
    return humanize(condition.field ?? "");
  }
  const aggregate = METAFIELD_AGGREGATES.find(
    (option) => option.value === metafield.aggregate,
  );
  return aggregate ? `${metafield.key} (${aggregate.short})` : metafield.key;
};

export const formatConditionLabel = (condition: RuleCondition): string =>
  [
    conditionSubject(condition),
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
