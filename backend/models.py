from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, UniqueConstraint, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    stores = relationship("ShopifyStore", back_populates="user", cascade="all, delete-orphan")
    rules = relationship("ProcessingRule", back_populates="user", cascade="all, delete-orphan")
    order_logs = relationship("OrderLog", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("Settings", back_populates="user", uselist=False, cascade="all, delete-orphan")
    location_aliases = relationship("LocationAlias", back_populates="user", cascade="all, delete-orphan")
    excluded_skus = relationship("ExcludedSKU", back_populates="user", cascade="all, delete-orphan")
    fraud_analyses = relationship("FraudAnalysis", back_populates="user", cascade="all, delete-orphan")
    fraud_detection_rules = relationship("FraudDetectionRule", back_populates="user", cascade="all, delete-orphan")
    task_statuses = relationship("TaskStatus", back_populates="user", cascade="all, delete-orphan")

class ShopifyStore(Base):
    __tablename__ = "shopify_stores"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shop_domain = Column(String, nullable=False, index=True)
    shop_name = Column(String, nullable=False)
    access_token = Column(Text, nullable=False)  # Encrypted in production
    is_active = Column(Boolean, default=True)
    last_sync = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="stores")
    order_logs = relationship("OrderLog", back_populates="store", cascade="all, delete-orphan")
    location_mappings = relationship("LocationMapping", back_populates="store", cascade="all, delete-orphan")
    fraud_analyses = relationship("FraudAnalysis", back_populates="store", cascade="all, delete-orphan")

class ProcessingRule(Base):
    __tablename__ = "processing_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    conditions = Column(JSON, nullable=False)  # Rule conditions as JSON
    actions = Column(JSON, nullable=False)     # Actions to take as JSON
    priority = Column(Integer, default=0)     # Higher number = higher priority
    delay_ms = Column(Integer, default=10)    # Delay in milliseconds after rule execution
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="rules")

class FraudDetectionRule(Base):
    __tablename__ = "fraud_detection_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    conditions = Column(JSON, nullable=False)  # Rule conditions as JSON
    actions = Column(JSON, nullable=False)     # Actions to take as JSON
    priority = Column(Integer, default=0)     # Higher number = higher priority
    delay_ms = Column(Integer, default=10)    # Delay in milliseconds after rule execution
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="fraud_detection_rules")

class OrderLog(Base):
    __tablename__ = "order_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    store_id = Column(Integer, ForeignKey("shopify_stores.id"), nullable=False)
    order_id = Column(String, nullable=False, index=True)  # Shopify order ID
    order_number = Column(String, nullable=False)
    action = Column(String, nullable=False)  # tag_added, fulfillment_updated, etc.
    status = Column(String, nullable=False)  # success, failed, pending
    details = Column(JSON)  # Additional details about the action
    error_message = Column(Text)  # Error details if failed
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="order_logs")
    store = relationship("ShopifyStore", back_populates="order_logs")

class TaskStatus(Base):
    __tablename__ = "task_status"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # nullable for backward compatibility
    task_id = Column(String, unique=True, nullable=False, index=True)
    task_name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # pending, running, success, failed
    result = Column(JSON)
    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    user = relationship("User", back_populates="task_statuses")

class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    sync_frequency_minutes = Column(Integer, default=10)  # How often to sync orders
    auto_sync_enabled = Column(Boolean, default=True)
    fraud_sync_enabled = Column(Boolean, default=True)  # Whether to run fraud detection independently
    log_retention_days = Column(Integer, default=30)
    sync_window_days = Column(Integer, default=7)  # How many days back to fetch orders during sync
    duplicate_detection_days = Column(Integer, default=7)  # How many days to check for duplicate orders in fraud detection
    fraud_sync_days = Column(Integer, default=7)  # Default days to look back when manually triggering fraud analysis
    reconciliation_batch_size = Column(Integer, default=500)  # Number of fraud analyses to process per reconciliation run
    timezone = Column(String, default="UTC")  # User's preferred timezone
    date_format = Column(String, default="MMM d, yyyy HH:mm")  # User's preferred date format
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="settings")

class ProcessedOrder(Base):
    __tablename__ = "processed_orders"
    
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("shopify_stores.id"), nullable=False)
    order_id = Column(String, nullable=False, index=True)  # Shopify order ID
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Unique constraint to prevent duplicate processing
    __table_args__ = (
        UniqueConstraint('store_id', 'order_id', name='unique_store_order'),
    )

class ProcessedFraudOrder(Base):
    __tablename__ = "processed_fraud_orders"
    
    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("shopify_stores.id"), nullable=False)
    order_id = Column(String, nullable=False, index=True)  # Shopify order ID
    fraud_analysis_id = Column(Integer, ForeignKey("fraud_analyses.id"))  # Link to analysis
    rules_applied = Column(Integer, default=0)  # Count of rules that matched
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Unique constraint to prevent duplicate processing
    __table_args__ = (
        UniqueConstraint('store_id', 'order_id', name='unique_store_fraud_order'),
    )

class LocationAlias(Base):
    __tablename__ = "location_aliases"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    alias_name = Column(String, nullable=False)  # "Main Warehouse", "East Coast Hub"
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="location_aliases")
    mappings = relationship("LocationMapping", back_populates="alias", cascade="all, delete-orphan")
    
    # Unique constraint per user
    __table_args__ = (
        UniqueConstraint('user_id', 'alias_name', name='unique_user_alias'),
    )

class LocationMapping(Base):
    __tablename__ = "location_mappings"
    
    id = Column(Integer, primary_key=True, index=True)
    alias_id = Column(Integer, ForeignKey("location_aliases.id"), nullable=False)
    store_id = Column(Integer, ForeignKey("shopify_stores.id"), nullable=False)
    shopify_location_id = Column(String, nullable=False)  # gid://shopify/Location/123
    shopify_location_name = Column(String, nullable=False)  # "125 N. Willow st"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    alias = relationship("LocationAlias", back_populates="mappings")
    store = relationship("ShopifyStore", back_populates="location_mappings")
    
    # Unique constraint: one mapping per alias per store
    __table_args__ = (
        UniqueConstraint('alias_id', 'store_id', name='unique_alias_store'),
    )

class OutOfStockIncident(Base):
    __tablename__ = "out_of_stock_incidents"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    store_id = Column(Integer, ForeignKey("shopify_stores.id"), nullable=False)
    order_id = Column(String, nullable=False, index=True)  # Shopify order ID
    order_number = Column(String, nullable=False, index=True)  # Human readable order number
    
    # Product information
    product_id = Column(String, nullable=False, index=True)  # Shopify product ID
    variant_id = Column(String, nullable=False, index=True)  # Shopify variant ID
    product_title = Column(String, nullable=False)
    variant_title = Column(String)
    sku = Column(String, index=True)
    vendor = Column(String, index=True)
    product_type = Column(String, index=True)
    
    # Incident details
    quantity_attempted = Column(Integer, default=1)  # How many units tried to fulfill
    attempted_location_id = Column(String, nullable=False)  # Target fulfillment location
    attempted_location_alias = Column(String)  # Location alias used
    rule_name = Column(String, nullable=False)  # Which rule triggered this
    
    # Timestamps
    incident_date = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User")
    store = relationship("ShopifyStore")
    
    # Index for efficient queries
    __table_args__ = (
        # Index for product-based queries
        {'mysql_key_block_size': '1024'}
    )

class ExcludedSKU(Base):
    __tablename__ = "excluded_skus"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sku_pattern = Column(String, nullable=False, index=True)  # SKU pattern to match (can contain wildcards)
    description = Column(Text)  # Optional description for why excluded
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="excluded_skus")
    
    # Unique constraint per user
    __table_args__ = (
        UniqueConstraint('user_id', 'sku_pattern', name='unique_user_excluded_sku'),
    )

class AdminUser(Base):
    __tablename__ = "admin_users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="admin", nullable=False)  # admin, super_admin, support, read_only
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    audit_logs = relationship("AdminAuditLog", back_populates="admin_user", cascade="all, delete-orphan")

class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False)
    action = Column(String, nullable=False)  # login, user_create, user_delete, etc.
    target_type = Column(String)  # user, store, rule, system
    target_id = Column(String)  # ID of the affected entity
    details = Column(JSON)  # Additional action details
    ip_address = Column(String)
    user_agent = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    admin_user = relationship("AdminUser", back_populates="audit_logs")

class SystemSettings(Base):
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    value = Column(JSON, nullable=False)
    description = Column(Text)
    is_public = Column(Boolean, default=False)  # Whether regular users can see this setting
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class FraudAnalysis(Base):
    __tablename__ = "fraud_analyses"
    
    # Core identification
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    store_id = Column(Integer, ForeignKey("shopify_stores.id"), nullable=False)
    order_name = Column(String, nullable=False, index=True)
    shopify_order_id = Column(String, nullable=False, index=True)
    
    # ALL 11 required fraud detection data points
    is_first_time_customer = Column(Boolean)
    order_total = Column(Numeric(12, 2))
    transaction_attempts_count = Column(Integer)
    customer_name = Column(String)
    duplicate_within_7days = Column(Boolean)
    previous_order_delivery_status = Column(String)
    previous_order_total = Column(Numeric(12, 2))
    current_order_total = Column(Numeric(12, 2))  # For comparison display
    shopify_fraud_risk_level = Column(String)  # low/medium/high
    customer_notes = Column(Text)
    billing_address_outside_us = Column(Boolean)
    same_billing_shipping = Column(Boolean)  # True if billing and shipping addresses match
    shipping_state = Column(String)  # Shipping state/province in UPPERCASE
    additional_details = Column(Text)  # Raw additional details from customAttributes
    current_order_delivery_status = Column(String)  # Delivery tracking status for current order
    days_since_last_delivery = Column(Integer)  # Number of days between current order and previous delivery
    customer_total_orders = Column(Integer)  # Total number of orders the customer has placed
    previous_order_cancelled = Column(Boolean)  # True if previous order was cancelled
    
    # Supporting data for analysis and fine-tuning
    raw_shopify_data = Column(JSON)  # Complete order data from Shopify
    duplicate_match_details = Column(JSON)  # What matched in duplicate detection
    transaction_details = Column(JSON)  # All transaction information
    risk_assessment_details = Column(JSON)  # Full Shopify risk analysis
    customer_order_history = Column(JSON)  # Customer's order history
    delivery_analytics = Column(JSON)  # Comprehensive delivery tracking analytics
    
    # Fraud rule processing tracking
    rule_triggered_ids = Column(JSON)  # List of fraud detection rule IDs that were triggered
    rule_processing_results = Column(JSON)  # Results and details of rule processing actions
    
    # Analysis metadata
    analysis_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    processing_time_seconds = Column(Numeric(8, 4))
    analysis_version = Column(String, default="1.0")  # For tracking logic changes
    
    # Relationships
    user = relationship("User", back_populates="fraud_analyses")
    store = relationship("ShopifyStore", back_populates="fraud_analyses")
    
    # Index for efficient queries
    __table_args__ = (
        # Index for order-based queries
        UniqueConstraint('store_id', 'order_name', name='unique_store_order_fraud_analysis'),
    )