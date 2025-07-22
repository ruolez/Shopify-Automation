import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RuleBuilder from "../../pages/RuleBuilder";
import * as api from "../../utils/api";
import { AuthProvider } from "../../contexts/AuthContext";

// Mock the API
vi.mock("../../utils/api");
const mockApi = vi.mocked(api.default);

// Mock react-router-dom
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({}), // Mock empty params for creating new rule
  };
});

// Mock react-hot-toast
vi.mock("react-hot-toast", () => ({
  default: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockSchema = {
  fields: [
    { field: "order_total", label: "Order Total", type: "number" },
    { field: "order_weight", label: "Order Weight", type: "number" },
    { field: "shipping_state", label: "Shipping State", type: "string" },
  ],
  operators: [
    { operator: "equals", label: "Equals", types: ["string", "number"] },
    { operator: "greater_than", label: "Greater Than", types: ["number"] },
    { operator: "contains", label: "Contains", types: ["string", "array"] },
  ],
  action_types: [
    { type: "add_tags", label: "Add Tags" },
    { type: "move_fulfillment", label: "Move Fulfillment" },
  ],
};

const TestWrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>{children}</AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

describe("RuleBuilder Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Mock schema API call
    mockApi.get.mockImplementation((url) => {
      if (url === "/rules/schema") {
        return Promise.resolve({ data: mockSchema });
      }
      return Promise.reject(new Error("Not found"));
    });
  });

  it("renders rule builder form", async () => {
    render(
      <TestWrapper>
        <RuleBuilder />
      </TestWrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText("Create Rule")).toBeInTheDocument();
    });

    expect(screen.getByLabelText(/rule name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/description/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/priority/i)).toBeInTheDocument();
    expect(screen.getByText("Conditions")).toBeInTheDocument();
    expect(screen.getByText("Actions")).toBeInTheDocument();
  });

  it("allows adding and removing conditions", async () => {
    render(
      <TestWrapper>
        <RuleBuilder />
      </TestWrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText("Create Rule")).toBeInTheDocument();
    });

    // Should have one condition by default
    expect(screen.getAllByText("Field")).toHaveLength(1);

    // Add another condition
    const addConditionButton = screen.getByText("Add Condition");
    fireEvent.click(addConditionButton);

    expect(screen.getAllByText("Field")).toHaveLength(2);

    // Remove a condition (should be able to remove when more than 1)
    const removeButtons = screen.getAllByRole("button");
    const removeButton = removeButtons.find(
      (btn) =>
        btn.querySelector("svg") && btn.classList.contains("text-red-600"),
    );

    if (removeButton) {
      fireEvent.click(removeButton);
      expect(screen.getAllByText("Field")).toHaveLength(1);
    }
  });

  it("allows adding and removing actions", async () => {
    render(
      <TestWrapper>
        <RuleBuilder />
      </TestWrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText("Create Rule")).toBeInTheDocument();
    });

    // Should have one action by default
    expect(screen.getAllByText("Action Type")).toHaveLength(1);

    // Add another action
    const addActionButton = screen.getByText("Add Action");
    fireEvent.click(addActionButton);

    expect(screen.getAllByText("Action Type")).toHaveLength(2);
  });

  it("validates required fields", async () => {
    render(
      <TestWrapper>
        <RuleBuilder />
      </TestWrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText("Create Rule")).toBeInTheDocument();
    });

    // Try to submit without filling required fields
    const submitButton = screen.getByText("Create Rule");
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(
        screen.getByText(/rule name must be at least 3 characters/i),
      ).toBeInTheDocument();
    });
  });

  it("submits form with valid data", async () => {
    mockApi.post.mockResolvedValueOnce({
      data: { id: 1, name: "Test Rule" },
    });

    render(
      <TestWrapper>
        <RuleBuilder />
      </TestWrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText("Create Rule")).toBeInTheDocument();
    });

    // Fill out the form
    const nameInput = screen.getByLabelText(/rule name/i);
    fireEvent.change(nameInput, { target: { value: "Test Rule" } });

    const descriptionInput = screen.getByLabelText(/description/i);
    fireEvent.change(descriptionInput, {
      target: { value: "Test description" },
    });

    // Set up condition
    const fieldSelects = screen.getAllByDisplayValue("");
    const fieldSelect = fieldSelects.find(
      (select) =>
        select.closest("div")?.querySelector("label")?.textContent === "Field",
    );
    if (fieldSelect) {
      fireEvent.change(fieldSelect, { target: { value: "order_total" } });
    }

    // Set up action
    const actionSelects = screen.getAllByDisplayValue("");
    const actionSelect = actionSelects.find(
      (select) =>
        select.closest("div")?.querySelector("label")?.textContent ===
        "Action Type",
    );
    if (actionSelect) {
      fireEvent.change(actionSelect, { target: { value: "add_tags" } });
    }

    // Submit form
    const submitButton = screen.getByText("Create Rule");
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockApi.post).toHaveBeenCalledWith("/rules", expect.any(Object));
    });
  });

  it("handles form submission error", async () => {
    const mockError = {
      response: {
        data: {
          detail: "Validation error",
        },
      },
    };

    mockApi.post.mockRejectedValueOnce(mockError);

    render(
      <TestWrapper>
        <RuleBuilder />
      </TestWrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText("Create Rule")).toBeInTheDocument();
    });

    // Fill minimum required fields
    const nameInput = screen.getByLabelText(/rule name/i);
    fireEvent.change(nameInput, { target: { value: "Test Rule" } });

    // Submit form
    const submitButton = screen.getByText("Create Rule");
    fireEvent.click(submitButton);

    await waitFor(() => {
      expect(mockApi.post).toHaveBeenCalled();
    });
  });

  it("navigates back when cancel is clicked", async () => {
    render(
      <TestWrapper>
        <RuleBuilder />
      </TestWrapper>,
    );

    await waitFor(() => {
      expect(screen.getByText("Create Rule")).toBeInTheDocument();
    });

    const cancelButton = screen.getByText("Cancel");
    fireEvent.click(cancelButton);

    expect(mockNavigate).toHaveBeenCalledWith("/rules");
  });
});
