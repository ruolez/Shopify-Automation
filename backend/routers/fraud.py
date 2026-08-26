"""Fraud detection and fraud rules endpoints"""
import logging
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func, text

from database import get_db
from models import User, ShopifyStore, OrderLog, Settings, FraudAnalysis, FraudDetectionRule, FraudRuleStore
from auth import get_current_user
from schemas import FraudRuleCreate, FraudRuleResponse, FraudRuleStoreBrief
from shopify_client import ShopifyClient
from fraud_service import FraudAnalysisService
from dependencies import _format_timestamp_with_user_timezone

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Fraud Detection"])


def _normalize_fraud_rule_conditions(conditions):
    """Normalize fraud rule conditions - capitalize fraud risk level values"""
    if isinstance(conditions, dict):
        if 'conditions' in conditions:
            # Handle new format with operator and conditions array
            normalized_conditions = []
            for condition in conditions['conditions']:
                if (condition.get('field') == 'fraud_risk_level' and
                    condition.get('operator') in ['risk_level_equals', 'risk_level_not_equals']):
                    # Capitalize the risk level value to match Shopify's format
                    condition = condition.copy()
                    condition['value'] = str(condition['value']).upper()
                normalized_conditions.append(condition)

            return {
                'operator': conditions['operator'],
                'conditions': normalized_conditions
            }
        else:
            # Handle legacy format - direct conditions array
            normalized_conditions = []
            for condition in conditions:
                if (condition.get('field') == 'fraud_risk_level' and
                    condition.get('operator') in ['risk_level_equals', 'risk_level_not_equals']):
                    # Capitalize the risk level value to match Shopify's format
                    condition = condition.copy()
                    condition['value'] = str(condition['value']).upper()
                normalized_conditions.append(condition)
            return normalized_conditions
    return conditions


# Fraud Detection Endpoints
@router.post("/fraud-detection/analyze/{store_id}")
async def analyze_order_fraud(
    store_id: int,
    order_name: str = Query(..., description="Order number to analyze (e.g., TS8270741)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger fraud analysis for a specific order"""
    store = db.query(ShopifyStore).filter(
        ShopifyStore.id == store_id,
        ShopifyStore.user_id == current_user.id
    ).first()

    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found"
        )

    try:
        # Get user settings for fraud analysis
        user_settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()

        # Create fraud analysis service
        fraud_service = FraudAnalysisService(
            db=db,
            user_id=current_user.id,
            store=store,
            settings=user_settings
        )

        # Get order data and analyze
        client = ShopifyClient(store.shop_domain, store.access_token)
        fraud_data = await client.get_order_fraud_data(order_name)

        if not fraud_data or not fraud_data.get("order_info"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order {order_name} not found"
            )

        # Process the fraud analysis
        analysis_result = await fraud_service.analyze_order(fraud_data)

        return {
            "success": True,
            "order_name": order_name,
            "analysis": analysis_result
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing order {order_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze order: {str(e)}"
        )


@router.get("/fraud-detection/analyses")
async def get_fraud_analyses(
    store_id: Optional[int] = None,
    order_name: Optional[str] = None,
    search: Optional[str] = None,
    risk_level: Optional[str] = None,
    matched_rules: Optional[str] = None,
    first_time_customer: Optional[bool] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    sort_field: Optional[str] = "analysis_timestamp",
    sort_direction: Optional[str] = "desc",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all fraud analyses with filtering and pagination"""
    try:
        limit = min(limit, 1000)
        # Build query
        query = db.query(FraudAnalysis).filter(FraudAnalysis.user_id == current_user.id)

        # Apply filters
        if store_id:
            # Verify store ownership
            store = db.query(ShopifyStore).filter(
                ShopifyStore.id == store_id,
                ShopifyStore.user_id == current_user.id
            ).first()
            if not store:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Store not found"
                )
            query = query.filter(FraudAnalysis.store_id == store_id)

        if order_name:
            query = query.filter(FraudAnalysis.order_name.ilike(f"%{order_name}%"))

        if search:
            query = query.filter(FraudAnalysis.order_name.ilike(f"%{search}%"))

        if risk_level:
            query = query.filter(FraudAnalysis.shopify_fraud_risk_level == risk_level.upper())

        if first_time_customer is not None:
            query = query.filter(FraudAnalysis.is_first_time_customer == first_time_customer)

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                query = query.filter(FraudAnalysis.analysis_timestamp >= start_dt)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid start_date format. Use ISO format."
                )

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                query = query.filter(FraudAnalysis.analysis_timestamp <= end_dt)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid end_date format. Use ISO format."
                )

        # Apply matched rules filter
        if matched_rules:
            rules_list = [r.strip() for r in matched_rules.split(",") if r.strip()]
            if rules_list:
                # Filter using lightweight tuples in chunks to avoid loading all full ORM objects
                filtered_ids = []
                chunk_size = 500
                offset_val = 0

                while True:
                    chunk = query.with_entities(
                        FraudAnalysis.id,
                        FraudAnalysis.rule_processing_results
                    ).offset(offset_val).limit(chunk_size).all()

                    if not chunk:
                        break

                    for analysis_id, rule_results_data in chunk:
                        if rule_results_data and isinstance(rule_results_data, dict):
                            rule_results = rule_results_data.get("results", [])
                            matched_rule_names = [
                                r.get("rule_name", "")
                                for r in rule_results
                                if isinstance(r, dict) and r.get("matched", False)
                            ]

                            if "No rules matched" in rules_list and not matched_rule_names:
                                filtered_ids.append(analysis_id)
                            elif any(rule_name in rules_list for rule_name in matched_rule_names):
                                filtered_ids.append(analysis_id)
                        elif "No rules matched" in rules_list:
                            filtered_ids.append(analysis_id)

                    offset_val += chunk_size

                if filtered_ids:
                    query = db.query(FraudAnalysis).filter(FraudAnalysis.id.in_(filtered_ids))
                else:
                    return {
                        "total": 0,
                        "skip": skip,
                        "limit": limit,
                        "data": []
                    }

        # Get total count before pagination
        total_count = query.count()

        # Apply sorting
        sort_field_map = {
            "order_name": FraudAnalysis.order_name,
            "risk_level": FraudAnalysis.shopify_fraud_risk_level,
            "customer_name": FraudAnalysis.customer_name,
            "order_total": FraudAnalysis.order_total,
            "analysis_timestamp": FraudAnalysis.analysis_timestamp
        }

        sort_column = sort_field_map.get(sort_field, FraudAnalysis.analysis_timestamp)
        if sort_direction.upper() == "ASC":
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        # Apply pagination with eager loading to avoid N+1 store queries
        analyses = query.options(selectinload(FraudAnalysis.store)).offset(skip).limit(limit).all()

        # Convert to response format
        result = []
        for analysis in analyses:
            store = analysis.store

            result.append({
                "id": analysis.id,
                "user_id": analysis.user_id,
                "store_id": analysis.store_id,
                "store_name": store.shop_name if store else "Unknown Store",
                "order_name": analysis.order_name,
                "shopify_order_id": analysis.shopify_order_id,
                "is_first_time_customer": analysis.is_first_time_customer,
                "order_total": float(analysis.order_total) if analysis.order_total else None,
                "transaction_attempts_count": analysis.transaction_attempts_count,
                "customer_name": analysis.customer_name,
                "duplicate_within_7days": analysis.duplicate_within_7days,
                "previous_order_delivery_status": analysis.previous_order_delivery_status,
                "previous_order_total": float(analysis.previous_order_total) if analysis.previous_order_total else None,
                "current_order_total": float(analysis.current_order_total) if analysis.current_order_total else None,
                "shopify_fraud_risk_level": analysis.shopify_fraud_risk_level,
                "customer_notes": analysis.customer_notes,
                "billing_address_outside_us": analysis.billing_address_outside_us,
                "same_billing_shipping": analysis.same_billing_shipping,
                "shipping_state": analysis.shipping_state,
                "current_order_delivery_status": analysis.current_order_delivery_status,
                "rule_processing_results": analysis.rule_processing_results,
                "analysis_timestamp": _format_timestamp_with_user_timezone(analysis.analysis_timestamp, current_user.id, db),
                "processing_time_seconds": float(analysis.processing_time_seconds) if analysis.processing_time_seconds else None
            })

        return {
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "analyses": result,
            "data": result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fraud analyses: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get fraud analyses"
        )


@router.get("/fraud-detection/matched-rules")
async def get_matched_rules(
    store_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of all matched rules from fraud analyses"""
    try:
        # Build query
        query = db.query(FraudAnalysis).filter(FraudAnalysis.user_id == current_user.id)

        if store_id:
            query = query.filter(FraudAnalysis.store_id == store_id)

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                query = query.filter(FraudAnalysis.analysis_timestamp >= start_dt)
            except ValueError:
                pass

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                query = query.filter(FraudAnalysis.analysis_timestamp <= end_dt)
            except ValueError:
                pass

        analyses = query.all()

        # Extract unique rule names from all analyses
        rule_counts = {}
        for analysis in analyses:
            if analysis.rule_processing_results:
                results = analysis.rule_processing_results
                if isinstance(results, dict):
                    rule_results = results.get("results", [])
                    has_matched_rules = False
                    for rule_result in rule_results:
                        if isinstance(rule_result, dict) and rule_result.get("matched", False):
                            rule_name = rule_result.get("rule_name", "Unknown")
                            rule_counts[rule_name] = rule_counts.get(rule_name, 0) + 1
                            has_matched_rules = True
                    # Add "No rules matched" count
                    if not has_matched_rules:
                        rule_counts["No rules matched"] = rule_counts.get("No rules matched", 0) + 1
                else:
                    rule_counts["No rules matched"] = rule_counts.get("No rules matched", 0) + 1

        return {
            "rules": sorted(rule_counts, key=lambda name: -rule_counts[name]),
            "rule_counts": rule_counts,
        }

    except Exception as e:
        logger.error(f"Error getting matched rules: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get matched rules"
        )


@router.get("/fraud-detection/rule-intersection-counts")
async def get_rule_intersection_counts(
    selected_rules: Optional[str] = None,
    store_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    risk_level: Optional[str] = None,
    first_time_customer: Optional[bool] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get counts of how many analyses match each rule while also matching the selected rules"""
    try:
        # Build base query
        query = db.query(FraudAnalysis).filter(FraudAnalysis.user_id == current_user.id)

        if store_id:
            query = query.filter(FraudAnalysis.store_id == store_id)

        if risk_level:
            query = query.filter(FraudAnalysis.shopify_fraud_risk_level == risk_level.upper())

        if first_time_customer is not None:
            query = query.filter(FraudAnalysis.is_first_time_customer == first_time_customer)

        if search:
            query = query.filter(FraudAnalysis.order_name.ilike(f"%{search}%"))

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                query = query.filter(FraudAnalysis.analysis_timestamp >= start_dt)
            except ValueError:
                pass

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                query = query.filter(FraudAnalysis.analysis_timestamp <= end_dt)
            except ValueError:
                pass

        analyses = query.all()

        # Parse selected rules
        selected_rules_list = []
        if selected_rules:
            selected_rules_list = [r.strip() for r in selected_rules.split(",") if r.strip()]

        # First pass: find all analyses that match the selected rules
        matching_analyses_ids = set()
        all_rules = set()
        rule_intersection_counts = {}

        for analysis in analyses:
            analysis_rule_names = set()
            has_matched_rules = False

            if analysis.rule_processing_results:
                results = analysis.rule_processing_results
                if isinstance(results, dict):
                    rule_results = results.get("results", [])
                    for rule_result in rule_results:
                        if isinstance(rule_result, dict) and rule_result.get("matched", False):
                            rule_name = rule_result.get("rule_name", "")
                            analysis_rule_names.add(rule_name)
                            all_rules.add(rule_name)
                            has_matched_rules = True

            if not has_matched_rules:
                analysis_rule_names.add("No rules matched")

            # Check if this analysis matches all selected rules
            if not selected_rules_list:
                matching_analyses_ids.add(analysis.id)
            else:
                if all(rule in analysis_rule_names for rule in selected_rules_list):
                    matching_analyses_ids.add(analysis.id)

        # Add "No rules matched" to the set
        all_rules.add("No rules matched")

        # Second pass: count intersections
        for rule in all_rules:
            if selected_rules_list and rule in selected_rules_list:
                # For already selected rules, show the count of current filtered results
                rule_intersection_counts[rule] = len(matching_analyses_ids)
            else:
                # For unselected rules, count how many of the matching analyses also have this rule
                count = 0
                for analysis_id in matching_analyses_ids:
                    analysis = next((a for a in analyses if a.id == analysis_id), None)
                    if analysis:
                        if rule == "No rules matched":
                            # Check if this analysis has no matched rules
                            if analysis.rule_processing_results:
                                results = analysis.rule_processing_results
                                if isinstance(results, dict):
                                    rule_results = results.get("results", [])
                                    has_matched_rules = any(
                                        r.get("matched", False) for r in rule_results
                                        if isinstance(r, dict)
                                    )
                                    if not has_matched_rules:
                                        count += 1
                            else:
                                count += 1
                        else:
                            # Check if this analysis has the specific rule
                            if analysis.rule_processing_results:
                                results = analysis.rule_processing_results
                                if isinstance(results, dict):
                                    rule_results = results.get("results", [])
                                    for rule_result in rule_results:
                                        if (isinstance(rule_result, dict) and
                                            rule_result.get("matched", False) and
                                            rule_result.get("rule_name", "") == rule):
                                            count += 1
                                            break

                rule_intersection_counts[rule] = count

        return {
            "rule_counts": rule_intersection_counts,
            "total_matching": len(matching_analyses_ids),
            "selected_rules": selected_rules_list
        }

    except Exception as e:
        logger.error(f"Error getting rule intersection counts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get rule intersection counts"
        )


@router.get("/fraud-detection/analysis/{analysis_id}")
async def get_fraud_analysis_details(
    analysis_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get detailed fraud analysis by ID"""
    try:
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.id == analysis_id,
            FraudAnalysis.user_id == current_user.id
        ).first()

        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud analysis not found"
            )

        # Get store name
        store_name = analysis.store.shop_name if analysis.store else "Unknown Store"

        return {
            "analysis": {
                "id": analysis.id,
                "user_id": analysis.user_id,
                "store_id": analysis.store_id,
                "order_name": analysis.order_name,
                "shopify_order_id": analysis.shopify_order_id,
                "is_first_time_customer": analysis.is_first_time_customer,
                "order_total": float(analysis.order_total) if analysis.order_total else None,
                "transaction_attempts_count": analysis.transaction_attempts_count,
                "customer_name": analysis.customer_name,
                "duplicate_within_7days": analysis.duplicate_within_7days,
                "previous_order_delivery_status": analysis.previous_order_delivery_status,
                "previous_order_total": float(analysis.previous_order_total) if analysis.previous_order_total else None,
                "current_order_total": float(analysis.current_order_total) if analysis.current_order_total else None,
                "shopify_fraud_risk_level": analysis.shopify_fraud_risk_level,
                "customer_notes": analysis.customer_notes,
                "billing_address_outside_us": analysis.billing_address_outside_us,
                "same_billing_shipping": analysis.same_billing_shipping,
                "shipping_state": analysis.shipping_state,
                "additional_details": analysis.additional_details,
                "current_order_delivery_status": analysis.current_order_delivery_status,
                "raw_shopify_data": analysis.raw_shopify_data,
                "duplicate_match_details": analysis.duplicate_match_details,
                "transaction_details": analysis.transaction_details,
                "risk_assessment_details": analysis.risk_assessment_details,
                "customer_order_history": analysis.customer_order_history,
                "analysis_timestamp": _format_timestamp_with_user_timezone(analysis.analysis_timestamp, current_user.id, db),
                "processing_time_seconds": float(analysis.processing_time_seconds) if analysis.processing_time_seconds else None,
                "analysis_version": analysis.analysis_version
            },
            "store_name": store_name
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fraud analysis details: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get fraud analysis details"
        )


@router.get("/fraud-detection/stats")
async def get_fraud_detection_stats(
    store_id: Optional[int] = None,
    days: Optional[int] = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get fraud detection statistics for dashboard"""
    try:
        # Base query
        query = db.query(FraudAnalysis).filter(FraudAnalysis.user_id == current_user.id)

        # Filter by store if specified
        if store_id:
            # Verify store ownership
            store = db.query(ShopifyStore).filter(
                ShopifyStore.id == store_id,
                ShopifyStore.user_id == current_user.id
            ).first()
            if not store:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Store not found"
                )
            query = query.filter(FraudAnalysis.store_id == store_id)

        # Filter by date range
        if days:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.filter(FraudAnalysis.analysis_timestamp >= cutoff_date)

        # Get all analyses for stats calculation
        analyses = query.all()

        total_analyses = len(analyses)

        if total_analyses == 0:
            return {
                "total_analyses": 0,
                "period_days": days,
                "stats": {
                    "first_time_customers": {"count": 0, "percentage": 0},
                    "multiple_transaction_attempts": {"count": 0, "percentage": 0},
                    "duplicate_orders": {"count": 0, "percentage": 0},
                    "high_fraud_risk": {"count": 0, "percentage": 0}
                },
                "risk_level_distribution": {
                    "low": {"count": 0, "percentage": 0},
                    "medium": {"count": 0, "percentage": 0},
                    "high": {"count": 0, "percentage": 0},
                    "unknown": {"count": 0, "percentage": 0}
                },
                "average_order_total": 0,
                "recent_analyses": []
            }

        # Calculate statistics
        first_time_customers = sum(1 for a in analyses if a.is_first_time_customer)
        multiple_attempts = sum(1 for a in analyses if a.transaction_attempts_count and a.transaction_attempts_count > 1)
        duplicate_orders = sum(1 for a in analyses if a.duplicate_within_7days)
        high_fraud_risk = sum(1 for a in analyses if a.shopify_fraud_risk_level and a.shopify_fraud_risk_level.upper() == 'HIGH')

        # Risk level distribution
        risk_levels = {"low": 0, "medium": 0, "high": 0, "unknown": 0}
        for analysis in analyses:
            level = (analysis.shopify_fraud_risk_level or "unknown").lower()
            risk_levels[level] = risk_levels.get(level, 0) + 1

        # Average order total
        order_totals = [float(a.order_total) for a in analyses if a.order_total]
        average_order_total = sum(order_totals) / len(order_totals) if order_totals else 0

        # Recent analyses (last 5)
        recent_analyses = sorted(analyses, key=lambda x: x.analysis_timestamp or datetime.min, reverse=True)[:5]
        recent_list = []
        for analysis in recent_analyses:
            store_name = analysis.store.shop_name if analysis.store else "Unknown Store"
            recent_list.append({
                "id": analysis.id,
                "order_name": analysis.order_name,
                "store_name": store_name,
                "analyzed_at": _format_timestamp_with_user_timezone(analysis.analysis_timestamp, current_user.id, db),
                "fraud_risk_level": analysis.shopify_fraud_risk_level or "unknown"
            })

        return {
            "total_analyses": total_analyses,
            "period_days": days,
            "stats": {
                "first_time_customers": {
                    "count": first_time_customers,
                    "percentage": round((first_time_customers / total_analyses) * 100, 1)
                },
                "multiple_transaction_attempts": {
                    "count": multiple_attempts,
                    "percentage": round((multiple_attempts / total_analyses) * 100, 1)
                },
                "duplicate_orders": {
                    "count": duplicate_orders,
                    "percentage": round((duplicate_orders / total_analyses) * 100, 1)
                },
                "high_fraud_risk": {
                    "count": high_fraud_risk,
                    "percentage": round((high_fraud_risk / total_analyses) * 100, 1)
                }
            },
            "risk_level_distribution": {
                level: {
                    "count": count,
                    "percentage": round((count / total_analyses) * 100, 1)
                }
                for level, count in risk_levels.items()
            },
            "average_order_total": round(average_order_total, 2),
            "recent_analyses": recent_list
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fraud detection stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get fraud detection statistics"
        )


@router.get("/fraud-detection/archived-analyses")
async def get_archived_fraud_analyses(
    store_id: Optional[int] = None,
    order_name: Optional[str] = None,
    search: Optional[str] = None,
    archive_reason: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    sort_field: Optional[str] = "archived_at",
    sort_direction: Optional[str] = "desc",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get archived fraud analyses with filtering and pagination"""
    try:
        # Build query for archived analyses
        params = {
            "user_id": current_user.id,
            "skip": skip,
            "limit": limit
        }

        # Start building the WHERE clause
        where_clauses = ["user_id = :user_id"]

        # Apply filters
        if store_id:
            # Verify store ownership
            store = db.query(ShopifyStore).filter(
                ShopifyStore.id == store_id,
                ShopifyStore.user_id == current_user.id
            ).first()
            if not store:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Store not found"
                )
            where_clauses.append("store_id = :store_id")
            params["store_id"] = store_id

        if order_name:
            where_clauses.append("order_name LIKE :order_name")
            params["order_name"] = f"%{order_name}%"

        if search:
            where_clauses.append("order_name LIKE :search")
            params["search"] = f"%{search}%"

        if archive_reason:
            where_clauses.append("archive_reason = :archive_reason")
            params["archive_reason"] = archive_reason

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                where_clauses.append("archived_at >= :start_date")
                params["start_date"] = start_dt
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid start_date format. Use ISO format."
                )

        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                where_clauses.append("archived_at <= :end_date")
                params["end_date"] = end_dt
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid end_date format. Use ISO format."
                )

        # Build the WHERE clause
        where_sql = " AND ".join(where_clauses)

        # Map sort fields
        sort_field_map = {
            "order_name": "order_name",
            "risk_level": "shopify_fraud_risk_level",
            "customer_name": "customer_name",
            "order_total": "order_total",
            "archived_at": "archived_at",
            "archive_reason": "archive_reason"
        }

        # Validate and set sort field
        actual_sort_field = sort_field_map.get(sort_field, "archived_at")
        sort_dir = "DESC" if sort_direction.upper() == "DESC" else "ASC"

        # Check if archive table exists first
        table_exists = db.execute(
            text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'fraud_analyses_archive')")
        ).scalar()

        if not table_exists:
            # Return empty result if table doesn't exist
            return {
                "analyses": [],
                "total": 0,
                "skip": skip,
                "limit": limit
            }

        # Count total archived analyses matching filters
        count_sql = f"SELECT COUNT(*) as total FROM fraud_analyses_archive WHERE {where_sql}"
        count_result = db.execute(text(count_sql), params).fetchone()
        total_count = count_result.total if count_result else 0

        # Get archived analyses with pagination
        query_sql = f"""
            SELECT * FROM fraud_analyses_archive
            WHERE {where_sql}
            ORDER BY {actual_sort_field} {sort_dir}
            LIMIT :limit OFFSET :skip
        """

        result = db.execute(text(query_sql), params)

        # Convert results to list of dicts
        analyses = []
        for row in result:
            analysis_dict = dict(row._mapping)

            # Parse JSON fields
            json_fields = [
                'raw_shopify_data', 'duplicate_match_details', 'transaction_details',
                'risk_assessment_details', 'customer_order_history', 'delivery_analytics',
                'rule_triggered_ids', 'rule_processing_results'
            ]

            for field in json_fields:
                if analysis_dict.get(field) and isinstance(analysis_dict[field], str):
                    try:
                        analysis_dict[field] = json.loads(analysis_dict[field])
                    except Exception as e:
                        logger.warning(f"Failed to parse JSON field {field}: {e}")
                        pass

            # Get store name
            store = db.query(ShopifyStore).filter(
                ShopifyStore.id == analysis_dict['store_id']
            ).first()

            analyses.append({
                **analysis_dict,
                "store_name": store.shop_name if store else "Unknown Store",
                "is_archived": True
            })

        return {
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "data": analyses
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting archived fraud analyses: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get archived fraud analyses"
        )


@router.post("/fraud-detection/archive/{analysis_id}")
async def manually_archive_fraud_analysis(
    analysis_id: int,
    archive_reason: str = "manual_archive",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually archive a specific fraud analysis for testing purposes"""
    try:
        # Find the analysis
        analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.id == analysis_id,
            FraudAnalysis.user_id == current_user.id
        ).first()

        if not analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud analysis not found"
            )

        # Validate archive reason
        valid_reasons = ["manual_archive", "order_fulfilled", "order_cancelled"]
        if archive_reason not in valid_reasons:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid archive reason. Must be one of: {', '.join(valid_reasons)}"
            )

        # Use the fraud archive service to archive the analysis
        from fraud_archive_service import FraudArchiveService
        archive_service = FraudArchiveService(db)

        # Archive the analysis
        archive_service._archive_analysis(analysis, archive_reason)

        # Commit the transaction
        db.commit()

        return {
            "message": "Fraud analysis archived successfully",
            "analysis_id": analysis_id,
            "order_name": analysis.order_name,
            "archive_reason": archive_reason,
            "archived_at": datetime.now(timezone.utc).isoformat()
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error manually archiving fraud analysis: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to archive fraud analysis"
        )


@router.post("/fraud-detection/archive-fulfilled-cancelled")
async def bulk_archive_fulfilled_cancelled_orders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually trigger the archive process for all fulfilled and cancelled orders"""
    logger.info(f"Bulk archive requested by user {current_user.id} ({current_user.email})")
    try:
        from fraud_archive_service import FraudArchiveService

        archive_service = FraudArchiveService(db)

        # Use the existing archive service method that fetches fresh data from Shopify
        result = await archive_service.archive_fulfilled_and_cancelled_analyses(current_user.id)

        # Create a more informative message based on the results
        archived_count = result["archived"]
        checked_count = result["checked"]

        # Get remaining count
        remaining_count = result.get("total_remaining", 0)

        # Get user's batch size setting
        settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
        batch_size = settings.reconciliation_batch_size if settings else 500

        if archived_count == 0:
            if checked_count == 0:
                message = "No fraud analyses found to reconcile."
            else:
                message = f"Checked {checked_count} orders - all are still unfulfilled. Nothing to reconcile at this time."
        else:
            message = f"Reconciliation completed. Archived {archived_count} out of {checked_count} orders."

        # Add note about remaining analyses
        if remaining_count > 0:
            message += f" ({remaining_count} more orders to check - run again to continue, batch size: {batch_size})"

        # Use the actual archived orders from the service
        archived_orders = result.get("archived_orders", [])

        return {
            "message": message,
            "archived_count": archived_count,
            "checked_count": checked_count,
            "archived_orders": archived_orders,
            "total_remaining": remaining_count
        }

    except Exception as e:
        logger.error(f"Error during bulk archive process: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run bulk archive process: {str(e)}"
        )


def _validate_store_ids_for_user(db: Session, user_id: int, store_ids: List[int]) -> List[int]:
    """Return the unique, user-owned subset of store_ids. Raises 400 on any foreign id."""
    if not store_ids:
        return []
    unique_ids = list({int(sid) for sid in store_ids})
    owned = {
        row[0]
        for row in db.query(ShopifyStore.id).filter(
            ShopifyStore.id.in_(unique_ids),
            ShopifyStore.user_id == user_id,
        ).all()
    }
    missing = [sid for sid in unique_ids if sid not in owned]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Store ids do not belong to this user: {missing}",
        )
    return unique_ids


def _replace_rule_store_mappings(db: Session, rule_id: int, store_ids: List[int]) -> None:
    """Delete existing mappings for the rule and insert the new set (no commit)."""
    db.query(FraudRuleStore).filter(FraudRuleStore.fraud_rule_id == rule_id).delete(synchronize_session=False)
    for sid in store_ids:
        db.add(FraudRuleStore(fraud_rule_id=rule_id, store_id=sid))


def _serialize_fraud_rule(rule: FraudDetectionRule) -> FraudRuleResponse:
    """Build a response payload including the rule's applicable stores."""
    stores = [
        FraudRuleStoreBrief(id=s.id, shop_name=s.shop_name, shop_domain=s.shop_domain)
        for s in (rule.applicable_stores or [])
    ]
    return FraudRuleResponse(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        conditions=rule.conditions,
        actions=rule.actions,
        priority=rule.priority,
        delay_ms=rule.delay_ms,
        is_active=rule.is_active,
        stores=stores,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


# Fraud Rule Management endpoints
@router.post("/fraud-rules", status_code=status.HTTP_201_CREATED, response_model=FraudRuleResponse)
async def create_fraud_rule(
    rule_data: FraudRuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new fraud detection rule"""
    try:
        # Normalize conditions through the schema validator and convert to dict
        if hasattr(rule_data.conditions, 'dict'):
            conditions_to_save = rule_data.conditions.dict()
        else:
            conditions_to_save = rule_data.conditions

        # Normalize fraud risk level values to uppercase
        conditions_to_save = _normalize_fraud_rule_conditions(conditions_to_save)

        validated_store_ids = _validate_store_ids_for_user(
            db, current_user.id, rule_data.store_ids or []
        )

        db_rule = FraudDetectionRule(
            user_id=current_user.id,
            name=rule_data.name,
            description=rule_data.description,
            conditions=conditions_to_save,
            actions=[action.dict() for action in rule_data.actions],
            priority=rule_data.priority,
            delay_ms=rule_data.delay_ms,
            is_active=rule_data.is_active
        )
        db.add(db_rule)
        db.flush()  # obtain db_rule.id without committing yet

        for sid in validated_store_ids:
            db.add(FraudRuleStore(fraud_rule_id=db_rule.id, store_id=sid))

        db.commit()
        db.refresh(db_rule)

        logger.info(
            f"Created fraud detection rule '{rule_data.name}' for user {current_user.id} "
            f"(stores={validated_store_ids or 'all'})"
        )

        return _serialize_fraud_rule(db_rule)

    except Exception as e:
        logger.error(f"Error creating fraud rule: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create fraud rule: {str(e)}"
        )


@router.get("/fraud-rules", response_model=List[FraudRuleResponse])
async def get_fraud_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all fraud detection rules for the current user"""
    try:
        rules = (
            db.query(FraudDetectionRule)
            .options(selectinload(FraudDetectionRule.applicable_stores))
            .filter(FraudDetectionRule.user_id == current_user.id)
            .order_by(FraudDetectionRule.priority.asc())
            .all()
        )

        return [_serialize_fraud_rule(rule) for rule in rules]

    except Exception as e:
        logger.error(f"Error fetching fraud rules: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch fraud rules: {str(e)}"
        )


@router.get("/fraud-rules/schema")
async def get_fraud_rule_schema(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get available fields, operators, and actions for fraud rule creation"""
    try:
        from rule_engine import RuleEngine
        engine = RuleEngine()

        # Get user's duplicate detection days setting
        user_settings = db.query(Settings).filter(Settings.user_id == current_user.id).first()
        duplicate_detection_days = user_settings.duplicate_detection_days if user_settings else 7

        # Get fraud-specific fields for rule conditions
        fraud_fields = [
            {"field": "first_time_customer", "label": "First Time Customer", "type": "boolean"},
            {"field": "order_total", "label": "Order Total", "type": "number"},
            {"field": "fraud_order_total_multiple", "label": "Order Total Multiple (vs Previous Order)", "type": "number"},
            {"field": "transaction_attempts", "label": "Transaction Attempts", "type": "number"},
            {"field": "customer_name", "label": "Customer Name", "type": "string"},
            {"field": "duplicate_within_7days", "label": f"Duplicate Within {duplicate_detection_days} Days", "type": "boolean"},
            {"field": "previous_order_delivery_status", "label": "Previous Order Delivery Status", "type": "string"},
            {"field": "previous_order_total", "label": "Previous Order Total", "type": "number"},
            {"field": "current_order_total", "label": "Current Order Total", "type": "number"},
            {"field": "fraud_risk_level", "label": "Shopify Fraud Risk Level", "type": "string"},
            {"field": "customer_notes", "label": "Customer Notes", "type": "string"},
            {"field": "billing_outside_us", "label": "Billing Address Outside US", "type": "boolean"},
            {"field": "same_billing_shipping", "label": "Same Billing & Shipping", "type": "boolean"},
            {"field": "shipping_state", "label": "Shipping State", "type": "string"},
            {"field": "days_since_last_delivery", "label": "Days Since Last Delivery", "type": "number"},
            {"field": "previous_order_cancelled", "label": "Previous Order Cancelled", "type": "boolean"},
            {"field": "customer_total_orders", "label": "Customer Total Orders", "type": "number"}
        ]

        # Get fraud-specific operators
        fraud_operators = [
            {"operator": "equals", "label": "Equals", "types": ["string", "number", "boolean"]},
            {"operator": "not_equals", "label": "Not Equals", "types": ["string", "number", "boolean"]},
            {"operator": "greater_than", "label": "Greater Than", "types": ["number"]},
            {"operator": "less_than", "label": "Less Than", "types": ["number"]},
            {"operator": "greater_than_or_equal", "label": "Greater Than or Equal", "types": ["number"]},
            {"operator": "less_than_or_equal", "label": "Less Than or Equal", "types": ["number"]},
            {"operator": "multiple_greater_than", "label": "Multiple Greater Than", "types": ["number"]},
            {"operator": "contains", "label": "Contains", "types": ["string"]},
            {"operator": "not_contains", "label": "Does Not Contain", "types": ["string"]},
            {"operator": "starts_with", "label": "Starts With", "types": ["string"]},
            {"operator": "ends_with", "label": "Ends With", "types": ["string"]},
            {"operator": "in_list", "label": "In List", "types": ["string"]},
            {"operator": "not_in_list", "label": "Not In List", "types": ["string"]},
            {"operator": "is_empty", "label": "Is Empty", "types": ["string"]},
            {"operator": "is_not_empty", "label": "Is Not Empty", "types": ["string"]},
            {"operator": "risk_level_equals", "label": "Risk Level Equals", "types": ["string"]},
            {"operator": "delivery_status_contains", "label": "Delivery Status Contains", "types": ["string"]},
            {"operator": "fraud_ratio_greater_than", "label": "Ratio Greater Than", "types": ["number"]},
            {"operator": "fraud_ratio_less_than", "label": "Ratio Less Than", "types": ["number"]}
        ]

        # Get fraud-specific action types
        fraud_actions = [
            {"type": "do_nothing", "label": "Do Nothing", "parameters": []},
            {"type": "add_tag", "label": "Add Tag", "parameters": ["tags"]},
            {"type": "remove_tag", "label": "Remove Tag", "parameters": ["tags"]},
            {"type": "place_on_hold", "label": "Place Order on Hold", "parameters": []}
        ]

        return {
            "fields": fraud_fields,
            "operators": fraud_operators,
            "action_types": fraud_actions
        }

    except Exception as e:
        logger.error(f"Error getting fraud rule schema: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fraud rule schema: {str(e)}"
        )


@router.get("/fraud-rules/{rule_id}", response_model=FraudRuleResponse)
async def get_fraud_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific fraud detection rule"""
    try:
        rule = (
            db.query(FraudDetectionRule)
            .options(selectinload(FraudDetectionRule.applicable_stores))
            .filter(
                FraudDetectionRule.id == rule_id,
                FraudDetectionRule.user_id == current_user.id,
            )
            .first()
        )

        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud rule not found"
            )

        return _serialize_fraud_rule(rule)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching fraud rule {rule_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch fraud rule: {str(e)}"
        )


@router.put("/fraud-rules/{rule_id}", response_model=FraudRuleResponse)
async def update_fraud_rule(
    rule_id: int,
    rule_data: FraudRuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing fraud detection rule"""
    try:
        rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == rule_id,
            FraudDetectionRule.user_id == current_user.id
        ).first()

        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud rule not found"
            )

        # Normalize conditions through the schema validator and convert to dict
        if hasattr(rule_data.conditions, 'dict'):
            conditions_to_save = rule_data.conditions.dict()
        else:
            conditions_to_save = rule_data.conditions

        # Normalize fraud risk level values to uppercase
        conditions_to_save = _normalize_fraud_rule_conditions(conditions_to_save)

        validated_store_ids = _validate_store_ids_for_user(
            db, current_user.id, rule_data.store_ids or []
        )

        # Update rule fields
        rule.name = rule_data.name
        rule.description = rule_data.description
        rule.conditions = conditions_to_save
        rule.actions = [action.dict() for action in rule_data.actions]
        rule.priority = rule_data.priority
        rule.delay_ms = rule_data.delay_ms
        rule.is_active = rule_data.is_active
        rule.updated_at = func.now()

        _replace_rule_store_mappings(db, rule.id, validated_store_ids)

        db.commit()
        db.refresh(rule)

        logger.info(
            f"Updated fraud detection rule '{rule_data.name}' for user {current_user.id} "
            f"(stores={validated_store_ids or 'all'})"
        )

        return _serialize_fraud_rule(rule)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating fraud rule {rule_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update fraud rule: {str(e)}"
        )


@router.delete("/fraud-rules/{rule_id}")
async def delete_fraud_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a fraud detection rule"""
    try:
        rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == rule_id,
            FraudDetectionRule.user_id == current_user.id
        ).first()

        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud rule not found"
            )

        db.delete(rule)
        db.commit()

        logger.info(f"Deleted fraud detection rule '{rule.name}' for user {current_user.id}")
        return {"message": "Fraud rule deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting fraud rule {rule_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete fraud rule: {str(e)}"
        )


@router.put("/fraud-rules/{rule_id}/toggle")
async def toggle_fraud_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Toggle the active status of a fraud detection rule"""
    try:
        rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.id == rule_id,
            FraudDetectionRule.user_id == current_user.id
        ).first()

        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fraud rule not found"
            )

        # Toggle the active status
        rule.is_active = not rule.is_active
        rule.updated_at = func.now()
        db.commit()

        status_text = "activated" if rule.is_active else "deactivated"
        logger.info(f"Fraud detection rule '{rule.name}' {status_text} for user {current_user.id}")

        return {
            "message": f"Fraud rule {status_text} successfully",
            "is_active": rule.is_active
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling fraud rule {rule_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to toggle fraud rule: {str(e)}"
        )


# Order Hold Management Endpoints
@router.get("/orders/{order_id}/fulfillment-orders")
async def get_order_fulfillment_orders(
    order_id: str,
    store_id: int = Query(..., description="Store ID to get the order from"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all fulfillment orders for a given order"""
    logger.info(f"Fulfillment orders endpoint called with order_id: '{order_id}', store_id: {store_id}")
    try:
        # Verify store ownership
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == current_user.id
        ).first()

        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )

        # URL decode the order_id in case it's encoded
        decoded_order_id = urllib.parse.unquote(order_id)
        logger.info(f"Looking up order: original='{order_id}', decoded='{decoded_order_id}'")

        # Get fulfillment orders
        client = ShopifyClient(store.shop_domain, store.access_token)
        fulfillment_orders = await client.get_fulfillment_orders_for_order(decoded_order_id)

        # If no fulfillment orders found, try to get order info for debugging
        if not fulfillment_orders:
            logger.warning(f"No fulfillment orders found for order {decoded_order_id}")
            try:
                # Try to get basic order info to see if the order exists
                order_info = await client.get_order_by_id(decoded_order_id)
                if order_info:
                    order_status = order_info.get('displayFulfillmentStatus', 'unknown')
                    financial_status = order_info.get('displayFinancialStatus', 'unknown')
                    logger.info(f"Order {decoded_order_id} exists but has no fulfillment orders. Status: {order_status}, Financial: {financial_status}")

                    # Provide specific guidance based on order status
                    if order_status == "UNFULFILLED":
                        debug_info = "Order is unfulfilled but has no fulfillment orders yet. This may be a new order - fulfillment orders are typically created automatically by Shopify within a few minutes. Try again shortly."
                    elif order_status == "FULFILLED":
                        debug_info = "Order is already fulfilled - no fulfillment orders available for holds"
                    elif order_status == "CANCELLED":
                        debug_info = "Order is cancelled - no fulfillment orders available"
                    else:
                        debug_info = f"Order exists but has no fulfillment orders (Status: {order_status})"

                    return {
                        "order_id": decoded_order_id,
                        "fulfillment_orders": [],
                        "order_exists": True,
                        "order_status": order_status,
                        "financial_status": financial_status,
                        "debug_info": debug_info
                    }
                else:
                    logger.warning(f"Order {decoded_order_id} not found in Shopify")
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Order {decoded_order_id} not found in Shopify"
                    )
            except Exception as debug_error:
                logger.error(f"Error getting order info for debugging: {str(debug_error)}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order {decoded_order_id} not found or inaccessible"
                )

        return {
            "order_id": decoded_order_id,
            "fulfillment_orders": fulfillment_orders
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fulfillment orders for order {order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fulfillment orders: {str(e)}"
        )


@router.get("/fulfillment-orders")
async def get_order_fulfillment_orders_alt(
    order_id: str = Query(..., description="Order ID to get fulfillment orders for"),
    store_id: int = Query(..., description="Store ID to get the order from"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all fulfillment orders for a given order (alternative endpoint with query params)"""
    logger.info(f"Alternative fulfillment orders endpoint called with order_id: '{order_id}', store_id: {store_id}")
    try:
        # Verify store ownership
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == current_user.id
        ).first()

        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )

        # URL decode the order_id in case it's encoded
        decoded_order_id = urllib.parse.unquote(order_id)
        logger.info(f"Looking up order: original='{order_id}', decoded='{decoded_order_id}'")

        # Get fulfillment orders
        client = ShopifyClient(store.shop_domain, store.access_token)
        fulfillment_orders = await client.get_fulfillment_orders_for_order(decoded_order_id)

        # If no fulfillment orders found, try to get order info for debugging
        if not fulfillment_orders:
            logger.warning(f"No fulfillment orders found for order {decoded_order_id}")
            try:
                # Try to get basic order info to see if the order exists
                order_info = await client.get_order_by_id(decoded_order_id)
                if order_info:
                    order_status = order_info.get('displayFulfillmentStatus', 'unknown')
                    financial_status = order_info.get('displayFinancialStatus', 'unknown')
                    logger.info(f"Order {decoded_order_id} exists but has no fulfillment orders. Status: {order_status}, Financial: {financial_status}")

                    # Provide specific guidance based on order status
                    if order_status == "UNFULFILLED":
                        debug_info = "Order is unfulfilled but has no fulfillment orders yet. This may be a new order - fulfillment orders are typically created automatically by Shopify within a few minutes. Try again shortly."
                    elif order_status == "FULFILLED":
                        debug_info = "Order is already fulfilled - no fulfillment orders available for holds"
                    elif order_status == "CANCELLED":
                        debug_info = "Order is cancelled - no fulfillment orders available"
                    else:
                        debug_info = f"Order exists but has no fulfillment orders (Status: {order_status})"

                    return {
                        "order_id": decoded_order_id,
                        "fulfillment_orders": [],
                        "order_exists": True,
                        "order_status": order_status,
                        "financial_status": financial_status,
                        "debug_info": debug_info
                    }
                else:
                    logger.warning(f"Order {decoded_order_id} not found in Shopify")
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Order {decoded_order_id} not found in Shopify"
                    )
            except Exception as debug_error:
                logger.error(f"Error getting order info for debugging: {str(debug_error)}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order {decoded_order_id} not found or inaccessible"
                )

        return {
            "order_id": decoded_order_id,
            "fulfillment_orders": fulfillment_orders
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fulfillment orders for order {order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fulfillment orders: {str(e)}"
        )


@router.post("/fulfillment-orders/{fulfillment_order_id}/hold")
async def apply_order_hold(
    fulfillment_order_id: str,
    store_id: int = Query(..., description="Store ID"),
    reason: str = Query(..., description="Hold reason (e.g., HIGH_RISK_OF_FRAUD, AWAITING_PAYMENT, etc.)"),
    reason_notes: str = Query("", description="Additional notes about the hold"),
    notify_merchant: bool = Query(True, description="Whether to notify the merchant"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Apply a hold to a fulfillment order"""
    try:
        # Verify store ownership
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == current_user.id
        ).first()

        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )

        # Validate reason
        valid_reasons = [
            "AWAITING_PAYMENT",
            "HIGH_RISK_OF_FRAUD",
            "INCORRECT_ADDRESS",
            "INVENTORY_OUT_OF_STOCK",
            "AWAITING_RETURN_ITEMS",
            "UNKNOWN_DELIVERY_DATE",
            "OTHER"
        ]

        if reason not in valid_reasons:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid hold reason. Must be one of: {', '.join(valid_reasons)}"
            )

        # Apply the hold
        client = ShopifyClient(store.shop_domain, store.access_token)
        result = await client.apply_fulfillment_hold(
            fulfillment_order_id,
            reason,
            reason_notes,
            notify_merchant
        )

        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to apply hold: {result.get('errors', 'Unknown error')}"
            )

        # Log the action
        log_entry = OrderLog(
            user_id=current_user.id,
            store_id=store.id,
            order_id=result["fulfillment_order"]["id"] if result["fulfillment_order"] else None,
            order_number=f"Fulfillment Order {fulfillment_order_id}",
            action="fulfillment_hold_applied",
            status="info",
            details={
                "fulfillment_order_id": fulfillment_order_id,
                "hold_reason": reason,
                "hold_notes": reason_notes,
                "notify_merchant": notify_merchant,
                "hold_id": result["hold"]["id"] if result["hold"] else None,
                "rule_name": "Manual Hold"
            }
        )
        db.add(log_entry)
        db.commit()

        return {
            "success": True,
            "message": f"Hold applied successfully to fulfillment order {fulfillment_order_id}",
            "fulfillment_order": result["fulfillment_order"],
            "hold": result["hold"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying hold to fulfillment order {fulfillment_order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply hold: {str(e)}"
        )


@router.post("/fulfillment-orders/{fulfillment_order_id}/release-hold")
async def release_order_hold(
    fulfillment_order_id: str,
    store_id: int = Query(..., description="Store ID"),
    hold_ids: List[str] = Query(None, description="Specific hold IDs to release (releases all if not provided)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Release a hold from a fulfillment order"""
    try:
        # Verify store ownership
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == current_user.id
        ).first()

        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )

        # Release the hold
        client = ShopifyClient(store.shop_domain, store.access_token)
        result = await client.release_fulfillment_hold(fulfillment_order_id, hold_ids)

        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to release hold: {result.get('errors', 'Unknown error')}"
            )

        # Log the action
        log_entry = OrderLog(
            user_id=current_user.id,
            store_id=store.id,
            order_id=result["fulfillment_order"]["id"] if result["fulfillment_order"] else None,
            order_number=f"Fulfillment Order {fulfillment_order_id}",
            action="fulfillment_hold_released",
            status="info",
            details={
                "fulfillment_order_id": fulfillment_order_id,
                "hold_ids": hold_ids,
                "rule_name": "Manual Hold Release"
            }
        )
        db.add(log_entry)
        db.commit()

        return {
            "success": True,
            "message": f"Hold released successfully from fulfillment order {fulfillment_order_id}",
            "fulfillment_order": result["fulfillment_order"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error releasing hold from fulfillment order {fulfillment_order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to release hold: {str(e)}"
        )


@router.post("/fulfillment-order-hold")
async def apply_order_hold_query(
    fulfillment_order_id: str = Query(..., description="Fulfillment Order ID (Shopify GID)"),
    store_id: int = Query(..., description="Store ID"),
    reason: str = Query(..., description="Hold reason (e.g., HIGH_RISK_OF_FRAUD, AWAITING_PAYMENT, etc.)"),
    reason_notes: str = Query("", description="Additional notes about the hold"),
    notify_merchant: bool = Query(True, description="Whether to notify the merchant"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Apply a hold to a fulfillment order using query parameters to avoid URL encoding issues with Shopify GIDs"""
    try:
        # Verify store ownership
        store = db.query(ShopifyStore).filter(
            ShopifyStore.id == store_id,
            ShopifyStore.user_id == current_user.id
        ).first()

        if not store:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Store not found"
            )

        # Validate reason
        valid_reasons = [
            "AWAITING_PAYMENT",
            "HIGH_RISK_OF_FRAUD",
            "INCORRECT_ADDRESS",
            "INVENTORY_OUT_OF_STOCK",
            "AWAITING_RETURN_ITEMS",
            "UNKNOWN_DELIVERY_DATE",
            "OTHER"
        ]

        if reason not in valid_reasons:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid hold reason. Must be one of: {', '.join(valid_reasons)}"
            )

        # Apply the hold
        client = ShopifyClient(store.shop_domain, store.access_token)
        result = await client.apply_fulfillment_hold(
            fulfillment_order_id,
            reason,
            reason_notes,
            notify_merchant
        )

        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to apply hold: {result.get('errors', 'Unknown error')}"
            )

        # Log the action
        log_entry = OrderLog(
            user_id=current_user.id,
            store_id=store.id,
            order_id=result["fulfillment_order"]["id"] if result["fulfillment_order"] else None,
            order_number=f"Fulfillment Order {fulfillment_order_id}",
            action="fulfillment_hold_applied",
            status="info",
            details={
                "fulfillment_order_id": fulfillment_order_id,
                "hold_reason": reason,
                "hold_notes": reason_notes,
                "notify_merchant": notify_merchant,
                "hold_id": result["hold"]["id"] if result["hold"] else None,
                "rule_name": "Manual Hold"
            }
        )
        db.add(log_entry)
        db.commit()

        return {
            "success": True,
            "message": f"Hold applied successfully to fulfillment order {fulfillment_order_id}",
            "fulfillment_order": result["fulfillment_order"],
            "hold": result["hold"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying hold to fulfillment order {fulfillment_order_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to apply hold: {str(e)}"
        )
