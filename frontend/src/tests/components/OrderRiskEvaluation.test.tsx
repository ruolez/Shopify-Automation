import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import OrderRiskEvaluation, {
  CardholderMatchBadge,
  CardholderMatchFilter,
  RiskLevelBadge,
  RiskLevelFilter,
} from "../../components/OrderRiskEvaluation";
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
  cardholder: null,
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

describe("OrderRiskEvaluation cardholder name check", () => {
  const CARD_NAME = "Charles Anderson";
  const ORDER_NAME = "Kristol Anderson";

  it.each([
    ["MATCH", "Name on card matches the order"],
    ["LAST_NAME_ONLY", "Only the last name on the card matches the order"],
    ["MISMATCH", "Name on card does not match the billing or shipping name"],
  ] as const)("describes a %s result", (status, text) => {
    const cardholder = { status, card_names: [CARD_NAME], billing_name: ORDER_NAME, shipping_name: null };
    render(<OrderRiskEvaluation risk={risk({ cardholder })} />);
    expect(screen.getByText(text).closest("[data-cardholder-match]")?.getAttribute("data-cardholder-match")).toEqual(status);
  });

  it("lists the names that were compared, leaving out a missing one", () => {
    const cardholder = { status: "LAST_NAME_ONLY" as const, card_names: [CARD_NAME], billing_name: ORDER_NAME, shipping_name: null };
    render(<OrderRiskEvaluation risk={risk({ cardholder })} />);
    expect(screen.getByText(`Name on card: ${CARD_NAME} · Billing: ${ORDER_NAME}`)).toBeInTheDocument();
  });

  it("names every card when several paid", () => {
    const cardholder = { status: "MISMATCH" as const, card_names: [CARD_NAME, "John Smith"], billing_name: ORDER_NAME, shipping_name: ORDER_NAME };
    render(<OrderRiskEvaluation risk={risk({ cardholder })} />);
    expect(
      screen.getByText(`Names on cards: ${CARD_NAME}, John Smith · Billing: ${ORDER_NAME} · Shipping: ${ORDER_NAME}`),
    ).toBeInTheDocument();
  });
});

describe("CardholderMatchBadge", () => {
  it.each([
    ["MISMATCH", "Name mismatch"],
    ["LAST_NAME_ONLY", "Last name only"],
    ["MATCH", "Name matches"],
  ] as const)("labels %s as %s", (match, label) => {
    render(<CardholderMatchBadge match={match} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("renders nothing without a result", () => {
    const { container } = render(<CardholderMatchBadge match={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("CardholderMatchFilter", () => {
  it("summarizes the selection and keeps it worst first", () => {
    const onChange = vi.fn();
    render(<CardholderMatchFilter value={["LAST_NAME_ONLY"]} onChange={onChange} />);
    expect(screen.getByRole("button")).toHaveTextContent("Last name only");
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByRole("option", { name: /Mismatch/ }));
    expect(onChange.mock.calls).toEqual([[["MISMATCH", "LAST_NAME_ONLY"]]]);
  });

  it("shows the placeholder when nothing is selected", () => {
    render(<CardholderMatchFilter value={[]} onChange={() => {}} />);
    expect(screen.getByRole("button")).toHaveTextContent("Any Match");
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

describe("RiskLevelFilter", () => {
  it("summarizes the selection on the button", () => {
    const { rerender } = render(<RiskLevelFilter value={[]} onChange={() => {}} />);
    expect(screen.getByRole("button")).toHaveTextContent("All Levels");
    rerender(<RiskLevelFilter value={["HIGH", "MEDIUM"]} onChange={() => {}} />);
    expect(screen.getByRole("button")).toHaveTextContent("High, Medium");
  });

  it("adds and removes levels, keeping them in severity order", () => {
    const onChange = vi.fn();
    const { rerender } = render(<RiskLevelFilter value={["LOW"]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByRole("option", { name: /High/ }));
    rerender(<RiskLevelFilter value={["LOW"]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("option", { name: /Low/ }));
    expect(onChange.mock.calls).toEqual([[["HIGH", "LOW"]], [[]]]);
  });
});
