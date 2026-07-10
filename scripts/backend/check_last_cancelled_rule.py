#!/usr/bin/env python3
"""Check for Last Cancelled rule in the database and analyze fraud analyses"""

import sys
import os
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudDetectionRule, FraudAnalysis, ShopifyStore
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_last_cancelled_rule():
    """Check for Last Cancelled rule and analyze its configuration"""
    db = SessionLocal()
    try:
        logger.info("=" * 80)
        logger.info("CHECKING FOR 'LAST CANCELLED' FRAUD RULE")
        logger.info("=" * 80)
        
        # 1. Look for any rule with "Last Cancelled" in the name
        rules = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.name.ilike('%last%cancel%')
        ).all()
        
        if rules:
            logger.info(f"\n✅ Found {len(rules)} rule(s) with 'Last Cancelled' in name:")
            for rule in rules:
                logger.info(f"\n📋 Rule: {rule.name}")
                logger.info(f"   ID: {rule.id}")
                logger.info(f"   Active: {rule.is_active}")
                logger.info(f"   User ID: {rule.user_id if hasattr(rule, 'user_id') else 'N/A'}")
                logger.info(f"   Priority: {rule.priority}")
                logger.info(f"   Conditions: {json.dumps(rule.conditions, indent=2) if rule.conditions else 'None'}")
                logger.info(f"   Actions: {json.dumps(rule.actions, indent=2) if rule.actions else 'None'}")
                
                # Check if the condition is looking for previous_order_cancelled
                conditions_str = str(rule.conditions) if rule.conditions else ""
                if 'previous_order_cancelled' in conditions_str:
                    logger.info("   ✅ Rule checks for previous_order_cancelled field")
                else:
                    logger.warning("   ⚠️ Rule does NOT check for previous_order_cancelled field")
        else:
            logger.warning("\n❌ No rules found with 'Last Cancelled' in the name")
        
        # 2. Look for any rule checking previous_order_cancelled field
        logger.info("\n" + "=" * 80)
        logger.info("CHECKING FOR RULES WITH previous_order_cancelled CONDITION")
        logger.info("=" * 80)
        
        all_rules = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.is_active == True
        ).all()
        
        rules_with_cancelled_check = []
        for rule in all_rules:
            if rule.conditions:
                conditions_str = str(rule.conditions)
                if 'previous_order_cancelled' in conditions_str:
                    rules_with_cancelled_check.append(rule)
        
        if rules_with_cancelled_check:
            logger.info(f"\n✅ Found {len(rules_with_cancelled_check)} active rule(s) checking previous_order_cancelled:")
            for rule in rules_with_cancelled_check:
                logger.info(f"\n📋 Rule: {rule.name}")
                logger.info(f"   User ID: {rule.user_id if hasattr(rule, 'user_id') else 'N/A'}")
                logger.info(f"   Conditions: {json.dumps(rule.conditions, indent=2)}")
        else:
            logger.warning("\n❌ No active rules found checking previous_order_cancelled field")
        
        # 3. Check how many fraud analyses have previous_order_cancelled = True
        logger.info("\n" + "=" * 80)
        logger.info("CHECKING FRAUD ANALYSES WITH CANCELLED PREVIOUS ORDERS")
        logger.info("=" * 80)
        
        total_analyses = db.query(FraudAnalysis).count()
        cancelled_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.previous_order_cancelled == True
        ).count()
        
        logger.info(f"\n📊 Fraud Analysis Statistics:")
        logger.info(f"   Total analyses: {total_analyses}")
        logger.info(f"   With previous order cancelled: {cancelled_analyses}")
        logger.info(f"   Percentage: {(cancelled_analyses/total_analyses*100) if total_analyses > 0 else 0:.2f}%")
        
        # 4. Show some examples of cancelled previous orders
        if cancelled_analyses > 0:
            logger.info("\n📍 Sample orders with previous order cancelled:")
            samples = db.query(FraudAnalysis).filter(
                FraudAnalysis.previous_order_cancelled == True
            ).limit(5).all()
            
            for sample in samples:
                logger.info(f"   - Order: {sample.order_name}")
                logger.info(f"     Customer: {sample.customer_name}")
                logger.info(f"     Analysis date: {sample.analysis_timestamp}")
                logger.info(f"     Rules triggered: {sample.rule_triggered_ids}")
                
                # Check if any rules were triggered for this order
                if sample.rule_triggered_ids:
                    logger.info(f"     ✅ Rules were triggered for this order")
                else:
                    logger.info(f"     ❌ No rules were triggered for this order")
        
        # 5. Check if the rule would match if it exists
        logger.info("\n" + "=" * 80)
        logger.info("ANALYSIS SUMMARY")
        logger.info("=" * 80)
        
        if not rules and not rules_with_cancelled_check:
            logger.info("\n⚠️ NO 'Last Cancelled' RULE FOUND!")
            logger.info("This explains why the rule never triggered in 1800 orders.")
            logger.info("\nPOSSIBLE REASONS:")
            logger.info("1. The rule was never created")
            logger.info("2. The rule was created with a different name")
            logger.info("3. The rule exists but is not active")
            logger.info("4. The rule exists but has incorrect conditions")
            
            logger.info("\n💡 SUGGESTION:")
            logger.info("Create a fraud detection rule with:")
            logger.info('   Name: "Last Cancelled"')
            logger.info('   Condition: {"all": [{"field": "previous_order_cancelled", "operator": "equals", "value": true}]}')
            logger.info('   Action: Add tag "PREVIOUS_ORDER_CANCELLED" or similar')
        
        elif cancelled_analyses == 0:
            logger.info("\n⚠️ No orders found with previous_order_cancelled = True")
            logger.info("This could mean:")
            logger.info("1. The fraud analysis is not detecting cancelled orders correctly")
            logger.info("2. There genuinely are no orders with cancelled previous orders")
            logger.info("3. The field is not being populated during analysis")
        
        else:
            logger.info(f"\n✅ Found {cancelled_analyses} orders with cancelled previous orders")
            logger.info("But they may not be triggering rules due to:")
            logger.info("1. Rule conditions not properly configured")
            logger.info("2. Rule not active for the correct stores")
            logger.info("3. Rule priority conflicts with other rules")
        
    except Exception as e:
        logger.error(f"Error checking Last Cancelled rule: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    check_last_cancelled_rule()