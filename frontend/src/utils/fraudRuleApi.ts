import { api } from "./api";

export interface FraudRuleCondition {
  field: string;
  operator: string;
  value: any;
}

export interface FraudRuleConditionGroup {
  operator: "AND" | "OR";
  conditions: FraudRuleCondition[];
}

export interface FraudRuleAction {
  type: string;
  parameters: Record<string, any>;
}

export interface FraudRule {
  id: number;
  name: string;
  description?: string;
  conditions: FraudRuleCondition[] | FraudRuleConditionGroup;
  actions: FraudRuleAction[];
  priority: number;
  delay_ms: number;
  is_active: boolean;
  created_at: string;
}

export interface FraudRuleForm {
  name: string;
  description?: string;
  conditions: FraudRuleCondition[] | FraudRuleConditionGroup;
  actions: FraudRuleAction[];
  priority: number;
  delay_ms: number;
  is_active: boolean;
}

export interface FraudRuleField {
  field: string;
  label: string;
  type: string;
}

export interface FraudRuleOperator {
  operator: string;
  label: string;
  types: string[];
}

export interface FraudActionType {
  type: string;
  label: string;
  parameters: string[];
}

export interface FraudRuleSchema {
  fields: FraudRuleField[];
  operators: FraudRuleOperator[];
  action_types: FraudActionType[];
}

export const fraudRuleApi = {
  // Get fraud rule schema (fields, operators, actions)
  getSchema: async (): Promise<FraudRuleSchema> => {
    const response = await api.get("/fraud-rules/schema");
    return response.data;
  },

  // List all fraud rules
  listRules: async (): Promise<FraudRule[]> => {
    const response = await api.get("/fraud-rules");
    return response.data;
  },

  // Get specific fraud rule
  getRule: async (id: number): Promise<FraudRule> => {
    const response = await api.get(`/fraud-rules/${id}`);
    return response.data;
  },

  // Create new fraud rule
  createRule: async (rule: FraudRuleForm): Promise<FraudRule> => {
    const response = await api.post("/fraud-rules", rule);
    return response.data;
  },

  // Update existing fraud rule
  updateRule: async (id: number, rule: FraudRuleForm): Promise<FraudRule> => {
    const response = await api.put(`/fraud-rules/${id}`, rule);
    return response.data;
  },

  // Delete fraud rule
  deleteRule: async (id: number): Promise<void> => {
    await api.delete(`/fraud-rules/${id}`);
  },

  // Toggle fraud rule active status
  toggleRule: async (id: number): Promise<FraudRule> => {
    const response = await api.put(`/fraud-rules/${id}/toggle`);
    return response.data;
  },
};

export default fraudRuleApi;