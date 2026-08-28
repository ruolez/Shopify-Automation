import { describe, expect, it } from "vitest";
import type { Rule } from "../../types";
import {
  filterRules,
  formatActionLabel,
  formatConditionLabel,
  groupRulesByStatus,
  normalizeConditions,
} from "../../utils/ruleDisplay";

const makeRule = (overrides: Partial<Rule>): Rule => ({
  id: 1,
  name: "Rule",
  conditions: [],
  actions: [],
  priority: 0,
  delay_ms: 0,
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  ...overrides,
});

describe("groupRulesByStatus", () => {
  it("partitions by is_active and orders each group by priority then id", () => {
    const activeLate = makeRule({ id: 3, priority: 20 });
    const activeEarly = makeRule({ id: 4, priority: 5 });
    const activeTieHigherId = makeRule({ id: 7, priority: 5 });
    const inactiveB = makeRule({ id: 2, priority: 50, is_active: false });
    const inactiveA = makeRule({ id: 9, priority: 1, is_active: false });

    expect(
      groupRulesByStatus([
        activeLate,
        inactiveB,
        activeTieHigherId,
        inactiveA,
        activeEarly,
      ]),
    ).toEqual({
      active: [activeEarly, activeTieHigherId, activeLate],
      inactive: [inactiveA, inactiveB],
    });
  });

  it("returns empty groups for no rules", () => {
    expect(groupRulesByStatus([])).toEqual({ active: [], inactive: [] });
  });
});

describe("normalizeConditions", () => {
  const condition = {
    field: "order_total",
    operator: "greater_than",
    value: 100,
  };

  it("wraps the legacy array form in an AND group", () => {
    expect(normalizeConditions([condition])).toEqual({
      operator: "AND",
      conditions: [condition],
    });
  });

  it("passes the group form through", () => {
    expect(
      normalizeConditions({ operator: "OR", conditions: [condition] }),
    ).toEqual({ operator: "OR", conditions: [condition] });
  });

  it("returns an empty AND group for missing conditions", () => {
    expect(normalizeConditions(undefined)).toEqual({
      operator: "AND",
      conditions: [],
    });
  });
});

describe("formatConditionLabel", () => {
  it("humanizes field and operator and joins list values", () => {
    expect(
      formatConditionLabel({
        field: "shipping_country",
        operator: "not_in",
        value: ["US", "CA"],
      }),
    ).toEqual("shipping country not in US, CA");
  });
});

describe("formatActionLabel", () => {
  it.each([
    [
      { type: "add_tag", parameters: { tags: ["heavy", "rush"] } },
      "Add tag: heavy, rush",
    ],
    [{ type: "remove_tag", parameters: { tags: "old" } }, "Remove tag: old"],
    [
      { type: "set_fulfillment_location", parameters: { location_id: "123" } },
      "Set location: 123",
    ],
    [
      { type: "place_on_hold", parameters: { reason: "high_risk_of_fraud" } },
      "Hold: high risk of fraud",
    ],
    [{ type: "send_notification", parameters: {} }, "send notification"],
  ])("formats %j", (action, expected) => {
    expect(formatActionLabel(action)).toEqual(expected);
  });
});

describe("filterRules", () => {
  const tagRule = makeRule({
    id: 1,
    name: "Tag heavy orders",
    description: "Marks bulky shipments",
    conditions: [
      { field: "order_weight", operator: "greater_than", value: 20 },
    ],
    actions: [{ type: "add_tag", parameters: { tags: ["heavy"] } }],
  });
  const holdRule = makeRule({
    id: 2,
    name: "Hold risky",
    conditions: {
      operator: "AND",
      conditions: [
        { field: "shipping_country", operator: "equals", value: "FR" },
      ],
    },
    actions: [{ type: "place_on_hold", parameters: { reason: "high_risk" } }],
  });
  const rules = [tagRule, holdRule];

  it("returns all rules for a blank query", () => {
    expect(filterRules(rules, "   ")).toEqual(rules);
  });

  it.each([
    ["name, case-insensitive", "HEAVY ORDERS", [tagRule]],
    ["description", "bulky", [tagRule]],
    ["condition value", "FR", [holdRule]],
    ["condition field with underscores humanized", "order weight", [tagRule]],
    ["action tag", "heavy", [tagRule]],
    ["hold reason", "high risk", [holdRule]],
    ["nothing", "zzz", []],
  ])("matches on %s", (_label, query, expected) => {
    expect(filterRules(rules, query)).toEqual(expected);
  });
});
