export interface User {
  id: number;
  email: string;
  full_name: string;
  created_at: string;
}

export interface Store {
  id: number;
  shop_domain: string;
  shop_name: string;
  is_active: boolean;
  created_at: string;
  last_sync?: string;
}

export interface RuleCondition {
  field: string;
  operator: string;
  value: any;
}

export interface RuleConditionGroup {
  operator: "AND" | "OR";
  conditions: RuleCondition[];
}

export interface RuleAction {
  type: string;
  parameters: Record<string, any>;
}

export interface Rule {
  id: number;
  name: string;
  description?: string;
  conditions: RuleCondition[] | RuleConditionGroup;
  actions: RuleAction[];
  priority: number;
  delay_ms: number;
  is_active: boolean;
  created_at: string;
}

export interface OrderLog {
  id: number;
  order_number: string;
  action: string;
  status: string;
  details?: Record<string, any>;
  error_message?: string;
  created_at: string;
}

export interface DashboardStats {
  stores: {
    total: number;
    active: number;
  };
  rules: {
    total: number;
    active: number;
  };
  recent_activity: OrderLog[];
}

export interface RuleField {
  field: string;
  label: string;
  type: string;
}

export interface RuleOperator {
  operator: string;
  label: string;
  types: string[];
}

export interface ActionType {
  type: string;
  label: string;
  parameters: string[];
}

export interface RuleSchema {
  fields: RuleField[];
  operators: RuleOperator[];
  action_types: ActionType[];
  hold_reasons?: { value: string; label: string }[];
}

export interface Location {
  id: string;
  name: string;
  address?: {
    province?: string;
    country?: string;
    city?: string;
  };
  fulfillsOnlineOrders: boolean;
  isActive: boolean;
}

export interface LoginForm {
  email: string;
  password: string;
}

export interface RegisterForm {
  email: string;
  full_name: string;
  password: string;
}

export interface StoreForm {
  shop_domain: string;
  access_token: string;
}

export interface RuleForm {
  name: string;
  description?: string;
  conditions: RuleCondition[] | RuleConditionGroup;
  actions: RuleAction[];
  priority: number;
  delay_ms: number;
  is_active: boolean;
}

// Fraud Rule Types
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
