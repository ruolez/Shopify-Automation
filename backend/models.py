from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey, JSON, UniqueConstraint, Numeric, Index
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import func
from database import Base
from encryption import encrypt_token, decrypt_token

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
    shipping_cost_samples = relationship("ShippingCostSample", back_populates="user", cascade="all, delete-orphan")

class ShopifyStore(Base):
    __tablename__ = "shopify_stores"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    shop_domain = Column(String, nullable=False, index=True)
    shop_name = Column(String, nullable=False)
    _access_token_encrypted = Column("access_token", Text, nullable=False)  # Encrypted using Fernet
    is_active = Column(Boolean, default=True)
    last_sync = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # OAuth connection metadata (auth_method="manual" for pasted admin tokens)
    auth_method = Column(String, default="manual", nullable=False)  # manual | oauth
    granted_scopes = Column(Text)
    _refresh_token_encrypted = Column("oauth_refresh_token", Text)  # Encrypted using Fernet
    token_expires_at = Column(DateTime(timezone=True))
    installed_at = Column(DateTime(timezone=True))
    needs_reauth = Column(Boolean, default=False)

    @hybrid_property
    def access_token(self) -> str:
        """Decrypt and return the access token."""
        return decrypt_token(self._access_token_encrypted)

    @access_token.setter
    def access_token(self, value: str):
        """Encrypt and store the access token."""
        self._access_token_encrypted = encrypt_token(value)

    @hybrid_property
    def refresh_token(self):
        """Decrypt and return the OAuth refresh token (None when not set)."""
        return decrypt_token(self._refresh_token_encrypted) if self._refresh_token_encrypted else None

    @refresh_token.setter
    def refresh_token(self, value):
        """Encrypt and store the OAuth refresh token."""
        self._refresh_token_encrypted = encrypt_token(value) if value else None

    # Relationships
    user = relationship("User", back_populates="stores")
    order_logs = relationship("OrderLog", back_populates="store", cascade="all, delete-orphan")
    location_mappings = relationship("LocationMapping", back_populates="store", cascade="all, delete-orphan")
    fraud_analyses = relationship("FraudAnalysis", back_populates="store", cascade="all, delete-orphan")
    fraud_rule_stores = relationship("FraudRuleStore", back_populates="store", cascade="all, delete-orphan")
    shipping_cost_samples = relationship("ShippingCostSample", back_populates="store", cascade="all, delete-orphan")

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
    store_mappings = relationship("FraudRuleStore", back_populates="rule", cascade="all, delete-orphan")
    applicable_stores = relationship(
        "ShopifyStore",
        secondary="fraud_rule_stores",
        viewonly=True,
    )

class FraudRuleStore(Base):
    __tablename__ = "fraud_rule_stores"

    id = Column(Integer, primary_key=True, index=True)
    fraud_rule_id = Column(Integer, ForeignKey("fraud_detection_rules.id", ondelete="CASCADE"), nullable=False)
    store_id = Column(Integer, ForeignKey("shopify_stores.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    rule = relationship("FraudDetectionRule", back_populates="store_mappings")
    store = relationship("ShopifyStore", back_populates="fraud_rule_stores")

    __table_args__ = (
        UniqueConstraint('fraud_rule_id', 'store_id', name='unique_fraud_rule_store'),
    )

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
    inventory_verification_excluded_tag = Column(String(255), nullable=True)  # Tag to exclude from inventory verification
    inventory_verification_days_back = Column(Integer, default=5)  # How many days to look back for inventory verification
    # Shipper platform MS SQL connection (shipping cost estimates); configured = host + name + user set
    shipper_db_host = Column(String(255), nullable=True)
    shipper_db_port = Column(Integer, default=1433)
    shipper_db_name = Column(String(255), nullable=True)
    shipper_db_user = Column(String(255), nullable=True)
    _shipper_db_password_encrypted = Column("shipper_db_password", Text, nullable=True)  # Encrypted using Fernet
    default_shipping_amount = Column(Numeric(10, 2), default=0)  # Used when no shipping estimate is possible; 0 = none
    shipper_db_last_sync_at = Column(DateTime(timezone=True), nullable=True)
    shipper_db_last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    @hybrid_property
    def shipper_db_password(self):
        """Decrypt and return the shipper database password (None when not set)."""
        return decrypt_token(self._shipper_db_password_encrypted) if self._shipper_db_password_encrypted else None

    @shipper_db_password.setter
    def shipper_db_password(self, value):
        """Encrypt and store the shipper database password."""
        self._shipper_db_password_encrypted = encrypt_token(value) if value else None

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
    __table_args__ = ()

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


class ShippingCostSample(Base):
    """A shipped order (one per Shopify order name) with its real shipping cost from the
    shipper platform, used to estimate shipping for new orders by state and weight."""
    __tablename__ = "shipping_cost_samples"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    store_id = Column(Integer, ForeignKey("shopify_stores.id"), nullable=False)
    order_name = Column(String(64), nullable=False)  # Shopify order name == parcels.order_number
    shipping_state = Column(String(64), nullable=False)  # UPPERCASE Shopify province name, as fraud_analyses.shipping_state
    weight_grams = Column(Numeric(10, 2), nullable=False)  # Rule-engine order weight (with the user's SKU exclusions)
    shipping_cost = Column(Numeric(10, 2), nullable=False)  # SUM(parcels.cost) for the order
    parcel_count = Column(Integer, nullable=False, default=1)
    shipped_at = Column(Date, nullable=False)
    synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="shipping_cost_samples")
    store = relationship("ShopifyStore", back_populates="shipping_cost_samples")

    __table_args__ = (
        UniqueConstraint("store_id", "order_name", name="uq_shipping_cost_samples_store_order"),
        Index("ix_shipping_cost_samples_lookup", "store_id", "shipping_state", "shipped_at", "weight_grams"),
    )
