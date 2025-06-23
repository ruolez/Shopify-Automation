from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, UniqueConstraint
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

class ProcessingRule(Base):
    __tablename__ = "processing_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    conditions = Column(JSON, nullable=False)  # Rule conditions as JSON
    actions = Column(JSON, nullable=False)     # Actions to take as JSON
    priority = Column(Integer, default=0)     # Higher number = higher priority
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="rules")

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
    task_id = Column(String, unique=True, nullable=False, index=True)
    task_name = Column(String, nullable=False)
    status = Column(String, nullable=False)  # pending, running, success, failed
    result = Column(JSON)
    error_message = Column(Text)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    sync_frequency_minutes = Column(Integer, default=10)  # How often to sync orders
    auto_sync_enabled = Column(Boolean, default=True)
    log_retention_days = Column(Integer, default=30)
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