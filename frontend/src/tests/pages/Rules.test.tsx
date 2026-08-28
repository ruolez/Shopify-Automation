import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Rules from "../../pages/Rules";
import * as api from "../../utils/api";
import type { Rule } from "../../types";

vi.mock("../../utils/api");
const mockApi = vi.mocked(api.default);

vi.mock("react-hot-toast", () => ({
  default: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("../../contexts/TimezoneContext", () => ({
  useTimezone: () => ({ timezone: "UTC" }),
}));

vi.mock("framer-motion", async () => {
  const React = await import("react");
  return {
    motion: {
      div: React.forwardRef<HTMLDivElement, any>(
        ({ initial, animate, transition, layout, ...props }, ref) => (
          <div ref={ref} {...props} />
        ),
      ),
    },
  };
});

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

const second = makeRule({ id: 11, name: "Second active", priority: 20 });
const first = makeRule({
  id: 12,
  name: "First active",
  priority: 10,
  conditions: [{ field: "order_weight", operator: "greater_than", value: 20 }],
  actions: [{ type: "add_tag", parameters: { tags: ["heavy"] } }],
});
const paused = makeRule({
  id: 13,
  name: "Paused rule",
  priority: 5,
  is_active: false,
});

const renderRules = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Rules />
      </BrowserRouter>
    </QueryClientProvider>,
  );
};

const mockRules = (rules: Rule[]) => {
  mockApi.get.mockResolvedValue({ data: rules } as any);
};

describe("Rules page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("groups rules into Active (execution order) and Inactive sections", async () => {
    mockRules([second, first, paused]);
    renderRules();

    const activeSection = (await screen.findByText("Active (2)")).closest(
      "section",
    )!;
    const inactiveSection = screen
      .getByText("Inactive (1)")
      .closest("section")!;

    const activeNames = within(activeSection)
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    const inactiveNames = within(inactiveSection)
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    const executionBadges = within(activeSection)
      .getAllByText(/^#\d+$/)
      .map((el) => el.textContent);

    expect({ activeNames, inactiveNames, executionBadges }).toEqual({
      activeNames: ["First active", "Second active"],
      inactiveNames: ["Paused rule"],
      executionBadges: ["#1", "#2"],
    });
  });

  it("shows count chips from the full list", async () => {
    mockRules([second, first, paused]);
    renderRules();

    await screen.findByText("3 total");
    expect(screen.getByText("2 active")).toBeInTheDocument();
    expect(screen.getByText("1 inactive")).toBeInTheDocument();
  });

  it("filters both sections by search and offers to clear when nothing matches", async () => {
    mockRules([second, first, paused]);
    renderRules();
    await screen.findByText("Active (2)");

    fireEvent.change(screen.getByLabelText("Search rules"), {
      target: { value: "heavy" },
    });
    expect(screen.getByText("Active (1)")).toBeInTheDocument();
    expect(screen.queryByText("Second active")).not.toBeInTheDocument();
    expect(screen.queryByText("Inactive (1)")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search rules"), {
      target: { value: "nope" },
    });
    expect(screen.getByText(/No rules match/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Clear search"));
    expect(screen.getByText("Active (2)")).toBeInTheDocument();
  });

  it("optimistically moves a toggled rule to Inactive and PUTs the flipped rule", async () => {
    mockRules([first, paused]);
    let resolvePut: (value: unknown) => void = () => {};
    mockApi.put.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePut = resolve;
        }),
    );
    renderRules();
    await screen.findByText("Active (1)");

    const firstCard = screen.getByTestId("rule-card-12");
    fireEvent.click(within(firstCard).getByRole("switch"));

    await waitFor(() =>
      expect(screen.getByText("Inactive (2)")).toBeInTheDocument(),
    );
    expect(screen.getByText("Active (0)")).toBeInTheDocument();
    expect(mockApi.put).toHaveBeenCalledWith("/rules/12", {
      ...first,
      is_active: false,
    });

    resolvePut({ data: { ...first, is_active: false } });
  });

  it("reverts the optimistic toggle when the update fails", async () => {
    mockRules([first, paused]);
    mockApi.put.mockRejectedValue({ response: { data: { detail: "nope" } } });
    renderRules();
    await screen.findByText("Active (1)");

    fireEvent.click(
      within(screen.getByTestId("rule-card-12")).getByRole("switch"),
    );

    await waitFor(() => expect(mockApi.put).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText("Active (1)")).toBeInTheDocument(),
    );
    expect(screen.getByText("Inactive (1)")).toBeInTheDocument();
  });

  it("disables Start All when every rule is already active", async () => {
    mockRules([first, second]);
    renderRules();
    await screen.findByText("Active (2)");

    expect(screen.getByRole("button", { name: /Start All/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Pause All/ })).toBeEnabled();
  });

  it("warns when rules exist but none are active", async () => {
    mockRules([paused]);
    renderRules();

    expect(
      await screen.findByText(/orders are not being processed/),
    ).toBeInTheDocument();
  });
});
