import React from "react";

export interface ProfitDetails {
  revenue: number | null;
  product_cost: number | null;
  profit: number | null;
  margin_percent: number | null;
  missing_cost_count: number | null;
  shipping_cost: number | null;
  currency?: string | null;
  truncated?: boolean;
  shipping_estimate?: {
    shipping_cost: number | null;
    source: "estimate" | "default" | "none";
    samples: number;
    tolerance_g: number | null;
    shipping_state?: string | null;
    weight_grams?: number | null;
  };
}

export interface ProfitCondition {
  field: string;
  operator: string;
  value: any;
  actual?: number | null;
}

const FIELD_LABELS: Record<string, string> = {
  order_profit: "profit",
  order_profit_margin: "margin",
  line_items_missing_cost: "items without cost",
  estimated_shipping_cost: "est. shipping",
  shipping_estimate_samples: "shipping samples",
};

const OPERATOR_SYMBOLS: Record<string, string> = {
  less_than: "<",
  less_than_or_equal: "≤",
  greater_than: ">",
  greater_than_or_equal: "≥",
  equals: "=",
  not_equals: "≠",
};

const MONEY_FIELDS = new Set(["order_profit", "estimated_shipping_cost"]);
const PERCENT_FIELDS = new Set(["order_profit_margin"]);

export const formatMoney = (amount: number | null | undefined, currency: string) => {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return "—";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount);
  } catch {
    return `$${amount.toFixed(2)}`;
  }
};

const formatFieldValue = (field: string, value: any, currency: string) => {
  const n = typeof value === "number" ? value : parseFloat(value);
  if (Number.isNaN(n)) return String(value ?? "—");
  if (MONEY_FIELDS.has(field)) return formatMoney(n, currency);
  if (PERCENT_FIELDS.has(field)) return `${n.toFixed(2)}%`;
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
};

const thresholdOutcome = (condition: ProfitCondition, currency: string): string => {
  const actual = typeof condition.actual === "number" ? condition.actual : NaN;
  const target = typeof condition.value === "number" ? condition.value : parseFloat(condition.value);
  if (Number.isNaN(actual) || Number.isNaN(target)) return "";
  const diff = Math.abs(actual - target);
  const diffText = formatFieldValue(condition.field, diff, currency);
  switch (condition.operator) {
    case "less_than":
    case "less_than_or_equal":
      return `${diffText} below`;
    case "greater_than":
    case "greater_than_or_equal":
      return `${diffText} above`;
    case "equals":
      return "matches";
    default:
      return "";
  }
};

const shippingNote = (profit: ProfitDetails): string => {
  const est = profit.shipping_estimate;
  if (!est || est.source === "none" || profit.shipping_cost === null) return "not estimated";
  if (est.source === "default") return "default amount";
  const band = est.tolerance_g ? `, ±${est.tolerance_g} g` : "";
  return `${est.samples} similar order${est.samples === 1 ? "" : "s"}${band}`;
};

const Row: React.FC<{ label: string; amount: string; note?: string; emphasize?: boolean }> = ({
  label,
  amount,
  note,
  emphasize,
}) => (
  <>
    <span className={emphasize ? "font-semibold text-gray-700 dark:text-dark-700" : ""}>{label}</span>
    <span
      className={`text-right whitespace-nowrap tabular-nums ${
        emphasize ? "font-semibold text-gray-700 dark:text-dark-700" : ""
      }`}
    >
      {amount}
    </span>
    <span className="text-gray-400 dark:text-dark-300 whitespace-nowrap">{note ? `(${note})` : ""}</span>
  </>
);

const ProfitBreakdown: React.FC<{ profit: ProfitDetails; conditions?: ProfitCondition[] }> = ({
  profit,
  conditions = [],
}) => {
  const currency = profit.currency || "USD";

  if (profit.profit === null || profit.profit === undefined) {
    return (
      <div className="mt-1 text-xs text-amber-600 dark:text-amber-400">
        Profit could not be calculated
        {profit.truncated ? " (line items truncated)" : ""}.
      </div>
    );
  }

  const showsMargin = conditions.some((c) => c.field === "order_profit_margin");
  const shippingAmount = profit.shipping_cost === null ? "—" : formatMoney(profit.shipping_cost, currency);

  return (
    <div className="mt-1 text-xs text-gray-600 dark:text-dark-500">
      <div className="grid grid-cols-[max-content_max-content_max-content] gap-x-3 gap-y-0.5 items-baseline">
        <Row label="Order total (excl. tax)" amount={formatMoney(profit.revenue, currency)} />
        <Row
          label="− Product cost"
          amount={formatMoney(profit.product_cost, currency)}
          note={
            profit.missing_cost_count
              ? `${profit.missing_cost_count} item${profit.missing_cost_count === 1 ? "" : "s"} without cost`
              : undefined
          }
        />
        <Row label="− Est. shipping" amount={shippingAmount} note={shippingNote(profit)} />
        <Row label="= Profit" amount={formatMoney(profit.profit, currency)} emphasize />
        {showsMargin && profit.margin_percent !== null && (
          <Row label="Margin" amount={`${profit.margin_percent.toFixed(2)}%`} />
        )}
      </div>
      {conditions.map((condition, index) => {
        const outcome = thresholdOutcome(condition, currency);
        return (
          <div key={`${condition.field}-${index}`} className="mt-0.5 whitespace-nowrap">
            Threshold: {FIELD_LABELS[condition.field] || condition.field}{" "}
            {OPERATOR_SYMBOLS[condition.operator] || condition.operator}{" "}
            {formatFieldValue(condition.field, condition.value, currency)}
            {outcome && (
              <>
                {" "}
                → <span className="font-semibold text-gray-700 dark:text-dark-700">{outcome}</span>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default ProfitBreakdown;
