import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import OrderRiskEvaluation, { RiskLevelBadge } from "../../components/OrderRiskEvaluation";
import type { OrderRisk } from "../../components/OrderRiskEvaluation";

const IP = "72.24.210.88";
const LOCATION = "Odessa, Texas, United States";
const NEGATIVE_FACT = "Shipping address is 465 miles from location of IP address";
const POSITIVE_FACT = "Card Verification Value (CVV) is correct";
const NEUTRAL_FACT = "Shipping address is 71 miles from location of IP address";

const risk = (overrides: Partial<OrderRisk> = {}): OrderRisk => ({
  level: "HIGH",
  recommendation: "CANCEL",
  assessments: [
    {
      provider: null,
      level: "HIGH",
      facts: [
        { description: NEGATIVE_FACT, sentiment: "NEGATIVE" },
        { description: POSITIVE_FACT, sentiment: "POSITIVE" },
        { description: NEUTRAL_FACT, sentiment: "NEUTRAL" },
      ],
    },
  ],
  ip: IP,
  ip_location: LOCATION,
  ...overrides,
});

describe("OrderRiskEvaluation", () => {
  it("shows the level, recommendation, facts with their sentiment and the IP details", () => {
    render(<OrderRiskEvaluation risk={risk()} />);
    expect(screen.getByText("High risk")).toBeInTheDocument();
    expect(screen.getByText("Consider canceling this order")).toBeInTheDocument();
    expect(
      [NEGATIVE_FACT, POSITIVE_FACT, NEUTRAL_FACT].map((fact) => screen.getByText(fact).closest("li")?.dataset.sentiment),
    ).toEqual(["NEGATIVE", "POSITIVE", "NEUTRAL"]);
    expect(screen.getByText(`IP address: ${IP}`)).toBeInTheDocument();
    expect(screen.getByText(`Location of IP address used to place the order is ${LOCATION}`)).toBeInTheDocument();
  });

  it.each([
    ["ACCEPT", "You can fulfill this order"],
    ["INVESTIGATE", "Investigate this order before fulfilling it"],
  ] as const)("maps the %s recommendation to its advice", (recommendation, advice) => {
    render(<OrderRiskEvaluation risk={risk({ level: "LOW", recommendation })} />);
    expect(screen.getByText(advice)).toBeInTheDocument();
  });

  it("says the analysis is in progress while Shopify's assessment is pending", () => {
    render(<OrderRiskEvaluation risk={risk({ level: "PENDING", recommendation: "NONE", assessments: [] })} />);
    expect([screen.getByText("Risk analysis in progress").tagName, screen.queryByText(/risk$/)]).toEqual(["P", null]);
  });

  it("names third-party providers and leaves the location line out when it is unknown", () => {
    const signifyd = { provider: "Signifyd", level: "LOW" as const, facts: [] };
    render(<OrderRiskEvaluation risk={risk({ ip_location: null, assessments: [...risk().assessments, signifyd] })} />);
    expect([screen.getByText("Signifyd: Low risk"), screen.queryByText(/^Location of IP address/)]).toEqual([
      expect.anything(),
      null,
    ]);
  });
});

describe("RiskLevelBadge", () => {
  it.each([
    ["HIGH", "High risk"],
    ["MEDIUM", "Medium risk"],
    ["LOW", "Low risk"],
    ["PENDING", "Risk pending"],
  ] as const)("labels %s as %s", (level, label) => {
    render(<RiskLevelBadge level={level} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it.each([null, "NONE"] as const)("renders nothing for %s", (level) => {
    const { container } = render(<RiskLevelBadge level={level} />);
    expect(container).toBeEmptyDOMElement();
  });
});
