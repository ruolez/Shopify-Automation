"""
Fraud Archive Service for managing the archival of fulfilled and cancelled fraud analyses.

This service handles:
- Checking order fulfillment/cancellation status
- Moving fraud analyses to archive table
- Cleaning up old archived records based on retention settings
"""
import asyncio
import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, or_
from sqlalchemy.exc import SQLAlchemyError

from models import FraudAnalysis, ShopifyStore, User, Settings, ProcessedFraudOrder
from shopify_client import ShopifyClient
from database import get_db

logger = logging.getLogger(__name__)


class FraudArchiveService:
    """Service for archiving fraud analyses of fulfilled and cancelled orders."""
    
    def __init__(self, db: Session):
        """Initialize the fraud archive service.
        
        Args:
            db: Database session
        """
        self.db = db
    
    async def archive_fulfilled_and_cancelled_analyses(self, user_id: int, max_analyses: int = None) -> Dict[str, Any]:
        """Archive fraud analyses for orders that are fulfilled or cancelled.
        
        Args:
            user_id: User ID to process analyses for
            max_analyses: Maximum number of analyses to process in one run (uses user setting if not provided)
            
        Returns:
            Dictionary with archival statistics
        """
        try:
            # Get user's batch size setting if not provided
            if max_analyses is None:
                settings = self.db.query(Settings).filter(Settings.user_id == user_id).first()
                max_analyses = settings.reconciliation_batch_size if settings else 500
            
            # Get active fraud analyses for the user with a limit
            query = self.db.query(FraudAnalysis).filter(
                FraudAnalysis.user_id == user_id
            )
            
            # Add limit to prevent processing too many at once
            total_count = query.count()
            active_analyses = query.limit(max_analyses).all()
            
            if not active_analyses:
                logger.info(f"No active fraud analyses found for user {user_id}")
                return {
                    "checked": 0,
                    "archived": 0,
                    "failed": 0,
                    "reasons": {"order_fulfilled": 0, "order_cancelled": 0},
                    "total_remaining": 0
                }
            
            logger.info(f"Processing {len(active_analyses)} out of {total_count} active fraud analyses for user {user_id}")
            
            # Group analyses by store for efficient API calls
            analyses_by_store: Dict[int, List[FraudAnalysis]] = {}
            for analysis in active_analyses:
                if analysis.store_id not in analyses_by_store:
                    analyses_by_store[analysis.store_id] = []
                analyses_by_store[analysis.store_id].append(analysis)
            
            # Process each store's analyses
            archived_count = 0
            failed_count = 0
            reasons = {"order_fulfilled": 0, "order_cancelled": 0}
            archived_orders = []  # Track archived orders with their names
            
            # Process in smaller batches to avoid locking the database too long
            BATCH_SIZE = 50
            
            for store_id, store_analyses in analyses_by_store.items():
                # Get store details
                store = self.db.query(ShopifyStore).filter(
                    ShopifyStore.id == store_id
                ).first()
                
                if not store:
                    logger.warning(f"Store {store_id} not found, skipping analyses")
                    failed_count += len(store_analyses)
                    continue
                
                # Initialize Shopify client
                client = ShopifyClient(store.shop_domain, store.access_token)
                
                # Process in batches
                for i in range(0, len(store_analyses), BATCH_SIZE):
                    batch = store_analyses[i:i + BATCH_SIZE]
                    batch_archived = 0
                    
                    # Check each order's status in the batch
                    for analysis in batch:
                        # Store analysis info before processing (in case it gets deleted)
                        analysis_id = analysis.id
                        analysis_order_name = analysis.order_name
                        
                        try:
                            # Get current order status from Shopify
                            order_status = await self._get_order_status(
                                client, 
                                analysis.order_name
                            )
                            
                            if not order_status:
                                logger.warning(f"Could not get status for order {analysis_order_name}")
                                failed_count += 1
                                continue
                            
                            # Check if order should be archived
                            archive_reason = None
                            
                            # Check fulfillment status
                            fulfillment_status = order_status.get("displayFulfillmentStatus")
                            if fulfillment_status:
                                fulfillment_status = fulfillment_status.upper()
                                if fulfillment_status == "FULFILLED":
                                    archive_reason = "order_fulfilled"
                                elif fulfillment_status in ["CANCELLED", "CANCELED"]:
                                    archive_reason = "order_cancelled"
                            
                            # Also check financial status for cancellation
                            if not archive_reason:
                                financial_status = order_status.get("displayFinancialStatus")
                                if financial_status and financial_status.upper() in ["VOIDED", "REFUNDED"]:
                                    archive_reason = "order_cancelled"
                            
                            # Check if order has cancelledAt timestamp
                            if not archive_reason and order_status.get("cancelledAt"):
                                archive_reason = "order_cancelled"
                            
                            # Log why order is or isn't being archived
                            if not archive_reason:
                                logger.debug(f"Order {analysis_order_name} not archived - Status: {fulfillment_status}, Financial: {financial_status}")
                            
                            if archive_reason:
                                # Archive this analysis
                                success = self._archive_analysis(analysis, archive_reason)
                                if success:
                                    archived_count += 1
                                    batch_archived += 1
                                    reasons[archive_reason] += 1
                                    archived_orders.append({
                                        "order_name": analysis_order_name,
                                        "archive_reason": archive_reason
                                    })
                                    logger.info(f"Archived fraud analysis for order {analysis_order_name} (reason: {archive_reason})")
                                else:
                                    failed_count += 1
                            
                        except Exception as e:
                            logger.error(f"Error processing analysis {analysis_id} (order: {analysis_order_name}): {str(e)}")
                            failed_count += 1
                    
                    # Commit after each batch to avoid long locks
                    if batch_archived > 0:
                        self.db.commit()
                        logger.info(f"Committed batch: archived {batch_archived} analyses")
                    
                    # Add a small delay between batches to allow other operations
                    await asyncio.sleep(0.1)
            
            # Calculate remaining analyses
            remaining_count = total_count - len(active_analyses)
            
            return {
                "checked": len(active_analyses),
                "archived": archived_count,
                "failed": failed_count,
                "reasons": reasons,
                "archived_orders": archived_orders,
                "total_remaining": remaining_count
            }
            
        except Exception as e:
            logger.error(f"Error in archive_fulfilled_and_cancelled_analyses: {str(e)}")
            self.db.rollback()
            raise
    
    async def _get_order_status(self, client: ShopifyClient, order_name: str) -> Optional[Dict[str, Any]]:
        """Get the current status of an order from Shopify.
        
        Args:
            client: Shopify client instance
            order_name: Order name (e.g., "#1001")
            
        Returns:
            Order status information or None if not found
        """
        try:
            # Use the get_order_fraud_data method which exists in ShopifyClient
            order_data = await client.get_order_fraud_data(order_name)
            
            if not order_data:
                return None
            
            # The order data is directly in the response, not nested
            # Check both order_info and raw_order_data fields since structure varies
            order_info = order_data.get("order_info", {})
            raw_data = order_data.get("raw_order_data", order_data)  # fallback to root if no raw_order_data
            
            # Extract fulfillment status - check multiple possible locations
            fulfillment_status = (
                order_info.get("fulfillment_status") or 
                raw_data.get("displayFulfillmentStatus") or
                order_data.get("displayFulfillmentStatus")  # Check root level too
            )
            
            # Extract cancellation status - check multiple possible locations
            cancelled_at = (
                raw_data.get("cancelledAt") or
                order_data.get("cancelledAt")
            )
            
            # Also check displayFinancialStatus for cancelled orders
            financial_status = (
                order_info.get("financial_status") or
                raw_data.get("displayFinancialStatus") or
                order_data.get("displayFinancialStatus")
            )
            
            logger.info(f"Order {order_name} status - Fulfillment: {fulfillment_status}, Financial: {financial_status}, Cancelled: {cancelled_at}")
            
            return {
                "displayFulfillmentStatus": fulfillment_status,
                "displayFinancialStatus": financial_status,
                "cancelledAt": cancelled_at,
                "status": raw_data.get("status") or order_data.get("status")
            }
            
        except Exception as e:
            logger.error(f"Error getting order status for {order_name}: {str(e)}")
            return None
    
    def _archive_analysis(self, analysis: FraudAnalysis, archive_reason: str) -> bool:
        """Archive a single fraud analysis record.
        
        Args:
            analysis: FraudAnalysis instance to archive
            archive_reason: Reason for archiving (order_fulfilled or order_cancelled)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # First, check if there are any processed_fraud_orders that reference this analysis
            from models import ProcessedFraudOrder
            
            # Preserve ProcessedFraudOrder records as deduplication guards by nulling
            # out the FK instead of deleting them. The dedup check in
            # process_store_fraud_detection uses store_id + order_id, not fraud_analysis_id.
            preserved_count = self.db.query(ProcessedFraudOrder).filter(
                ProcessedFraudOrder.fraud_analysis_id == analysis.id
            ).update({ProcessedFraudOrder.fraud_analysis_id: None})
            
            # First check if this analysis is already archived
            check_sql = text("SELECT id FROM fraud_analyses_archive WHERE id = :id")
            existing = self.db.execute(check_sql, {"id": analysis.id}).fetchone()
            
            if existing:
                logger.warning(f"Analysis {analysis.id} already exists in archive, skipping insert")
                # Still need to delete from main table and related records
                self.db.delete(analysis)
                return True
            
            # Build insert statement for archive table
            insert_sql = text("""
                INSERT INTO fraud_analyses_archive (
                    id, user_id, store_id, order_name, shopify_order_id,
                    is_first_time_customer, order_total, transaction_attempts_count,
                    customer_name, duplicate_within_7days, previous_order_delivery_status,
                    previous_order_total, current_order_total, shopify_fraud_risk_level,
                    customer_notes, billing_address_outside_us,
                    same_billing_shipping, shipping_state, additional_details,
                    current_order_delivery_status, days_since_last_delivery,
                    raw_shopify_data, duplicate_match_details, transaction_details,
                    risk_assessment_details, customer_order_history, delivery_analytics,
                    rule_triggered_ids, rule_processing_results,
                    analysis_timestamp, processing_time_seconds, analysis_version,
                    archived_at, archive_reason
                ) VALUES (
                    :id, :user_id, :store_id, :order_name, :shopify_order_id,
                    :is_first_time_customer, :order_total, :transaction_attempts_count,
                    :customer_name, :duplicate_within_7days, :previous_order_delivery_status,
                    :previous_order_total, :current_order_total, :shopify_fraud_risk_level,
                    :customer_notes, :billing_address_outside_us,
                    :same_billing_shipping, :shipping_state, :additional_details,
                    :current_order_delivery_status, :days_since_last_delivery,
                    :raw_shopify_data, :duplicate_match_details, :transaction_details,
                    :risk_assessment_details, :customer_order_history, :delivery_analytics,
                    :rule_triggered_ids, :rule_processing_results,
                    :analysis_timestamp, :processing_time_seconds, :analysis_version,
                    :archived_at, :archive_reason
                )
            """)
            
            # Convert JSON fields to strings for SQLite
            import json
            
            # Execute insert
            self.db.execute(insert_sql, {
                "id": analysis.id,
                "user_id": analysis.user_id,
                "store_id": analysis.store_id,
                "order_name": analysis.order_name,
                "shopify_order_id": analysis.shopify_order_id,
                "is_first_time_customer": analysis.is_first_time_customer,
                "order_total": str(analysis.order_total) if analysis.order_total else None,
                "transaction_attempts_count": analysis.transaction_attempts_count,
                "customer_name": analysis.customer_name,
                "duplicate_within_7days": analysis.duplicate_within_7days,
                "previous_order_delivery_status": analysis.previous_order_delivery_status,
                "previous_order_total": str(analysis.previous_order_total) if analysis.previous_order_total else None,
                "current_order_total": str(analysis.current_order_total) if analysis.current_order_total else None,
                "shopify_fraud_risk_level": analysis.shopify_fraud_risk_level,
                "customer_notes": analysis.customer_notes,
                "billing_address_outside_us": analysis.billing_address_outside_us,
                "same_billing_shipping": analysis.same_billing_shipping,
                "shipping_state": analysis.shipping_state,
                "additional_details": analysis.additional_details,
                "current_order_delivery_status": analysis.current_order_delivery_status,
                "days_since_last_delivery": analysis.days_since_last_delivery,
                "raw_shopify_data": json.dumps(analysis.raw_shopify_data) if analysis.raw_shopify_data else None,
                "duplicate_match_details": json.dumps(analysis.duplicate_match_details) if analysis.duplicate_match_details else None,
                "transaction_details": json.dumps(analysis.transaction_details) if analysis.transaction_details else None,
                "risk_assessment_details": json.dumps(analysis.risk_assessment_details) if analysis.risk_assessment_details else None,
                "customer_order_history": json.dumps(analysis.customer_order_history) if analysis.customer_order_history else None,
                "delivery_analytics": json.dumps(analysis.delivery_analytics) if analysis.delivery_analytics else None,
                "rule_triggered_ids": json.dumps(analysis.rule_triggered_ids) if analysis.rule_triggered_ids else None,
                "rule_processing_results": json.dumps(analysis.rule_processing_results) if analysis.rule_processing_results else None,
                "analysis_timestamp": analysis.analysis_timestamp,
                "processing_time_seconds": str(analysis.processing_time_seconds) if analysis.processing_time_seconds else None,
                "analysis_version": analysis.analysis_version,
                "archived_at": datetime.now(timezone.utc),
                "archive_reason": archive_reason
            })
            
            # Delete from active table (after deleting related records)
            self.db.delete(analysis)
            
            logger.info(f"Archived analysis {analysis.id} for order {analysis.order_name} (preserved {preserved_count} ProcessedFraudOrder records)")
            
            return True
            
        except SQLAlchemyError as e:
            logger.error(f"Database error archiving analysis {analysis.id} (order: {analysis.order_name}): {str(e)}", exc_info=True)
            logger.error(f"SQL Error Details: {e.__class__.__name__}: {str(e)}")
            self.db.rollback()  # Rollback the failed transaction
            return False
        except Exception as e:
            logger.error(f"Error archiving analysis {analysis.id} (order: {analysis.order_name}): {str(e)}", exc_info=True)
            self.db.rollback()  # Rollback the failed transaction
            return False
    
    def cleanup_old_archived_analyses(self, user_id: int, retention_days: int) -> int:
        """Delete archived fraud analyses older than retention period.
        
        Args:
            user_id: User ID to clean up archives for
            retention_days: Number of days to retain archived analyses
            
        Returns:
            Number of archived analyses deleted
        """
        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
            
            # Delete old archived analyses
            delete_sql = text("""
                DELETE FROM fraud_analyses_archive 
                WHERE user_id = :user_id 
                AND archived_at < :cutoff_date
            """)
            
            result = self.db.execute(delete_sql, {
                "user_id": user_id,
                "cutoff_date": cutoff_date
            })
            
            deleted_count = result.rowcount
            self.db.commit()
            
            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} archived fraud analyses older than {retention_days} days for user {user_id}")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up archived analyses: {str(e)}")
            self.db.rollback()
            return 0
    
    def get_archive_statistics(self, user_id: int) -> Dict[str, Any]:
        """Get statistics about archived fraud analyses.
        
        Args:
            user_id: User ID to get statistics for
            
        Returns:
            Dictionary with archive statistics
        """
        try:
            # Count total archived
            total_sql = text("""
                SELECT COUNT(*) as total,
                       COUNT(CASE WHEN archive_reason = 'order_fulfilled' THEN 1 END) as fulfilled,
                       COUNT(CASE WHEN archive_reason = 'order_cancelled' THEN 1 END) as cancelled,
                       MIN(archived_at) as oldest_archive,
                       MAX(archived_at) as newest_archive
                FROM fraud_analyses_archive
                WHERE user_id = :user_id
            """)
            
            result = self.db.execute(total_sql, {"user_id": user_id}).fetchone()
            
            return {
                "total_archived": result.total if result else 0,
                "archived_fulfilled": result.fulfilled if result else 0,
                "archived_cancelled": result.cancelled if result else 0,
                "oldest_archive_date": result.oldest_archive.isoformat() if result and result.oldest_archive else None,
                "newest_archive_date": result.newest_archive.isoformat() if result and result.newest_archive else None
            }
            
        except Exception as e:
            logger.error(f"Error getting archive statistics: {str(e)}")
            return {
                "total_archived": 0,
                "archived_fulfilled": 0,
                "archived_cancelled": 0,
                "oldest_archive_date": None,
                "newest_archive_date": None
            }