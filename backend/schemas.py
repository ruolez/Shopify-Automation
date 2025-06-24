from pydantic import BaseModel, EmailStr, validator
from typing import Optional, List, Dict, Any
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
    token_type: str

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
    
class RuleAction(BaseModel):
    type: str  # add_tag, set_fulfillment_location
    parameters: Dict[str, Any]

class RuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    conditions: List[RuleCondition]
    actions: List[RuleAction]
    priority: int = 0
    is_active: bool = True
    
    @validator('name')
    def validate_name(cls, v):
        if len(v.strip()) < 3:
            raise ValueError('Rule name must be at least 3 characters long')
        return v.strip()

class RuleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    conditions: List[RuleCondition]
    actions: List[RuleAction]
    priority: int
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

# Task schemas
class TaskStatusResponse(BaseModel):
    task_id: str
    task_name: str
    status: str
    result: Optional[Dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True

# Settings schemas
class SettingsBase(BaseModel):
    sync_frequency_minutes: int = 10
    auto_sync_enabled: bool = True
    log_retention_days: int = 30

class SettingsUpdate(SettingsBase):
    pass

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