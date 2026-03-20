"""
Fraud analysis service for Shopify orders.
Analyzes orders for potential fraud indicators and stores results for ML training.
"""
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from models import FraudAnalysis, ShopifyStore, User
from shopify_client import ShopifyClient
from enhanced_shopify_client import EnhancedShopifyClient
from database import get_db
from logging_config import get_logger, debug_log, DEBUG_LOGGING

logger = get_logger(__name__)


def format_ordinal_date(dt: datetime) -> str:
    """Format datetime to ordinal date format like 'August 5th 2025'"""
    day = dt.day
    if 4 <= day <= 20 or 24 <= day <= 30:
        suffix = "th"
    else:
        suffix = ["st", "nd", "rd"][day % 10 - 1]
    
    return dt.strftime(f"%B {day}{suffix} %Y")


class FraudAnalysisService:
    """Service for analyzing Shopify orders for fraud indicators."""
    
    def __init__(self, db: Session, store: ShopifyStore, user: User):
        """Initialize the fraud analysis service.
        
        Args:
            db: Database session
            store: ShopifyStore instance
            user: User instance
        """
        self.db = db
        self.store = store
        self.user = user
        self.client = ShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
        # Enhanced client for better delivery tracking
        self.enhanced_client = EnhancedShopifyClient(
            shop_domain=store.shop_domain,
            access_token=store.access_token
        )
    
    def analyze_order_fraud(self, order_data: Dict[str, Any]) -> Optional[FraudAnalysis]:
        """Analyze an order for fraud indicators and save to database.
        
        Args:
            order_data: Raw order data from Shopify (structured by shopify_client)
            
        Returns:
            FraudAnalysis instance if successful, None otherwise
        """
        try:
            # CRITICAL: Ensure we have fresh database session before analysis
            self.db.expire_all()  # Clear session cache to avoid stale data
            self.db.commit()      # Commit any pending changes
            logger.info("Refreshed database session for fraud analysis")
            
            # Extract order info - handle both direct GraphQL format and nested order_info format
            if 'order_info' in order_data:
                # Manual analysis format (nested)
                order_info = order_data.get('order_info', {})
                order_id = order_info.get('id', '') if order_info.get('id') else ''
                order_name = order_info.get('name', '')
                logger.debug("Using nested order_info format for fraud analysis")
            else:
                # Bulk analysis format (direct GraphQL)
                order_id = order_data.get('id', '') if order_data.get('id') else ''
                order_name = order_data.get('name', '')
                logger.debug("Using direct GraphQL format for fraud analysis")
            
            if not order_id or not order_name:
                logger.warning(f"Missing order ID or name in order data. ID: {order_id}, Name: {order_name}")
                logger.debug(f"Order data keys: {list(order_data.keys())}")
                return None
            
            # Check if fraud analysis already exists
            existing_analysis = self.db.query(FraudAnalysis).filter(
                FraudAnalysis.store_id == self.store.id,
                FraudAnalysis.order_name == order_name
            ).first()
            
            if existing_analysis:
                logger.info(f"Fraud analysis already exists for order {order_name}, returning existing analysis")
                return existing_analysis
            
            # Extract all fraud indicators using structured data
            is_first_time = self._check_first_time_customer(order_data)
            order_total = self._extract_order_total(order_data)
            transaction_attempts = self._count_transaction_attempts(order_data)
            customer_name = self._extract_customer_name(order_data)
            customer_total_orders = self._extract_customer_total_orders(order_data)
            duplicate_within_7days = self._check_duplicate_within_configurable_days(order_data)
            
            # Get comprehensive delivery analytics
            delivery_analytics = self._get_comprehensive_delivery_analytics(order_data)
            
            # Get previous order data if not first time customer
            prev_delivery_status = None
            prev_order_total = None
            prev_order_data = None
            prev_order_cancelled = None
            days_since_last_delivery = None
            current_order_total = order_total
            if not is_first_time:
                logger.info(f"Customer is not first-time, fetching previous order data for order {order_name}")
                prev_delivery_status, prev_order_total, prev_order_data = self._get_previous_order_data(order_data)
                logger.info(f"Previous order data: delivery_status={prev_delivery_status}, total={prev_order_total}")
                
                # Check if previous order was cancelled
                prev_order_cancelled = self._check_previous_order_cancelled(order_data)
                logger.info(f"Previous order cancelled: {prev_order_cancelled}")
                
                # Calculate days since last delivery
                # First try using the data we already have
                if prev_order_data:
                    days_since_last_delivery = self._calculate_days_since_last_delivery(order_data, prev_order_data)
                    logger.info(f"Days since last delivery: {days_since_last_delivery}")
                else:
                    days_since_last_delivery = None
                
                # Also get boolean delivery status for legacy compatibility
                prev_delivery_bool = self._get_previous_order_delivery_status(order_data)
                logger.info(f"Previous order delivery boolean: {prev_delivery_bool}")
            else:
                logger.info(f"Customer is first-time, skipping previous order data for order {order_name}")
            
            fraud_risk_level = self._extract_fraud_risk_level(order_data)
            customer_notes = self._extract_customer_notes(order_data)
            billing_outside_us = self._check_billing_address_outside_us(order_data)
            same_billing_shipping = self._check_same_billing_shipping(order_data)
            shipping_state = self._extract_shipping_state(order_data)
            additional_details = self._extract_additional_details(order_data)
            current_delivery_status = delivery_analytics['current_order_delivery_status'] or self._extract_delivery_tracking_status(order_data)
            
            # CRITICAL: Refresh session before creating fraud analysis record
            self.db.expire_all()  # Clear any cached data
            logger.info("Refreshed database session before creating fraud analysis record")
            
            # Create fraud analysis record
            fraud_analysis_data = {
                'user_id': self.user.id,
                'store_id': self.store.id,
                'shopify_order_id': order_id,
                'order_name': order_name,
                'is_first_time_customer': is_first_time,
                'order_total': order_total,
                'transaction_attempts_count': transaction_attempts,
                'customer_name': customer_name,
                'customer_total_orders': customer_total_orders,
                'duplicate_within_7days': duplicate_within_7days,
                'previous_order_delivery_status': prev_delivery_status,
                'previous_order_total': prev_order_total,
                'current_order_total': current_order_total,
                'shopify_fraud_risk_level': fraud_risk_level,
                'customer_notes': customer_notes,
                'billing_address_outside_us': billing_outside_us,
                'same_billing_shipping': same_billing_shipping,
                'shipping_state': shipping_state,
                'additional_details': additional_details,
                'current_order_delivery_status': current_delivery_status,
                'days_since_last_delivery': days_since_last_delivery,
                'previous_order_cancelled': prev_order_cancelled,
                # Store supporting data for analysis and debugging
                'raw_shopify_data': order_data,
                'duplicate_match_details': order_data.get('custom_attributes', []),
                'transaction_details': order_data.get('transactions', []),
                'risk_assessment_details': order_data.get('risk_assessments', []),
                'customer_order_history': order_data.get('customer', {}).get('orders', {}),
                'analysis_timestamp': datetime.now(timezone.utc)
            }
            
            # Try to add delivery analytics if column exists
            try:
                fraud_analysis_data['delivery_analytics'] = delivery_analytics
            except Exception as e:
                logger.warning(f"Could not add delivery_analytics (column may not exist yet): {str(e)}")
            
            fraud_analysis = FraudAnalysis(**fraud_analysis_data)
            
            debug_log(logger, f"FRAUD SERVICE DEBUG - Order {order_name}: Saving fraud analysis with risk level: {fraud_analysis.shopify_fraud_risk_level}")
            
            try:
                self.db.add(fraud_analysis)
                self.db.commit()
                self.db.refresh(fraud_analysis)
            except IntegrityError as e:
                self.db.rollback()
                # Check if it's a duplicate order (race condition between workers)
                existing_analysis = self.db.query(FraudAnalysis).filter(
                    FraudAnalysis.store_id == self.store.id,
                    FraudAnalysis.order_name == order_name
                ).first()
                if existing_analysis:
                    logger.info(f"Fraud analysis already created by another worker for order {order_name}")
                    return existing_analysis
                else:
                    # Re-raise if it's a different integrity error
                    raise
            
            debug_log(logger, f"FRAUD SERVICE DEBUG - Order {order_name}: Saved fraud analysis {fraud_analysis.id} with risk level: {fraud_analysis.shopify_fraud_risk_level}")
            
            logger.info(f"Fraud analysis completed for order {order_name}")
            return fraud_analysis
            
        except Exception as e:
            logger.error(f"Error analyzing order fraud: {str(e)}", exc_info=True)
            self.db.rollback()
            return None
    
    async def analyze_order_fraud_with_enhanced_delivery(self, order_name: str) -> Optional['FraudAnalysis']:
        """Analyze an order for fraud using enhanced delivery tracking with MCP-optimized GraphQL.
        
        Args:
            order_name: Name of the order to analyze
            
        Returns:
            FraudAnalysis instance if successful, None otherwise
        """
        try:
            logger.info(f"Starting enhanced fraud analysis for order {order_name}")
            
            # Use enhanced client to get comprehensive delivery data
            order_data = await self.enhanced_client.get_order_with_comprehensive_delivery_data(order_name)
            
            if not order_data:
                logger.warning(f"No order data found for {order_name} using enhanced client")
                return None
            
            # Use the existing analyze_order_fraud method with enhanced data
            return self.analyze_order_fraud(order_data)
            
        except Exception as e:
            logger.error(f"Error in enhanced fraud analysis for order {order_name}: {str(e)}")
            return None
    
    def _extract_mcp_delivery_status(self, order_data: Dict[str, Any]) -> Optional[str]:
        """Extract delivery status using MCP-optimized data structure.
        
        This method is specifically designed to work with the enhanced GraphQL data
        from the MCP-optimized query.
        
        Args:
            order_data: Enhanced order data from MCP-optimized GraphQL query
            
        Returns:
            Detailed delivery status string
        """
        try:
            fulfillments = order_data.get('fulfillments', [])
            if not fulfillments:
                return "Unfulfilled"
            
            logger.debug(f"Processing {len(fulfillments)} fulfillments for MCP delivery status")
            
            # Prioritized delivery status extraction
            delivery_statuses = []
            
            for fulfillment in fulfillments:
                fulfillment_id = fulfillment.get('id', 'Unknown')
                
                # Priority 1: Direct delivery timestamp
                delivered_at = fulfillment.get('deliveredAt')
                if delivered_at:
                    try:
                        delivery_datetime = datetime.fromisoformat(delivered_at.replace('Z', '+00:00'))
                        formatted_date = format_ordinal_date(delivery_datetime)
                        status_text = f"Delivered on {formatted_date}"
                        delivery_statuses.append((1, status_text))
                        logger.info(f"Found delivery date: {status_text} for fulfillment {fulfillment_id}")
                        continue
                    except Exception as e:
                        logger.warning(f"Error parsing delivery date {delivered_at}: {e}")
                
                # Priority 2: Fulfillment events with DELIVERED status
                events = fulfillment.get('events', {}).get('edges', [])
                delivered_event_found = False
                
                for event_edge in events:
                    event = event_edge['node']
                    event_status = event.get('status', '').upper()
                    happened_at = event.get('happenedAt')
                    message = event.get('message', '')
                    
                    if event_status == 'DELIVERED' and happened_at:
                        try:
                            event_datetime = datetime.fromisoformat(happened_at.replace('Z', '+00:00'))
                            formatted_date = format_ordinal_date(event_datetime)
                            status_text = f"Delivered on {formatted_date}"
                            if message:
                                status_text += f" - {message}"
                            delivery_statuses.append((1, status_text))
                            logger.info(f"Found delivery event: {status_text} for fulfillment {fulfillment_id}")
                            delivered_event_found = True
                            break
                        except Exception as e:
                            logger.warning(f"Error parsing delivery event date {happened_at}: {e}")
                
                if delivered_event_found:
                    continue
                
                # Priority 3: Display status indicating delivery
                display_status = fulfillment.get('displayStatus', '')
                if display_status and display_status.upper() in ['DELIVERED', 'FULFILLED']:
                    delivery_statuses.append((3, display_status.title()))
                    logger.debug(f"Found display status: {display_status} for fulfillment {fulfillment_id}")
                    continue
                
                # Priority 4: In transit information
                in_transit_at = fulfillment.get('inTransitAt')
                if in_transit_at:
                    try:
                        transit_datetime = datetime.fromisoformat(in_transit_at.replace('Z', '+00:00'))
                        formatted_date = format_ordinal_date(transit_datetime)
                        status_text = f"In Transit since {formatted_date}"
                        delivery_statuses.append((4, status_text))
                        logger.debug(f"Found transit date: {status_text} for fulfillment {fulfillment_id}")
                        continue
                    except Exception as e:
                        logger.warning(f"Error parsing transit date {in_transit_at}: {e}")
                
                # Priority 5: Other fulfillment events
                for event_edge in events[:5]:  # Check first 5 events
                    event = event_edge['node']
                    event_status = event.get('status', '').upper()
                    happened_at = event.get('happenedAt')
                    
                    if event_status in ['OUT_FOR_DELIVERY', 'IN_TRANSIT'] and happened_at:
                        try:
                            event_datetime = datetime.fromisoformat(happened_at.replace('Z', '+00:00'))
                            formatted_date = format_ordinal_date(event_datetime)
                            status_text = f"{event_status.replace('_', ' ').title()} on {formatted_date}"
                            delivery_statuses.append((5, status_text))
                            logger.debug(f"Found event status: {status_text} for fulfillment {fulfillment_id}")
                            break
                        except Exception as e:
                            logger.warning(f"Error parsing event date {happened_at}: {e}")
            
            # Return the highest priority status
            if delivery_statuses:
                delivery_statuses.sort(key=lambda x: x[0])  # Sort by priority
                best_status = delivery_statuses[0][1]
                logger.info(f"MCP delivery status result: {best_status}")
                return best_status
            else:
                logger.debug("No delivery status found, returning Unfulfilled")
                return "Unfulfilled"
                
        except Exception as e:
            logger.error(f"Error extracting MCP delivery status: {str(e)}")
            return "Unknown"
    
    def _get_mcp_previous_order_delivery_data(self, order_data: Dict[str, Any]) -> Tuple[Optional[str], Optional[bool]]:
        """Get previous order delivery data using MCP-optimized structure.
        
        Args:
            order_data: Enhanced order data from MCP-optimized GraphQL query
            
        Returns:
            Tuple of (delivery_status_string, was_delivered_boolean)
        """
        try:
            customer = order_data.get('customer', {})
            if not customer:
                logger.warning("No customer data in MCP order data")
                return None, None
            
            customer_orders = customer.get('orders', {}).get('edges', [])
            logger.info(f"Customer has {len(customer_orders)} orders in MCP data")
            
            if len(customer_orders) < 2:
                logger.info("Less than 2 orders available for previous order analysis")
                return None, None
            
            # Get the second order (first is current)
            previous_order = customer_orders[1]['node']
            prev_order_name = previous_order.get('name', 'Unknown')
            logger.info(f"Analyzing previous order: {prev_order_name}")
            
            # Create mock order data for previous order
            previous_order_mock = {
                'fulfillments': previous_order.get('fulfillments', [])
            }
            
            # Extract delivery status using MCP method
            delivery_status = self._extract_mcp_delivery_status(previous_order_mock)
            
            # Determine boolean delivery status
            was_delivered = False
            if delivery_status:
                status_lower = delivery_status.lower()
                was_delivered = (
                    'delivered' in status_lower or 
                    'fulfilled' in status_lower
                ) and status_lower not in ['unfulfilled', 'unknown']
            
            logger.info(f"Previous order {prev_order_name}: status='{delivery_status}', delivered={was_delivered}")
            return delivery_status, was_delivered
            
        except Exception as e:
            logger.error(f"Error getting MCP previous order delivery data: {str(e)}")
            return None, None
    
    def _check_first_time_customer(self, order_data: Dict[str, Any]) -> bool:
        """Check if this is a first-time customer.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            True if first-time customer, False otherwise
        """
        try:
            # Check customer object from structured data
            customer = order_data.get('customer', {})
            if not customer:
                return True
            
            # Check numberOfOrders count (API 2025-04 field name)
            orders_count = customer.get('numberOfOrders', 0)
            if isinstance(orders_count, str):
                orders_count = int(orders_count)
            
            # If this is their first order (count would be 1 including current)
            return orders_count <= 1
            
        except Exception as e:
            logger.error(f"Error checking first time customer: {str(e)}")
            return True  # Default to first-time for safety
    
    def _extract_order_total(self, order_data: Dict[str, Any]) -> Decimal:
        """Extract the order total amount.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            Order total as Decimal
        """
        try:
            # Handle both data formats
            if 'order_info' in order_data:
                # Manual analysis format (nested)
                order_info = order_data.get('order_info', {})
                total_price = order_info.get('total_price')
            else:
                # Bulk analysis format (direct GraphQL)
                total_price_set = order_data.get('totalPriceSet', {})
                shop_money = total_price_set.get('shopMoney', {})
                total_price = shop_money.get('amount')
            
            if total_price:
                return Decimal(str(total_price))
            
            return Decimal('0.00')
            
        except Exception as e:
            logger.error(f"Error extracting order total: {str(e)}")
            return Decimal('0.00')
    
    def _count_transaction_attempts(self, order_data: Dict[str, Any]) -> int:
        """Count the number of transaction attempts for this order.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            Number of transaction attempts
        """
        try:
            transactions = order_data.get('transactions', [])
            return len(transactions) if isinstance(transactions, list) else 0
            
        except Exception as e:
            logger.error(f"Error counting transaction attempts: {str(e)}")
            return 0
    
    def _extract_customer_name(self, order_data: Dict[str, Any]) -> Optional[str]:
        """Extract the customer name from order data.
        
        Args:
            order_data: Order data from Shopify
            
        Returns:
            Customer name if found, None otherwise
        """
        try:
            # Get customer info from structured data
            customer = order_data.get('customer', {})
            if customer:
                # Try to get display name first
                display_name = customer.get('displayName')
                if display_name:
                    return display_name
                
                # Fallback to first name + last name
                first_name = customer.get('firstName', '').strip()
                last_name = customer.get('lastName', '').strip()
                if first_name or last_name:
                    return f"{first_name} {last_name}".strip()
            
            # Fallback: check billing address for name
            billing_address = order_data.get('billing_address', {})
            if billing_address:
                first_name = billing_address.get('first_name', '').strip()
                last_name = billing_address.get('last_name', '').strip()
                if first_name or last_name:
                    return f"{first_name} {last_name}".strip()
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting customer name: {str(e)}")
            return None
    
    def _extract_customer_total_orders(self, order_data: Dict[str, Any]) -> int:
        """Extract the total number of orders the customer has placed.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            Total number of orders (including current order)
        """
        try:
            # Get customer info from structured data
            customer = order_data.get('customer', {})
            if not customer:
                logger.info("No customer data found, assuming first order")
                return 1
            
            # Get numberOfOrders count (API 2025-04 field name)
            orders_count = customer.get('numberOfOrders', 0)
            if isinstance(orders_count, str):
                orders_count = int(orders_count)
            
            logger.info(f"Customer total orders: {orders_count}")
            return orders_count if orders_count > 0 else 1
            
        except Exception as e:
            logger.error(f"Error extracting customer total orders: {str(e)}")
            return 1  # Default to 1 (at least the current order exists)
    
    def _check_duplicate_within_configurable_days(self, order_data: Dict[str, Any]) -> bool:
        """Check if customer has duplicate orders within configured days.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            True if duplicate orders found, False otherwise
        """
        try:
            customer = order_data.get('customer', {})
            if not customer:
                return False
            
            # Get user's configured duplicate detection period
            from models import Settings
            # CRITICAL: Refresh session to get latest settings
            self.db.expire_all()
            user_settings = self.db.query(Settings).filter(Settings.user_id == self.user.id).first()
            duplicate_detection_days = user_settings.duplicate_detection_days if user_settings else 7
            logger.info(f"Using duplicate_detection_days: {duplicate_detection_days} for user {self.user.id}")
            
            # Get order creation date - handle both data formats
            if 'order_info' in order_data:
                # Manual analysis format (nested)
                order_info = order_data.get('order_info', {})
                created_at_str = order_info.get('created_at', '')
                current_order_id = order_info.get('id', '')
            else:
                # Bulk analysis format (direct GraphQL)
                created_at_str = order_data.get('createdAt', '')
                current_order_id = order_data.get('id', '')
                
            if not created_at_str:
                return False
            
            created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            detection_period_ago = created_at - timedelta(days=duplicate_detection_days)
            
            # Check customer's order history for orders within configured days
            customer_orders = customer.get('orders', {}).get('edges', [])
            duplicate_count = 0
            
            for order_edge in customer_orders:
                order = order_edge['node']
                order_created_str = order.get('createdAt', '')
                
                if order_created_str and order.get('id') != current_order_id:
                    order_created = datetime.fromisoformat(order_created_str.replace('Z', '+00:00'))
                    if detection_period_ago <= order_created <= created_at:
                        duplicate_count += 1
            
            return duplicate_count > 0
            
        except Exception as e:
            logger.error(f"Error checking duplicate orders: {str(e)}")
            return False
    
    def _get_previous_order_delivery_status(self, order_data: Dict[str, Any]) -> Optional[bool]:
        """Get delivery status of customer's previous order.
        
        Args:
            order_data: Order data from Shopify
            
        Returns:
            True if delivered, False if not delivered, None if no previous order
        """
        try:
            customer = order_data.get('customer', {})
            if not customer:
                return None
            
            # Get customer's order history from structured data
            customer_orders = customer.get('orders', {}).get('edges', [])
            
            if not customer_orders or len(customer_orders) < 2:
                # Need at least 2 orders (current + previous)
                return None
            
            # Get the second order (first is current order)
            previous_order = customer_orders[1]['node']
            
            # Check fulfillments for delivery status
            fulfillments = previous_order.get('fulfillments', [])
            if not fulfillments:
                return False  # No fulfillments means not delivered
            
            # Check if any fulfillment has delivery confirmation
            for fulfillment in fulfillments:
                # Direct delivery date check
                if fulfillment.get('deliveredAt'):
                    return True
                
                # Check fulfillment events for DELIVERED status
                events = fulfillment.get('events', {}).get('edges', [])
                for event_edge in events:
                    event = event_edge['node']
                    if event.get('status', '').upper() == 'DELIVERED':
                        return True
                
                # Check display status
                display_status = fulfillment.get('displayStatus', '')
                if display_status.upper() == 'DELIVERED':
                    return True
            
            # If we have fulfillments but no delivery confirmation, assume not delivered
            return False
            
        except Exception as e:
            logger.error(f"Error getting previous order delivery status: {str(e)}")
            return None
    
    def _check_previous_order_cancelled(self, order_data: Dict[str, Any]) -> Optional[bool]:
        """Check if customer's previous order was cancelled.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            True if previous order was cancelled, False if not cancelled, None if no previous order
        """
        try:
            # Get previous order data using existing method
            _, _, previous_order = self._get_previous_order_data(order_data)
            
            if not previous_order:
                logger.info("No previous order found for cancellation check")
                return None
            
            # Check if cancelledAt field exists and is not null
            cancelled_at = previous_order.get('cancelledAt')
            was_cancelled = cancelled_at is not None
            
            prev_order_name = previous_order.get('name', 'Unknown')
            logger.info(f"Previous order {prev_order_name} cancellation status: {was_cancelled} (cancelledAt: {cancelled_at})")
            
            return was_cancelled
            
        except Exception as e:
            logger.error(f"Error checking previous order cancellation: {str(e)}")
            return None
    
    def _get_previous_order_data(self, order_data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Decimal], Optional[Dict[str, Any]]]:
        """Get delivery tracking status, total, and full data of customer's previous order.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            Tuple of (delivery_tracking_status, order_total, previous_order_data) for previous order
        """
        try:
            customer = order_data.get('customer', {})
            if not customer:
                logger.warning("No customer data found in order data")
                return None, None, None
            
            # Get current order info - handle both data formats
            if 'order_info' in order_data:
                # Manual analysis format (nested)
                order_info = order_data.get('order_info', {})
                current_order_name = order_info.get('name', '')
                current_order_created = order_info.get('created_at', '')
            else:
                # Bulk analysis format (direct GraphQL)
                current_order_name = order_data.get('name', '')
                current_order_created = order_data.get('createdAt', '')
                
            if not current_order_created:
                logger.warning("No current order creation date found")
                return None, None, None
            
            # Parse current order creation date
            try:
                current_dt = datetime.fromisoformat(current_order_created.replace('Z', '+00:00'))
            except Exception as e:
                logger.warning(f"Could not parse current order date: {e}")
                return None, None, None
            
            # Get customer's order history from structured data
            customer_orders = customer.get('orders', {}).get('edges', [])
            logger.info(f"Customer has {len(customer_orders)} orders in history")
            
            # Debug: log order names and basic info
            for i, order_edge in enumerate(customer_orders[:3]):
                order = order_edge['node']
                order_name = order.get('name', 'Unknown')
                order_created = order.get('createdAt', 'Unknown')
                fulfillment_count = len(order.get('fulfillments', []))
                logger.debug(f"  Order {i+1}: {order_name} created {order_created} (fulfillments: {fulfillment_count})")
            
            # Find the actual previous order (chronologically before current order)
            previous_orders = []
            for order_edge in customer_orders:
                order = order_edge['node']
                order_name = order.get('name', '')
                order_created = order.get('createdAt', '')
                
                # Skip the current order
                if order_name == current_order_name:
                    logger.debug(f"Skipping current order: {order_name}")
                    continue
                
                # Only consider orders created before the current order
                try:
                    order_dt = datetime.fromisoformat(order_created.replace('Z', '+00:00'))
                    if order_dt < current_dt:
                        previous_orders.append((order_dt, order))
                        logger.debug(f"Found previous order: {order_name} created {order_created}")
                except Exception as e:
                    logger.warning(f"Could not parse order date for {order_name}: {e}")
            
            if not previous_orders:
                logger.info("No chronologically previous orders found")
                return None, None, None
            
            # Sort by creation date (newest first among previous orders)
            previous_orders.sort(key=lambda x: x[0], reverse=True)
            previous_order = previous_orders[0][1]
            prev_order_name = previous_order.get('name', 'Unknown')
            logger.info(f"Analyzing actual previous order: {prev_order_name}")
            
            # Extract order total
            total_amount = previous_order.get('totalPriceSet', {}).get('shopMoney', {}).get('amount')
            order_total = Decimal(str(total_amount)) if total_amount else None
            
            # Extract delivery status from the previous order's fulfillment data
            # This data is now included in the main GraphQL query
            fulfillments = previous_order.get('fulfillments', [])
            logger.info(f"Previous order {prev_order_name} has {len(fulfillments)} fulfillments")
            
            # Debug: log fulfillment details
            for i, fulfillment in enumerate(fulfillments):
                fulfillment_id = fulfillment.get('id', 'Unknown')
                delivered_at = fulfillment.get('deliveredAt')
                display_status = fulfillment.get('displayStatus')
                logger.debug(f"  Fulfillment {i+1} ({fulfillment_id}): deliveredAt={delivered_at}, displayStatus={display_status}")
            
            if fulfillments:
                # Create a mock order data structure for the previous order to use our existing extraction logic
                previous_order_mock = {
                    'fulfillments': fulfillments
                }
                delivery_status = self._extract_delivery_tracking_status(previous_order_mock)
                logger.info(f"Extracted previous order delivery status: {delivery_status}")
                
                # Return delivery status if we have meaningful information
                # Accept both detailed statuses ("Delivered on August 5th, 2024") and basic statuses ("Delivered")
                # Only reject empty, "Unknown", "Unfulfilled", or None values
                if delivery_status and delivery_status.lower() not in ['unknown', 'unfulfilled', 'none', '']:
                    logger.info(f"Returning previous order delivery status: '{delivery_status}'")
                    return delivery_status, order_total, previous_order
                else:
                    logger.info(f"Skipping invalid delivery status '{delivery_status}' - no meaningful data")
            
            # No delivery information available - return None for delivery status but still return order data
            logger.info(f"No delivery tracking available for previous order {previous_order.get('name')}")
            return None, order_total, previous_order
            
        except Exception as e:
            logger.error(f"Error getting previous order data: {str(e)}")
            return None, None, None
    
    def _extract_fraud_risk_level(self, order_data: Dict[str, Any]) -> Optional[str]:
        """Extract Shopify's fraud risk level assessment from the risk field.
        
        Args:
            order_data: Order data from Shopify
            
        Returns:
            Risk level (LOW, MEDIUM, HIGH) as determined by Shopify, or None
        """
        try:
            order_name = order_data.get('name', 'unknown')
            debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Starting risk level extraction")
            debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Order data keys: {list(order_data.keys())[:10]}...")

            # Check Shopify's risk field (OrderRiskSummary structure)
            risk_data = order_data.get('risk')
            debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Risk data type: {type(risk_data)}, value: {risk_data}")

            if risk_data and isinstance(risk_data, dict):
                # Extract assessments from the OrderRiskSummary
                assessments = risk_data.get('assessments', [])
                debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Found {len(assessments)} assessments")

                if assessments and len(assessments) > 0:
                    # Get the first assessment (typically the main fraud assessment)
                    assessment = assessments[0]
                    debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Assessment data: {assessment}")
                    risk_level = assessment.get('riskLevel')
                    debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Raw risk level: {risk_level}")

                    if risk_level:
                        # Convert to uppercase for consistency
                        risk_level = risk_level.upper()

                        # Validate it's one of the expected values
                        if risk_level in ['LOW', 'MEDIUM', 'HIGH']:
                            debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Valid Shopify fraud risk assessment: {risk_level}")
                            facts = assessment.get('facts', [])
                            debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Risk facts count: {len(facts)}")
                            return risk_level
                        else:
                            logger.warning(f"FRAUD RISK DEBUG - Order {order_name}: Unexpected Shopify risk level value: {risk_level}")
                            return risk_level  # Return it anyway in case Shopify added new values
                    else:
                        debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Risk level is null in assessment")
                else:
                    debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: No risk assessments found in order")
            else:
                debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: No risk data found in order (risk field is None or empty)")

            debug_log(logger, f"FRAUD RISK DEBUG - Order {order_name}: Returning None - no Shopify fraud risk level found")
            return None

        except Exception as e:
            logger.error(f"FRAUD RISK DEBUG - Order {order_name}: Error extracting fraud risk level: {str(e)}")
            return None
    
    def _extract_customer_notes(self, order_data: Dict[str, Any]) -> Optional[str]:
        """Extract customer notes from the order.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            Customer notes if present, None otherwise
        """
        try:
            notes_parts = []
            
            # Check note field - handle both data formats
            if 'order_info' in order_data:
                # Manual analysis format (nested)
                order_info = order_data.get('order_info', {})
                note = order_info.get('note', '')
            else:
                # Bulk analysis format (direct GraphQL)
                note = order_data.get('note', '')
                
            if note and note.strip():
                notes_parts.append(f"Order Note: {note.strip()}")
            
            # Check customAttributes (Additional Details) for customer-provided notes
            # Handle both snake_case (manual analysis) and camelCase (bulk processing) formats
            custom_attributes = order_data.get('custom_attributes', [])
            if not custom_attributes:
                custom_attributes = order_data.get('customAttributes', [])
                
            if isinstance(custom_attributes, list):
                for attr in custom_attributes:
                    key = attr.get('key', '').lower()
                    value = attr.get('value', '')
                    
                    # Look for note-related attributes and customer information
                    note_keywords = [
                        'note', 'comment', 'message', 'instruction', 'request', 
                        'special', 'additional', 'customer', 'delivery', 'gift'
                    ]
                    
                    if any(word in key for word in note_keywords):
                        if value and value.strip():
                            notes_parts.append(f"{attr.get('key', 'Note')}: {value.strip()}")
                    elif value and len(value.strip()) > 10:  # Capture any substantial text values
                        notes_parts.append(f"{attr.get('key', 'Additional Info')}: {value.strip()}")
            
            # Return combined notes if any found
            if notes_parts:
                return '\n'.join(notes_parts)
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting customer notes: {str(e)}")
            return None
    
    def _check_same_billing_shipping(self, order_data: Dict[str, Any]) -> bool:
        """Check if billing and shipping addresses are the same.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            True if addresses match, False otherwise
        """
        try:
            # Handle both naming conventions (snake_case from manual, camelCase from bulk)
            # Check for snake_case first (manual analysis format)
            billing_address = order_data.get('billing_address')
            shipping_address = order_data.get('shipping_address')
            
            # If not found, check for camelCase (bulk processing format)
            if billing_address is None:
                billing_address = order_data.get('billingAddress')
            if shipping_address is None:
                shipping_address = order_data.get('shippingAddress')
            
            logger.info(f"Billing address data: {billing_address}")
            logger.info(f"Shipping address data: {shipping_address}")
            
            if not billing_address or not shipping_address:
                logger.warning("Missing billing or shipping address data")
                return None
            
            # Fields to compare (ignoring name fields as they might differ)
            address_fields = ['address1', 'address2', 'city', 'province', 'country', 'zip']
            
            for field in address_fields:
                # Normalize values for comparison
                billing_val = str(billing_address.get(field) or '').strip().upper()
                shipping_val = str(shipping_address.get(field) or '').strip().upper()
                
                logger.debug(f"Comparing {field}: billing='{billing_val}' vs shipping='{shipping_val}'")
                
                # Skip empty address2 fields
                if field == 'address2' and not billing_val and not shipping_val:
                    logger.debug(f"Skipping empty address2 fields")
                    continue
                
                if billing_val != shipping_val:
                    logger.info(f"Address mismatch on field {field}: '{billing_val}' != '{shipping_val}'")
                    return False
            
            logger.info("Billing and shipping addresses match")
            return True
            
        except Exception as e:
            logger.error(f"Error checking billing/shipping address match: {str(e)}")
            return False  # Return False on error for safety
    
    def _check_billing_address_outside_us(self, order_data: Dict[str, Any]) -> bool:
        """Check if billing address is outside the United States.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            True if billing address is outside US, False otherwise
        """
        try:
            # Handle both naming conventions (snake_case from manual, camelCase from bulk)
            billing_address = order_data.get('billing_address')
            if billing_address is None:
                billing_address = order_data.get('billingAddress')
            if billing_address:
                country = billing_address.get('country', '').upper()
                
                # Check if US
                us_indicators = ['US', 'USA', 'UNITED STATES', 'UNITED STATES OF AMERICA']
                if country in us_indicators:
                    return False
                elif country:
                    # Has a country but it's not US
                    return True
            
            # If no billing address, assume False
            return False
            
        except Exception as e:
            logger.error(f"Error checking billing address: {str(e)}")
            return False
    
    def _extract_shipping_state(self, order_data: Dict[str, Any]) -> Optional[str]:
        """Extract the shipping state/province from the order.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            Shipping state/province in UPPERCASE, or None if not found
        """
        try:
            # Handle both snake_case (manual analysis) and camelCase (bulk processing) formats
            shipping_address = order_data.get('shipping_address')
            if shipping_address is None:
                shipping_address = order_data.get('shippingAddress')
                
            if shipping_address:
                # Get the province (state) field - Shopify uses 'province' for US states
                state = shipping_address.get('province', '').strip()
                
                if state:
                    # Convert to uppercase as requested by user
                    state_upper = state.upper()
                    logger.info(f"Extracted shipping state: '{state}' -> '{state_upper}'")
                    return state_upper
                else:
                    logger.debug("No state/province found in shipping address")
                    return None
            else:
                logger.debug("No shipping address found")
                return None
            
        except Exception as e:
            logger.error(f"Error extracting shipping state: {str(e)}")
            return None
    
    def _extract_additional_details(self, order_data: Dict[str, Any]) -> Optional[str]:
        """Extract additional details from customAttributes.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            Formatted additional details if present, None otherwise
        """
        try:
            # Handle both snake_case (manual analysis) and camelCase (bulk processing) formats
            custom_attributes = order_data.get('custom_attributes', [])
            if not custom_attributes:
                custom_attributes = order_data.get('customAttributes', [])
            
            if not isinstance(custom_attributes, list) or not custom_attributes:
                return None
            
            # Format all custom attributes as key-value pairs
            details_parts = []
            for attr in custom_attributes:
                key = attr.get('key', '').strip()
                value = attr.get('value', '').strip()
                
                if key and value:
                    details_parts.append(f"{key} {value}")
                elif value:  # Value without key
                    details_parts.append(value)
            
            if details_parts:
                result = '\n'.join(details_parts)
                return result
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting additional details: {str(e)}")
            return None
    
    async def _calculate_days_since_last_delivery_enhanced(self, order_data: Dict[str, Any]) -> Optional[int]:
        """Calculate days since last delivery using enhanced delivery data retrieval.
        
        This method uses the same approach as manual fraud analysis to get accurate delivery data.
        
        Args:
            order_data: Current order data from Shopify
            
        Returns:
            Number of days since last delivery, or None if no delivery found
        """
        try:
            # Get current order creation date
            if 'order_info' in order_data:
                current_order_created = order_data.get('order_info', {}).get('created_at', '')
                order_name = order_data.get('order_info', {}).get('name', '')
            else:
                current_order_created = order_data.get('createdAt', '')
                order_name = order_data.get('name', '')
            
            if not current_order_created:
                logger.warning("No creation date found for current order")
                return None
            
            # Parse current order creation date
            try:
                current_dt = datetime.fromisoformat(current_order_created.replace('Z', '+00:00'))
            except Exception as e:
                logger.warning(f"Could not parse current order date: {e}")
                return None
            
            # Use enhanced client to get comprehensive delivery data (like manual analysis does)
            logger.info(f"Fetching enhanced delivery data for order {order_name}")
            enhanced_order_data = await self.enhanced_client.get_order_with_comprehensive_delivery_data(order_name)
            
            if not enhanced_order_data:
                logger.warning(f"Could not fetch enhanced order data for {order_name}")
                return None
            
            # Now we have the full delivery data - extract previous delivery date
            customer = enhanced_order_data.get('customer', {})
            if not customer:
                logger.warning("No customer data in enhanced order data")
                return None
            
            customer_orders = customer.get('orders', {}).get('edges', [])
            logger.info(f"Customer has {len(customer_orders)} orders with enhanced data")
            
            # Find the most recent delivered order (skip current order)
            for order_edge in customer_orders[1:]:  # Skip first order (current)
                order = order_edge.get('node', {})
                fulfillments = order.get('fulfillments', [])
                
                for fulfillment in fulfillments:
                    # Check for delivery date
                    delivered_at = fulfillment.get('deliveredAt')
                    if delivered_at:
                        try:
                            delivery_dt = datetime.fromisoformat(delivered_at.replace('Z', '+00:00'))
                            days_diff = (current_dt - delivery_dt).days
                            
                            if days_diff >= 0:
                                logger.info(f"Found previous delivery {days_diff} days ago in order {order.get('name')}")
                                return days_diff
                        except Exception as e:
                            logger.warning(f"Error parsing delivery date: {e}")
                            continue
                    
                    # Also check events for delivery
                    events = fulfillment.get('events', {}).get('edges', [])
                    for event_edge in events:
                        event = event_edge.get('node', {})
                        if event.get('status', '').upper() == 'DELIVERED' and event.get('happenedAt'):
                            try:
                                delivery_dt = datetime.fromisoformat(event.get('happenedAt').replace('Z', '+00:00'))
                                days_diff = (current_dt - delivery_dt).days
                                
                                if days_diff >= 0:
                                    logger.info(f"Found previous delivery {days_diff} days ago from event")
                                    return days_diff
                            except Exception as e:
                                logger.warning(f"Error parsing event delivery date: {e}")
            
            logger.info("No previous delivery found in customer history")
            return None
            
        except Exception as e:
            logger.error(f"Error calculating days since last delivery with enhanced method: {str(e)}")
            return None
    
    def _calculate_days_since_last_delivery(self, order_data: Dict[str, Any], previous_order_data: Dict[str, Any] = None) -> Optional[int]:
        """Calculate the number of days between current order creation and previous order delivery.
        
        Args:
            order_data: Current order data from Shopify
            previous_order_data: Previous order data with fulfillment information
            
        Returns:
            Number of days since last delivery, or None if no previous delivery exists
        """
        try:
            # Get current order creation date - handle both data formats
            if 'order_info' in order_data:
                # Manual analysis format (nested)
                order_info = order_data.get('order_info', {})
                current_order_created = order_info.get('created_at', '')
            else:
                # Bulk analysis format (direct GraphQL)
                current_order_created = order_data.get('createdAt', '')
            
            if not current_order_created:
                logger.warning("No creation date found for current order")
                return None
            
            # Parse current order creation date
            try:
                current_dt = datetime.fromisoformat(current_order_created.replace('Z', '+00:00'))
            except Exception as e:
                logger.warning(f"Could not parse current order date: {e}")
                return None
            
            # Get previous order delivery date
            previous_delivery_date = None
            if previous_order_data:
                # Extract delivery date from previous order fulfillments
                fulfillments = previous_order_data.get('fulfillments', [])
                
                for fulfillment in fulfillments:
                    # Check for direct delivery date
                    delivered_at = fulfillment.get('deliveredAt')
                    if delivered_at:
                        previous_delivery_date = delivered_at
                        logger.debug(f"Found previous order delivery date: {delivered_at}")
                        break
                    
                    # Check fulfillment events for delivery
                    events = fulfillment.get('events', {}).get('edges', [])
                    for event_edge in events:
                        event = event_edge['node']
                        if event.get('status', '').upper() == 'DELIVERED' and event.get('happenedAt'):
                            previous_delivery_date = event.get('happenedAt')
                            logger.debug(f"Found previous order delivery date from event: {previous_delivery_date}")
                            break
                    
                    if previous_delivery_date:
                        break
            
            # Calculate days difference
            if previous_delivery_date:
                try:
                    delivery_dt = datetime.fromisoformat(previous_delivery_date.replace('Z', '+00:00'))
                    days_diff = (current_dt - delivery_dt).days
                    
                    # Only return positive values (delivery before current order)
                    if days_diff >= 0:
                        logger.info(f"Days since last delivery: {days_diff}")
                        return days_diff
                    else:
                        logger.warning(f"Previous delivery date is after current order (days_diff: {days_diff})")
                        return None
                except Exception as e:
                    logger.warning(f"Could not parse previous delivery date: {e}")
                    return None
            else:
                logger.info("No previous delivery date found")
                return None
                
        except Exception as e:
            logger.error(f"Error calculating days since last delivery: {str(e)}")
            return None
    
    def _extract_delivery_tracking_status(self, order_data: Dict[str, Any]) -> Optional[str]:
        """Extract detailed delivery tracking status from fulfillments with specific dates and messages.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            Detailed delivery tracking status with dates (e.g., "Delivered on Monday, August 5, 2024")
        """
        try:
            fulfillments = order_data.get('fulfillments', [])
            logger.debug(f"Extracting delivery status from {len(fulfillments)} fulfillments")
            
            if not isinstance(fulfillments, list) or not fulfillments:
                logger.debug("No fulfillments found, returning Unfulfilled")
                return "Unfulfilled"
            
            # Collect all delivery tracking information with priority scoring
            delivery_details = []
            
            for fulfillment in fulfillments:
                fulfillment_details = []
                
                # Priority 1: Direct delivery date (highest priority)
                delivered_at = fulfillment.get('deliveredAt')
                logger.debug(f"Fulfillment {fulfillment.get('id', 'Unknown')} - deliveredAt: {delivered_at}")
                
                if delivered_at:
                    try:
                        delivery_datetime = datetime.fromisoformat(delivered_at.replace('Z', '+00:00'))
                        formatted_date = format_ordinal_date(delivery_datetime)
                        status_text = f"Delivered on {formatted_date}"
                        logger.debug(f"Formatted delivery status: {status_text}")
                        fulfillment_details.append((1, status_text))
                    except Exception as e:
                        logger.warning(f"Error formatting delivery date {delivered_at}: {str(e)}")
                        fulfillment_details.append((1, "Delivered"))
                
                # Priority 2: Fulfillment events (detailed tracking)
                events = fulfillment.get('events', {}).get('edges', [])
                if events:
                    for event_edge in events:
                        event = event_edge['node']
                        event_status = event.get('status', '').upper()
                        happened_at = event.get('happenedAt')
                        message = event.get('message', '')
                        
                        if happened_at:
                            try:
                                event_datetime = datetime.fromisoformat(happened_at.replace('Z', '+00:00'))
                                formatted_date = format_ordinal_date(event_datetime)
                                
                                # Assign priority based on event status
                                if event_status == 'DELIVERED':
                                    priority = 1
                                    status_text = f"Delivered on {formatted_date}"
                                    if message:
                                        status_text += f" - {message}"
                                elif event_status == 'OUT_FOR_DELIVERY':
                                    priority = 2
                                    status_text = f"Out for Delivery on {formatted_date}"
                                    if message:
                                        status_text += f" - {message}"
                                elif event_status == 'IN_TRANSIT':
                                    priority = 3
                                    status_text = f"In Transit since {formatted_date}"
                                    if message:
                                        status_text += f" - {message}"
                                elif event_status == 'ATTEMPTED_DELIVERY':
                                    priority = 4
                                    status_text = f"Delivery Attempted on {formatted_date}"
                                    if message:
                                        status_text += f" - {message}"
                                else:
                                    priority = 5
                                    status_text = f"{event_status.replace('_', ' ').title()} on {formatted_date}"
                                    if message:
                                        status_text += f" - {message}"
                                
                                fulfillment_details.append((priority, status_text))
                                
                                # If we found a delivery event, stop processing other events for this fulfillment
                                if event_status == 'DELIVERED':
                                    break
                                    
                            except Exception as e:
                                logger.warning(f"Error formatting event date {happened_at}: {str(e)}")
                                if message:
                                    fulfillment_details.append((6, f"Status: {event_status} - {message}"))
                                else:
                                    fulfillment_details.append((6, f"Status: {event_status}"))
                
                # Priority 3: In transit date
                if not any(detail[0] <= 3 for detail in fulfillment_details):  # Only if no higher priority info
                    in_transit_at = fulfillment.get('inTransitAt')
                    if in_transit_at:
                        try:
                            transit_datetime = datetime.fromisoformat(in_transit_at.replace('Z', '+00:00'))
                            formatted_date = format_ordinal_date(transit_datetime)
                            fulfillment_details.append((3, f"In Transit since {formatted_date}"))
                        except Exception as e:
                            logger.warning(f"Error formatting transit date {in_transit_at}: {str(e)}")
                            fulfillment_details.append((3, "In Transit"))
                
                # Priority 4: Display status
                if not any(detail[0] <= 4 for detail in fulfillment_details):  # Only if no higher priority info
                    display_status = fulfillment.get('displayStatus', '')
                    if display_status:
                        priority = 2 if display_status.upper() == 'DELIVERED' else 4
                        fulfillment_details.append((priority, display_status.replace('_', ' ').title()))
                
                # Priority 5: Tracking information
                if not any(detail[0] <= 4 for detail in fulfillment_details):  # Only if no higher priority info
                    tracking_info = fulfillment.get('trackingInfo', [])
                    if tracking_info and len(tracking_info) > 0:
                        tracking = tracking_info[0]
                        company = tracking.get('company', '')
                        number = tracking.get('number', '')
                        if company and number:
                            fulfillment_details.append((5, f"Tracking Available - {company}: {number}"))
                        else:
                            fulfillment_details.append((5, "Tracking Available"))
                
                # Priority 6: Basic fulfillment status
                if not fulfillment_details:  # Only if no other info available
                    status = fulfillment.get('status', '')
                    if status:
                        fulfillment_details.append((6, status.replace('_', ' ').title()))
                
                # Add all details from this fulfillment
                delivery_details.extend(fulfillment_details)
            
            # Sort by priority (lower number = higher priority) and return the best status
            if delivery_details:
                delivery_details.sort(key=lambda x: x[0])
                best_status = delivery_details[0][1]
                logger.debug(f"Returning best delivery status: {best_status} (from {len(delivery_details)} options)")
                return best_status
            else:
                logger.debug("No delivery details found, returning Unfulfilled")
                return "Unfulfilled"
            
        except Exception as e:
            logger.error(f"Error extracting delivery tracking status: {str(e)}")
            return "Unknown"
    
    def _get_comprehensive_delivery_analytics(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Get comprehensive delivery analytics for fraud detection.
        
        Args:
            order_data: Structured order data from Shopify
            
        Returns:
            Dictionary with detailed delivery analytics
        """
        try:
            analytics = {
                'current_order_delivery_status': None,
                'previous_order_delivery_status': None,
                'customer_delivery_history': {
                    'total_orders': 0,
                    'delivered_orders': 0,
                    'failed_deliveries': 0,
                    'average_delivery_days': None,
                    'delivery_success_rate': 0.0
                },
                'delivery_patterns': {
                    'has_tracking_info': False,
                    'multiple_delivery_attempts': False,
                    'unusual_delivery_locations': False
                }
            }
            
            # Current order delivery status
            analytics['current_order_delivery_status'] = self._extract_delivery_tracking_status(order_data)
            
            # Customer order history analysis
            customer = order_data.get('customer', {})
            if customer:
                customer_orders = customer.get('orders', {}).get('edges', [])
                analytics['customer_delivery_history']['total_orders'] = len(customer_orders)
                
                delivered_count = 0
                failed_count = 0
                delivery_times = []
                tracking_info_found = False
                multiple_attempts = False
                
                for order_edge in customer_orders[1:]:  # Skip current order
                    order = order_edge['node']
                    fulfillments = order.get('fulfillments', [])
                    
                    order_delivered = False
                    order_failed = False
                    
                    for fulfillment in fulfillments:
                        # Check if order has tracking info
                        tracking_info = fulfillment.get('trackingInfo', [])
                        if tracking_info:
                            tracking_info_found = True
                        
                        # Check delivery status
                        if fulfillment.get('deliveredAt'):
                            order_delivered = True
                            
                            # Calculate delivery time
                            try:
                                created_at = datetime.fromisoformat(order.get('createdAt', '').replace('Z', '+00:00'))
                                delivered_at = datetime.fromisoformat(fulfillment.get('deliveredAt').replace('Z', '+00:00'))
                                delivery_days = (delivered_at - created_at).days
                                if delivery_days >= 0:  # Sanity check
                                    delivery_times.append(delivery_days)
                            except Exception:
                                pass
                        
                        # Check for failed delivery attempts
                        events = fulfillment.get('events', {}).get('edges', [])
                        attempted_delivery_count = 0
                        
                        for event_edge in events:
                            event = event_edge['node']
                            event_status = event.get('status', '').upper()
                            
                            if event_status in ['ATTEMPTED_DELIVERY', 'FAILURE', 'NOT_DELIVERED']:
                                attempted_delivery_count += 1
                            
                            if event_status == 'DELIVERED':
                                order_delivered = True
                            elif event_status in ['FAILURE', 'NOT_DELIVERED']:
                                order_failed = True
                        
                        if attempted_delivery_count > 1:
                            multiple_attempts = True
                    
                    if order_delivered:
                        delivered_count += 1
                    elif order_failed:
                        failed_count += 1
                
                analytics['customer_delivery_history']['delivered_orders'] = delivered_count
                analytics['customer_delivery_history']['failed_deliveries'] = failed_count
                analytics['delivery_patterns']['has_tracking_info'] = tracking_info_found
                analytics['delivery_patterns']['multiple_delivery_attempts'] = multiple_attempts
                
                # Calculate success rate
                total_concluded = delivered_count + failed_count
                if total_concluded > 0:
                    analytics['customer_delivery_history']['delivery_success_rate'] = delivered_count / total_concluded
                
                # Calculate average delivery time
                if delivery_times:
                    analytics['customer_delivery_history']['average_delivery_days'] = sum(delivery_times) / len(delivery_times)
                
                # Get previous order delivery status specifically
                if len(customer_orders) >= 2:
                    previous_order = customer_orders[1]['node']
                    previous_order_mock = {
                        'fulfillments': previous_order.get('fulfillments', [])
                    }
                    analytics['previous_order_delivery_status'] = self._extract_delivery_tracking_status(previous_order_mock)
            
            return analytics
            
        except Exception as e:
            logger.error(f"Error getting comprehensive delivery analytics: {str(e)}")
            return {
                'current_order_delivery_status': 'Unknown',
                'previous_order_delivery_status': 'Unknown',
                'customer_delivery_history': {
                    'total_orders': 0,
                    'delivered_orders': 0,
                    'failed_deliveries': 0,
                    'average_delivery_days': None,
                    'delivery_success_rate': 0.0
                },
                'delivery_patterns': {
                    'has_tracking_info': False,
                    'multiple_delivery_attempts': False,
                    'unusual_delivery_locations': False
                }
            }