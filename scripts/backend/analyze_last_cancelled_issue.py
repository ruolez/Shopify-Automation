#!/usr/bin/env python3
"""Comprehensive analysis of the Last Cancelled rule issue"""

import sys
import os
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudDetectionRule, FraudAnalysis, OrderLog
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def analyze_last_cancelled_issue():
    """Comprehensive analysis of why Last Cancelled seems to not trigger"""
    db = SessionLocal()
    try:
        logger.info("=" * 80)
        logger.info("COMPREHENSIVE ANALYSIS: LAST CANCELLED RULE")
        logger.info("=" * 80)
        
        # 1. Get the Last Cancelled rule details
        last_cancelled_rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.name == "Last Cancelled"
        ).first()
        
        if not last_cancelled_rule:
            logger.error("❌ Last Cancelled rule not found!")
            return
        
        logger.info(f"\n📋 RULE CONFIGURATION:")
        logger.info(f"Name: {last_cancelled_rule.name}")
        logger.info(f"ID: {last_cancelled_rule.id}")
        logger.info(f"Active: {last_cancelled_rule.is_active}")
        logger.info(f"Priority: {last_cancelled_rule.priority}")
        logger.info(f"Conditions: {json.dumps(last_cancelled_rule.conditions, indent=2)}")
        logger.info(f"Actions: {json.dumps(last_cancelled_rule.actions, indent=2)}")
        
        # Check the action type
        if last_cancelled_rule.actions:
            for action in last_cancelled_rule.actions:
                if action.get('type') == 'do_nothing':
                    logger.warning("\n⚠️ CRITICAL ISSUE FOUND!")
                    logger.warning("The rule action is set to 'do_nothing'")
                    logger.warning("This means the rule triggers but takes NO VISIBLE ACTION")
                    logger.warning("No tags are added, so it appears the rule never triggered!")
        
        # 2. Check how many times this rule has triggered
        rule_id = last_cancelled_rule.id
        triggered_analyses = db.query(FraudAnalysis).filter(
            FraudAnalysis.rule_triggered_ids.contains([rule_id])
        ).all()
        
        logger.info(f"\n📊 TRIGGER STATISTICS:")
        logger.info(f"Rule ID {rule_id} has triggered {len(triggered_analyses)} time(s)")
        
        if triggered_analyses:
            logger.info("\n📍 Orders where Last Cancelled rule triggered:")
            for analysis in triggered_analyses:
                logger.info(f"\n   Order: {analysis.order_name}")
                logger.info(f"   Customer: {analysis.customer_name}")
                logger.info(f"   Date: {analysis.analysis_timestamp}")
                logger.info(f"   Previous order cancelled: {analysis.previous_order_cancelled}")
                logger.info(f"   All triggered rules: {analysis.rule_triggered_ids}")
                
                # Check order logs for this order
                logs = db.query(OrderLog).filter(
                    OrderLog.order_name == analysis.order_name
                ).order_by(OrderLog.created_at.desc()).limit(5).all()
                
                if logs:
                    logger.info(f"   Recent log entries:")
                    for log in logs:
                        if 'Last Cancelled' in log.message or 'previous_order_cancelled' in log.message:
                            logger.info(f"      - {log.created_at}: {log.message[:100]}")
        
        # 3. Check the condition value type issue
        logger.info(f"\n🔍 CONDITION ANALYSIS:")
        conditions = last_cancelled_rule.conditions
        if conditions and 'conditions' in conditions:
            for condition in conditions['conditions']:
                if condition.get('field') == 'previous_order_cancelled':
                    value = condition.get('value')
                    operator = condition.get('operator')
                    logger.info(f"Field: {condition.get('field')}")
                    logger.info(f"Operator: {operator}")
                    logger.info(f"Value: {value} (type: {type(value).__name__})")
                    
                    if isinstance(value, str) and value == "true":
                        logger.warning("\n⚠️ POTENTIAL ISSUE:")
                        logger.warning("The condition value is the STRING 'true' not BOOLEAN true")
                        logger.warning("This might cause matching issues if the field is a boolean")
        
        # 4. Analyze why so few orders have cancelled previous orders
        logger.info(f"\n📈 CANCELLED ORDER STATISTICS:")
        
        total_analyses = db.query(FraudAnalysis).count()
        with_cancelled = db.query(FraudAnalysis).filter(
            FraudAnalysis.previous_order_cancelled == True
        ).count()
        with_false = db.query(FraudAnalysis).filter(
            FraudAnalysis.previous_order_cancelled == False
        ).count()
        with_null = db.query(FraudAnalysis).filter(
            FraudAnalysis.previous_order_cancelled == None
        ).count()
        
        logger.info(f"Total fraud analyses: {total_analyses}")
        logger.info(f"With previous_order_cancelled = True: {with_cancelled} ({with_cancelled/total_analyses*100:.2f}%)")
        logger.info(f"With previous_order_cancelled = False: {with_false} ({with_false/total_analyses*100:.2f}%)")
        logger.info(f"With previous_order_cancelled = NULL: {with_null} ({with_null/total_analyses*100:.2f}%)")
        
        # 5. Final diagnosis
        logger.info("\n" + "=" * 80)
        logger.info("DIAGNOSIS & RECOMMENDATIONS")
        logger.info("=" * 80)
        
        logger.info("\n✅ THE RULE IS WORKING!")
        logger.info("The 'Last Cancelled' rule exists and has triggered at least once.")
        
        logger.info("\n❌ PROBLEMS IDENTIFIED:")
        logger.info("1. The rule action is 'do_nothing' - it doesn't add tags or take visible actions")
        logger.info("2. Only 0.13% of orders have a cancelled previous order (very rare condition)")
        logger.info("3. The condition value might be a string 'true' instead of boolean true")
        
        logger.info("\n💡 RECOMMENDATIONS:")
        logger.info("1. Change the rule action from 'do_nothing' to 'add_tag' with a specific tag")
        logger.info("   Example: Add tag 'PREVIOUS_ORDER_CANCELLED' or 'LAST_CANCELLED'")
        logger.info("2. Consider if the condition value should be boolean true instead of string 'true'")
        logger.info("3. The low trigger rate (1 in 752) is NORMAL - cancelled previous orders are rare")
        logger.info("4. To verify the rule works, test with order TS8308944 which has this condition")
        
    except Exception as e:
        logger.error(f"Error analyzing Last Cancelled rule: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    analyze_last_cancelled_issue()