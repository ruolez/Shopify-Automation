#!/usr/bin/env python3
"""Test if the type mismatch between string 'true' and boolean True prevents rule triggering"""

import sys
import os
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import FraudDetectionRule, FraudAnalysis
from rule_engine import RuleEngine
from fraud_rule_processor import FraudRuleProcessor
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_type_mismatch():
    """Test if the type mismatch prevents rule triggering"""
    db = SessionLocal()
    try:
        logger.info("=" * 80)
        logger.info("TESTING TYPE MISMATCH: STRING 'true' vs BOOLEAN True")
        logger.info("=" * 80)
        
        # 1. Get the Last Cancelled rule
        last_cancelled_rule = db.query(FraudDetectionRule).filter(
            FraudDetectionRule.name == "Last Cancelled"
        ).first()
        
        if not last_cancelled_rule:
            logger.error("Last Cancelled rule not found!")
            return
            
        logger.info(f"\n📋 Current Rule Configuration:")
        logger.info(f"Rule ID: {last_cancelled_rule.id}")
        logger.info(f"Conditions: {json.dumps(last_cancelled_rule.conditions, indent=2)}")
        
        # Extract the condition value and its type
        condition_value = None
        if last_cancelled_rule.conditions and 'conditions' in last_cancelled_rule.conditions:
            for cond in last_cancelled_rule.conditions['conditions']:
                if cond.get('field') == 'previous_order_cancelled':
                    condition_value = cond.get('value')
                    logger.info(f"\n🔍 Condition Analysis:")
                    logger.info(f"   Field: {cond.get('field')}")
                    logger.info(f"   Operator: {cond.get('operator')}")
                    logger.info(f"   Value: {condition_value}")
                    logger.info(f"   Value Type: {type(condition_value).__name__}")
                    logger.info(f"   Is String: {isinstance(condition_value, str)}")
                    logger.info(f"   Is Boolean: {isinstance(condition_value, bool)}")
        
        # 2. Get the fraud analysis for order TS8308944 (which has previous_order_cancelled = True)
        fraud_analysis = db.query(FraudAnalysis).filter(
            FraudAnalysis.order_name == "TS8308944"
        ).first()
        
        if fraud_analysis:
            logger.info(f"\n📊 Test Order TS8308944:")
            logger.info(f"   previous_order_cancelled DB value: {fraud_analysis.previous_order_cancelled}")
            logger.info(f"   Type: {type(fraud_analysis.previous_order_cancelled).__name__}")
            logger.info(f"   Rules triggered: {fraud_analysis.rule_triggered_ids}")
            
            # 3. Test the rule evaluation with actual data
            rule_engine = RuleEngine(db)
            processor = FraudRuleProcessor(db, None, None, None)
            
            # Convert fraud analysis to rule data
            rule_data = processor._convert_fraud_analysis_to_rule_data(fraud_analysis)
            
            logger.info(f"\n🔄 Converted Rule Data:")
            logger.info(f"   previous_order_cancelled value: {rule_data.get('previous_order_cancelled')}")
            logger.info(f"   Type: {type(rule_data.get('previous_order_cancelled')).__name__}")
            
            # 4. Test rule evaluation
            logger.info(f"\n🧪 Testing Rule Evaluation:")
            
            # Test with current configuration
            matched = rule_engine.evaluate_rule(last_cancelled_rule, rule_data)
            logger.info(f"\n   Test 1 - Current Configuration:")
            logger.info(f"   Rule condition: string '{condition_value}'")
            logger.info(f"   Data value: boolean {rule_data.get('previous_order_cancelled')}")
            logger.info(f"   Result: {'✅ MATCHED' if matched else '❌ NOT MATCHED'}")
            
            # Create test scenarios
            test_scenarios = [
                {"value": True, "desc": "Boolean True"},
                {"value": False, "desc": "Boolean False"},
                {"value": "true", "desc": "String 'true'"},
                {"value": "false", "desc": "String 'false'"},
                {"value": 1, "desc": "Integer 1"},
                {"value": 0, "desc": "Integer 0"},
                {"value": None, "desc": "None/Null"}
            ]
            
            logger.info(f"\n🧪 Testing Different Data Values Against Rule:")
            logger.info(f"   Rule expects: {condition_value} (type: {type(condition_value).__name__})")
            
            for scenario in test_scenarios:
                test_data = rule_data.copy()
                test_data['previous_order_cancelled'] = scenario['value']
                
                # Evaluate with test data
                matched = rule_engine.evaluate_rule(last_cancelled_rule, test_data)
                logger.info(f"\n   {scenario['desc']}:")
                logger.info(f"      Value: {scenario['value']}")
                logger.info(f"      Type: {type(scenario['value']).__name__ if scenario['value'] is not None else 'NoneType'}")
                logger.info(f"      Result: {'✅ MATCHED' if matched else '❌ NOT MATCHED'}")
            
            # 5. Check how the rule engine handles the comparison
            logger.info(f"\n🔬 Rule Engine Comparison Logic:")
            
            # Look at the specific condition evaluation
            if last_cancelled_rule.conditions and 'conditions' in last_cancelled_rule.conditions:
                for condition in last_cancelled_rule.conditions['conditions']:
                    if condition.get('field') == 'previous_order_cancelled':
                        # Test the actual comparison logic
                        field_value = rule_data.get('previous_order_cancelled')
                        condition_value = condition.get('value')
                        operator = condition.get('operator')
                        
                        logger.info(f"   Field value: {field_value} (type: {type(field_value).__name__})")
                        logger.info(f"   Condition value: {condition_value} (type: {type(condition_value).__name__})")
                        logger.info(f"   Operator: {operator}")
                        
                        # Test different comparison approaches
                        logger.info(f"\n   Comparison Tests:")
                        logger.info(f"      Direct equality (==): {field_value == condition_value}")
                        logger.info(f"      String comparison: {str(field_value).lower() == str(condition_value).lower()}")
                        logger.info(f"      Boolean comparison: {bool(field_value) == bool(condition_value == 'true')}")
                        
                        # Check if 5 is in rule_triggered_ids
                        if fraud_analysis.rule_triggered_ids and 5 in fraud_analysis.rule_triggered_ids:
                            logger.info(f"\n   ✅ Rule ID 5 IS in triggered rules list!")
                            logger.info(f"   This confirms the rule DID trigger despite type mismatch")
                        else:
                            logger.info(f"\n   ❌ Rule ID 5 is NOT in triggered rules list")
        
        # 6. Final diagnosis
        logger.info("\n" + "=" * 80)
        logger.info("DIAGNOSIS")
        logger.info("=" * 80)
        
        if fraud_analysis and fraud_analysis.rule_triggered_ids and 5 in fraud_analysis.rule_triggered_ids:
            logger.info("\n✅ GOOD NEWS: The rule IS triggering despite the type mismatch!")
            logger.info("The rule engine must be handling the type conversion internally.")
            logger.info("The string 'true' is being compared successfully with boolean True.")
        else:
            logger.info("\n⚠️ The type mismatch might be preventing the rule from triggering.")
            logger.info("Consider changing the condition value from string 'true' to boolean true.")
        
    except Exception as e:
        logger.error(f"Error testing type mismatch: {str(e)}", exc_info=True)
    finally:
        db.close()

if __name__ == "__main__":
    test_type_mismatch()