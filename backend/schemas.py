from pydantic import BaseModel, EmailStr, validator
from typing import Optional, List, Dict, Any, Union
from datetime import datetime

# User schemas
class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        return v

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str

# Store schemas
class ShopifyStoreCreate(BaseModel):
    shop_domain: str
    access_token: str
    
    @validator('shop_domain')
    def validate_shop_domain(cls, v):
        v = v.strip().lower()
        if not v.endswith('.myshopify.com'):
            if '.' not in v:
                v = f"{v}.myshopify.com"
            else:
                raise ValueError('Invalid shop domain format')
        return v

class ShopifyStoreResponse(BaseModel):
    id: int
    shop_domain: str
    shop_name: str
    is_active: bool
    created_at: datetime
    last_sync: Optional[datetime]
    
    class Config:
        from_attributes = True

# Rule schemas
class RuleCondition(BaseModel):
    field: str  # order_total, weight, shipping_state, etc.
    operator: str  # equals, greater_than, less_than, contains, etc.
    value: Any
    
    @validator('operator')
    def validate_fulfillment_location_operators(cls, v, values):
        # For fulfillment_location field, only allow equals and not_equals
        if values.get('field') == 'fulfillment_location':
            if v not in ['equals', 'not_equals']:
                raise ValueError('fulfillment_location field only supports equals and not_equals operators')
        return v
    
class RuleAction(BaseModel):
    type: str  # add_tag, set_fulfillment_location
    parameters: Dict[str, Any]

class RuleConditionGroup(BaseModel):
    operator: str = "AND"  # AND or OR
    conditions: List[RuleCondition]
    
    @validator('operator')
    def validate_operator(cls, v):
        if v.upper() not in ["AND", "OR"]:
            raise ValueError('Operator must be AND or OR')
        return v.upper()

class RuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    conditions: Union[List[RuleCondition], RuleConditionGroup]  # Support both formats
    actions: List[RuleAction]
    priority: int = 0
    delay_ms: int = 10  # Delay in milliseconds after rule execution
    is_active: bool = True
    
    @validator('name')
    def validate_name(cls, v):
        if len(v.strip()) < 3:
            raise ValueError('Rule name must be at least 3 characters long')
        return v.strip()
    
    @validator('delay_ms')
    def validate_delay_ms(cls, v):
        if v < 0:
            raise ValueError('Delay must be non-negative')
        if v > 60000:  # Max 60 seconds
            raise ValueError('Delay must be no more than 60 seconds (60000ms)')
        return v
    
    @validator('conditions')
    def normalize_conditions(cls, v):
        # If conditions is already a list (legacy format), convert to new format
        if isinstance(v, list):
            # Convert RuleCondition objects to dicts if needed
            conditions_list = []
            for condition in v:
                if hasattr(condition, 'dict'):
                    conditions_list.append(condition.dict())
                else:
                    conditions_list.append(condition)
            return {"operator": "AND", "conditions": conditions_list}
        # If it's already in the new format, ensure operator is uppercase
        elif isinstance(v, dict) and "conditions" in v:
            v["operator"] = v.get("operator", "AND").upper()
            # Convert nested RuleCondition objects to dicts if needed
            conditions_list = []
            for condition in v["conditions"]:
                if hasattr(condition, 'dict'):
                    conditions_list.append(condition.dict())
                else:
                    conditions_list.append(condition)
            v["conditions"] = conditions_list
            return v
        return v

class RuleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    conditions: Union[List[RuleCondition], RuleConditionGroup]
    actions: List[RuleAction]
    priority: int
    delay_ms: int
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

# Order schemas
class OrderLogResponse(BaseModel):
    id: int
    order_number: str
    action: str
    status: str
    details: Optional[Dict[str, Any]]
    error_message: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True

# Dashboard schemas
class DashboardStats(BaseModel):
    stores: Dict[str, int]
    rules: Dict[str, int]
    recent_activity: List[OrderLogResponse]

# Task schemas - TaskStatusResponse defined below with FailedTasksResponse

# Settings schemas
class SettingsBase(BaseModel):
    sync_frequency_minutes: int = 10
    auto_sync_enabled: bool = True
    fraud_sync_enabled: bool = True
    log_retention_days: int = 30
    sync_window_days: int = 7
    duplicate_detection_days: int = 7
    fraud_sync_days: int = 7
    reconciliation_batch_size: int = 500
    timezone: str = "UTC"
    date_format: str = "MMM d, yyyy HH:mm"
    inventory_verification_excluded_tag: Optional[str] = None

class SettingsUpdate(BaseModel):
    sync_frequency_minutes: Optional[int] = None
    auto_sync_enabled: Optional[bool] = None
    fraud_sync_enabled: Optional[bool] = None
    log_retention_days: Optional[int] = None
    sync_window_days: Optional[int] = None
    duplicate_detection_days: Optional[int] = None
    fraud_sync_days: Optional[int] = None
    reconciliation_batch_size: Optional[int] = None
    timezone: Optional[str] = None
    date_format: Optional[str] = None
    inventory_verification_excluded_tag: Optional[str] = None
    
    @validator('duplicate_detection_days')
    def validate_duplicate_detection_days(cls, v):
        if v is not None and (v < 1 or v > 365):
            raise ValueError('Duplicate detection days must be between 1 and 365')
        return v
    
    @validator('fraud_sync_days')
    def validate_fraud_sync_days(cls, v):
        if v is not None and (v < 1 or v > 365):
            raise ValueError('Fraud sync days must be between 1 and 365')
        return v
    
    @validator('reconciliation_batch_size')
    def validate_reconciliation_batch_size(cls, v):
        if v is not None and (v < 100 or v > 2000):
            raise ValueError('Reconciliation batch size must be between 100 and 2000')
        return v

class SettingsResponse(SettingsBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Order Log query schemas
class OrderLogQuery(BaseModel):
    store_id: Optional[int] = None
    status: Optional[str] = None
    action: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    page: int = 1
    per_page: int = 50

# Location Alias schemas
class LocationAliasCreate(BaseModel):
    alias_name: str
    description: Optional[str] = None
    
    @validator('alias_name')
    def validate_alias_name(cls, v):
        v = v.strip()
        if len(v) < 2:
            raise ValueError('Alias name must be at least 2 characters long')
        if len(v) > 50:
            raise ValueError('Alias name must be no more than 50 characters')
        return v

class LocationAliasUpdate(BaseModel):
    alias_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    
    @validator('alias_name')
    def validate_alias_name(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) < 2:
                raise ValueError('Alias name must be at least 2 characters long')
            if len(v) > 50:
                raise ValueError('Alias name must be no more than 50 characters')
        return v

class LocationMappingResponse(BaseModel):
    id: int
    store_id: int
    store_name: str
    store_domain: str
    shopify_location_id: str
    shopify_location_name: str
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class LocationAliasResponse(BaseModel):
    id: int
    alias_name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    mappings: List[LocationMappingResponse]
    
    class Config:
        from_attributes = True

# Location Mapping schemas
class LocationMappingCreate(BaseModel):
    store_id: int
    shopify_location_id: str
    shopify_location_name: str
    
class LocationMappingUpdate(BaseModel):
    shopify_location_id: Optional[str] = None
    shopify_location_name: Optional[str] = None
    is_active: Optional[bool] = None

# Store Location schema for listing available locations
class StoreLocationResponse(BaseModel):
    store_id: int
    store_name: str
    store_domain: str
    locations: List[Dict[str, str]]  # [{"id": "gid://...", "name": "Location Name"}]

# Excluded SKU schemas
class ExcludedSKUCreate(BaseModel):
    sku_pattern: str
    description: Optional[str] = None
    
    @validator('sku_pattern')
    def validate_sku_pattern(cls, v):
        if not v or not v.strip():
            raise ValueError('SKU pattern cannot be empty')
        return v.strip()

class ExcludedSKUUpdate(BaseModel):
    sku_pattern: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    
    @validator('sku_pattern')
    def validate_sku_pattern(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError('SKU pattern cannot be empty')
        return v.strip() if v else v

class ExcludedSKUResponse(BaseModel):
    id: int
    sku_pattern: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Admin schemas
class AdminUserCreate(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    password: str
    role: str = "admin"
    
    @validator('username')
    def validate_username(cls, v):
        if len(v.strip()) < 3:
            raise ValueError('Username must be at least 3 characters long')
        return v.strip()
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        return v
    
    @validator('role')
    def validate_role(cls, v):
        allowed_roles = ["admin", "super_admin", "support", "read_only"]
        if v not in allowed_roles:
            raise ValueError(f'Role must be one of: {", ".join(allowed_roles)}')
        return v

class AdminUserLogin(BaseModel):
    username: str
    password: str

class AdminUserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    
    @validator('role')
    def validate_role(cls, v):
        if v is not None:
            allowed_roles = ["admin", "super_admin", "support", "read_only"]
            if v not in allowed_roles:
                raise ValueError(f'Role must be one of: {", ".join(allowed_roles)}')
        return v

class AdminUserChangePassword(BaseModel):
    current_password: str
    new_password: str
    
    @validator('new_password')
    def validate_new_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        return v

class AdminUserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True

class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

class AdminAuditLogResponse(BaseModel):
    id: int
    admin_user_id: int
    action: str
    target_type: Optional[str]
    target_id: Optional[str]
    details: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    admin_user: AdminUserResponse
    
    class Config:
        from_attributes = True

class SystemStatsResponse(BaseModel):
    total_users: int
    active_users: int
    total_stores: int
    active_stores: int
    total_rules: int
    active_rules: int
    total_processed_orders: int
    total_order_logs: int
    recent_registrations: int  # Last 7 days

class UserManagementResponse(BaseModel):
    id: int
    email: str
    full_name: str
    is_active: bool
    created_at: datetime
    stores_count: int
    rules_count: int
    last_activity: Optional[datetime]

# Fraud Detection Rule schemas
class FraudRuleCondition(BaseModel):
    field: str  # first_time_customer, order_total, fraud_risk_level, etc.
    operator: str  # equals, greater_than, less_than, contains, etc.
    value: Any

class FraudRuleAction(BaseModel):
    type: str  # log_fraud, flag_order, add_note, etc.
    parameters: Dict[str, Any]

class FraudRuleConditionGroup(BaseModel):
    operator: str = "AND"  # AND or OR
    conditions: List[FraudRuleCondition]
    
    @validator('operator')
    def validate_operator(cls, v):
        if v.upper() not in ["AND", "OR"]:
            raise ValueError('Operator must be AND or OR')
        return v.upper()

class FraudRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    conditions: Union[List[FraudRuleCondition], FraudRuleConditionGroup]  # Support both formats
    actions: List[FraudRuleAction]
    priority: int = 0
    delay_ms: int = 10  # Delay in milliseconds after rule execution
    is_active: bool = True
    store_ids: Optional[List[int]] = None  # None or [] = applies to all stores
    
    @validator('name')
    def validate_name(cls, v):
        if len(v.strip()) < 3:
            raise ValueError('Fraud rule name must be at least 3 characters long')
        return v.strip()
    
    @validator('delay_ms')
    def validate_delay_ms(cls, v):
        if v < 0:
            raise ValueError('Delay must be non-negative')
        if v > 60000:  # Max 60 seconds
            raise ValueError('Delay must be no more than 60 seconds (60000ms)')
        return v
    
    @validator('conditions', pre=True)
    def normalize_conditions(cls, v):
        """Convert list format to object format for consistency"""
        if isinstance(v, list):
            return FraudRuleConditionGroup(conditions=v)
        return v

class FraudRuleStoreBrief(BaseModel):
    id: int
    shop_name: str
    shop_domain: str

    class Config:
        from_attributes = True


class FraudRuleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    conditions: Dict[str, Any]
    actions: List[Dict[str, Any]]
    priority: int
    delay_ms: int
    is_active: bool
    stores: List[FraudRuleStoreBrief] = []
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True

# Task Status Schemas
class TaskStatusResponse(BaseModel):
    id: int
    user_id: Optional[int]
    task_id: str
    task_name: str
    status: str
    result: Optional[Dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True

class FailedTasksResponse(BaseModel):
    tasks: List[TaskStatusResponse]
    total: int
    page: int
    per_page: int
    pages: int

# Inventory Management Schemas
class InventorySearchRequest(BaseModel):
    barcode: str
    
class ProductVariantInfo(BaseModel):
    variant_id: str
    title: str
    sku: Optional[str]
    barcode: Optional[str]
    product_id: str
    product_title: str
    inventory_item_id: str

class InventoryQuantities(BaseModel):
    available: int
    on_hand: int
    committed: int
    # Optional verification fields - backward compatible
    verification_quantity: Optional[int] = None
    verification_metadata: Optional[Dict[str, Any]] = None
    
class InventoryLocationLevel(BaseModel):
    store_id: int
    store_name: str
    location_id: str
    location_name: str
    location_alias: Optional[str]
    quantities: InventoryQuantities
    inventory_item_id: Optional[str] = None  # Store-specific inventory item ID
    
class InventorySearchResponse(BaseModel):
    barcode: str
    variants: List[ProductVariantInfo]
    inventory_levels: List[InventoryLocationLevel]
    # Optional verification summary - backward compatible
    verification_summary: Optional[Dict[str, Any]] = None
    
class InventoryUpdateItem(BaseModel):
    store_id: int
    location_id: str
    inventory_item_id: str
    available: Optional[int] = None
    on_hand: Optional[int] = None
    
class InventoryUpdateRequest(BaseModel):
    updates: List[InventoryUpdateItem]
    
class InventoryUpdateResult(BaseModel):
    store_id: int
    location_id: str
    success: bool
    error: Optional[str] = None
    changes: Optional[Dict[str, Any]] = None
    
class InventoryUpdateResponse(BaseModel):
    results: List[InventoryUpdateResult]
    total: int
    successful: int
