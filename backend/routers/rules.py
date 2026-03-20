"""Processing rules management endpoints"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional

from database import get_db
from models import User, ProcessingRule
from auth import get_current_user
from schemas import RuleCreate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rules", tags=["Rules"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_rule(
    rule_data: RuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Normalize conditions through the schema validator and convert to dict
    # rule_data.conditions is already normalized to dict format by the validator
    if hasattr(rule_data.conditions, 'dict'):
        conditions_to_save = rule_data.conditions.dict()
    else:
        conditions_to_save = rule_data.conditions

    db_rule = ProcessingRule(
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
    db.commit()
    db.refresh(db_rule)

    return {
        "id": db_rule.id,
        "name": db_rule.name,
        "description": db_rule.description,
        "conditions": db_rule.conditions,
        "actions": db_rule.actions,
        "priority": db_rule.priority,
        "delay_ms": db_rule.delay_ms,
        "is_active": db_rule.is_active,
        "created_at": db_rule.created_at
    }


@router.get("")
async def get_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rules = db.query(ProcessingRule).filter(ProcessingRule.user_id == current_user.id).order_by(ProcessingRule.priority.asc()).all()
    return [
        {
            "id": rule.id,
            "name": rule.name,
            "description": rule.description,
            "conditions": rule.conditions,
            "actions": rule.actions,
            "priority": rule.priority,
            "delay_ms": rule.delay_ms,
            "is_active": rule.is_active,
            "created_at": rule.created_at
        }
        for rule in rules
    ]


@router.get("/schema")
async def get_rule_schema(current_user: User = Depends(get_current_user)):
    """Get available fields and operators for rule creation"""
    from rule_engine import RuleEngine
    engine = RuleEngine()

    return {
        "fields": engine.get_available_fields(),
        "operators": engine.get_available_operators(),
        "action_types": [
            {"type": "add_tag", "label": "Add Tag", "parameters": ["tags"]},
            {"type": "remove_tag", "label": "Remove Tag", "parameters": ["tags"]},
            {"type": "set_fulfillment_location", "label": "Set Fulfillment Location", "parameters": ["location_id"]}
        ]
    }


@router.get("/{rule_id}")
async def get_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rule = db.query(ProcessingRule).filter(
        ProcessingRule.id == rule_id,
        ProcessingRule.user_id == current_user.id
    ).first()

    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found"
        )

    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "conditions": rule.conditions,
        "actions": rule.actions,
        "priority": rule.priority,
        "delay_ms": rule.delay_ms,
        "is_active": rule.is_active,
        "created_at": rule.created_at
    }


@router.put("/{rule_id}")
async def update_rule(
    rule_id: int,
    rule_data: RuleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rule = db.query(ProcessingRule).filter(
        ProcessingRule.id == rule_id,
        ProcessingRule.user_id == current_user.id
    ).first()

    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found"
        )

    rule.name = rule_data.name
    rule.description = rule_data.description
    # Normalize conditions through the schema validator and convert to dict
    if hasattr(rule_data.conditions, 'dict'):
        rule.conditions = rule_data.conditions.dict()
    else:
        rule.conditions = rule_data.conditions
    rule.actions = [action.dict() for action in rule_data.actions]
    rule.priority = rule_data.priority
    rule.delay_ms = rule_data.delay_ms
    rule.is_active = rule_data.is_active

    db.commit()
    db.refresh(rule)

    return {
        "id": rule.id,
        "name": rule.name,
        "description": rule.description,
        "conditions": rule.conditions,
        "actions": rule.actions,
        "priority": rule.priority,
        "delay_ms": rule.delay_ms,
        "is_active": rule.is_active,
        "created_at": rule.created_at
    }


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    rule = db.query(ProcessingRule).filter(
        ProcessingRule.id == rule_id,
        ProcessingRule.user_id == current_user.id
    ).first()

    if not rule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rule not found"
        )

    db.delete(rule)
    db.commit()
    return {"message": "Rule deleted successfully"}


@router.put("/bulk/activate")
async def bulk_activate_rules(
    rule_ids: Optional[List[int]] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id
    )
    if rule_ids:
        query = query.filter(ProcessingRule.id.in_(rule_ids))

    updated = query.update({"is_active": True}, synchronize_session=False)
    db.commit()
    return {"message": f"Activated {updated} rules"}


@router.put("/bulk/deactivate")
async def bulk_deactivate_rules(
    rule_ids: Optional[List[int]] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(ProcessingRule).filter(
        ProcessingRule.user_id == current_user.id
    )
    if rule_ids:
        query = query.filter(ProcessingRule.id.in_(rule_ids))

    updated = query.update({"is_active": False}, synchronize_session=False)
    db.commit()
    return {"message": f"Deactivated {updated} rules"}
