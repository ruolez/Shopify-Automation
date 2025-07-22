import { api } from "./api";

export interface FraudAnalysis {
  id: number;
  user_id: number;
  store_id: number;
  order_name: string;
  shopify_order_id: string;
  
  // 11 fraud detection data points
  is_first_time_customer: boolean | null;
  order_total: number | null;
  transaction_attempts_count: number | null;
  customer_name: string | null;
  duplicate_within_7days: boolean | null;
  previous_order_delivery_status: string | null;
  previous_order_total: number | null;
  current_order_total: number | null;
  shopify_fraud_risk_level: string | null;
  customer_notes: string | null;
  billing_address_outside_us: boolean | null;
  same_billing_shipping: boolean | null;
  shipping_state: string | null;
  additional_details: string | null;
  current_order_delivery_status: string | null;
  days_since_last_delivery: number | null;
  customer_total_orders: number | null;
  
  // Supporting data
  raw_shopify_data: any;
  duplicate_match_details: any;
  transaction_details: any;
  risk_assessment_details: any;
  customer_order_history: any;
  delivery_analytics: any;
  
  // Fraud rule processing tracking
  rule_triggered_ids: number[] | null;
  rule_processing_results: any;
  
  // Metadata
  analysis_timestamp: string;
  processing_time_seconds: number | null;
  analysis_version: string;
  
  // Archive fields (optional for backward compatibility)
  is_archived?: boolean;
  archive_reason?: string;
  archived_at?: string;
}

export interface FraudAnalysisResult {
  analysis: FraudAnalysis;
  store_name: string;
}

export interface FraudAnalysisCreateResponse {
  message: string;
  analysis_id: number;
  status: "completed" | "existing";
  order_name: string;
  analyzed_at: string | null;
}

export interface FraudStats {
  total_analyses: number;
  high_risk_count: number;
  medium_risk_count: number;
  low_risk_count: number;
  average_fraud_score: number;
  recent_analyses: number;
  risk_distribution: {
    high: number;
    medium: number;
    low: number;
  };
}

export interface FraudAnalysisFilters {
  store_id?: number;
  risk_level?: "low" | "medium" | "high";
  date_from?: string;
  date_to?: string;
  min_fraud_score?: number;
  max_fraud_score?: number;
  search?: string;
  matched_rules?: string;  // Comma-separated list of rules
  skip?: number;
  limit?: number;
  sort_field?: string;
  sort_direction?: "asc" | "desc";
}

export const fraudApi = {
  // Analyze a specific order for fraud
  analyzeOrder: async (
    storeId: number,
    orderName: string,
  ): Promise<FraudAnalysisCreateResponse> => {
    const response = await api.post(`/fraud-detection/analyze/${storeId}?order_name=${orderName}`);
    return response.data;
  },

  // Get fraud analyses with filtering and pagination
  getFraudAnalyses: async (
    params: FraudAnalysisFilters = {},
  ): Promise<{
    analyses: FraudAnalysis[];
    total: number;
    skip: number;
    limit: number;
  }> => {
    const searchParams = new URLSearchParams();

    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        searchParams.append(key, value.toString());
      }
    });

    const response = await api.get(
      `/fraud-detection/analyses?${searchParams.toString()}`,
    );
    return response.data;
  },

  // Get detailed fraud analysis by ID
  getFraudAnalysis: async (
    analysisId: number,
  ): Promise<FraudAnalysisResult> => {
    const response = await api.get(`/fraud-detection/analysis/${analysisId}`);
    return response.data;
  },

  // Get fraud statistics
  getFraudStats: async (
    params: {
      store_id?: number;
      date_from?: string;
      date_to?: string;
    } = {},
  ): Promise<FraudStats> => {
    const searchParams = new URLSearchParams();

    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        searchParams.append(key, value.toString());
      }
    });

    const response = await api.get(`/fraud-detection/stats?${searchParams.toString()}`);
    return response.data;
  },

  // Get archived fraud analyses with filtering and pagination
  getArchivedFraudAnalyses: async (
    params: FraudAnalysisFilters = {},
  ): Promise<{
    analyses: FraudAnalysis[];
    total: number;
    skip: number;
    limit: number;
  }> => {
    const searchParams = new URLSearchParams();

    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        searchParams.append(key, value.toString());
      }
    });

    const response = await api.get(
      `/fraud-detection/archived-analyses?${searchParams.toString()}`,
    );
    
    // Transform data to match the expected format
    return {
      analyses: response.data.data,
      total: response.data.total,
      skip: response.data.skip,
      limit: response.data.limit,
    };
  },

  // Manually archive a fraud analysis for testing
  manuallyArchiveAnalysis: async (
    analysisId: number,
    archiveReason: string = "manual_archive"
  ): Promise<{
    message: string;
    analysis_id: number;
    order_name: string;
    archive_reason: string;
    archived_at: string;
  }> => {
    const response = await api.post(
      `/fraud-detection/archive/${analysisId}?archive_reason=${archiveReason}`
    );
    return response.data;
  },

  // Bulk archive all fulfilled and cancelled orders
  bulkArchiveFulfilledCancelled: async (): Promise<{
    message: string;
    archived_count: number;
    checked_count: number;
    archived_orders: Array<{
      order_name: string;
      archive_reason: string;
    }>;
  }> => {
    const response = await api.post("/fraud-detection/archive-fulfilled-cancelled");
    return response.data;
  },
};

export default fraudApi;
