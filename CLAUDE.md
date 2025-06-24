# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Shopify Multi-Store Order Management System - a comprehensive automated order processing and tagging system with a modern UI and background processing capabilities. The system allows users to connect multiple Shopify stores, create complex automation rules, and process orders automatically based on conditions like weight, shipping location, product types, etc.

## Architecture

### Core Components

**Backend (FastAPI + SQLAlchemy + Celery)**
- `backend/main.py` - FastAPI application with REST endpoints and debugging endpoints
- `backend/models.py` - SQLAlchemy models (User, ShopifyStore, ProcessingRule, OrderLog, Settings, ProcessedOrder)
- `backend/rule_engine.py` - Rule evaluation engine with 15+ operators and field extraction
- `backend/tasks.py` - Celery background tasks for order processing and store synchronization
- `backend/shopify_client.py` - Shopify Admin API GraphQL client with order management and fulfillment operations
- `backend/database.py` - Database configuration and session management
- `backend/auth.py` - JWT authentication and user management

**Frontend (React + TypeScript + Tailwind)**
- `frontend/src/pages/` - Main application pages (Dashboard, Stores, Rules, RuleBuilder, Settings, OrderLogs)
- `frontend/src/components/` - Reusable UI components
- `frontend/src/contexts/AuthContext.tsx` - Authentication state management
- `frontend/src/utils/api.ts` - Axios API client with interceptors

**Infrastructure**
- 6 Docker services: redis, api, worker, scheduler, frontend, nginx
- SQLite database with volume persistence
- Redis for Celery task queue and caching
- Nginx reverse proxy for production

### Key Data Flow

1. **Order Sync**: Celery scheduler triggers `process_all_orders_if_enabled` every 5-10 minutes based on user settings
2. **Rule Processing**: For each new order, `RuleEngine.evaluate_rule()` checks conditions, then `_apply_rule_actions()` executes actions
3. **Action Types**: `add_tag`, `remove_tag`, `set_fulfillment_location` (with GraphQL mutations)
4. **Deduplication**: `ProcessedOrder` table prevents duplicate processing of same order
5. **Logging**: All actions logged to `OrderLog` table for user visibility

### Rule Engine Architecture

The rule engine supports complex conditional logic:
- **Conditions**: 15+ field types (order_total, shipping_province, product_types, etc.) with operators (equals, contains, greater_than, etc.)
- **Logical Operators**: AND/OR grouping of conditions
- **Field Extraction**: Handles nested GraphQL response structures from Shopify API
- **Action Processing**: Sequential execution of multiple actions per rule

## Common Development Commands

### Full Application
```bash
# Start all services
docker-compose up -d

# View logs for all services
docker-compose logs -f

# Restart specific service
docker-compose restart api
docker-compose restart worker
```

### Backend Development
```bash
# Start backend services only
docker-compose up -d redis api worker scheduler

# Run backend locally for development
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run backend tests
cd backend
pytest

# Access database via container
docker exec shopify_api python -c "from database import engine; print('DB accessible')"
```

### Frontend Development
```bash
# Start backend services then run frontend locally
docker-compose up -d redis api worker scheduler
cd frontend
npm install
npm run dev

# Build for production
npm run build

# Run tests
npm test
npm run test:coverage

# Lint code
npm run lint
```

### Debugging & Troubleshooting

**Database Issues**
```bash
# Check if tables exist
docker exec shopify_api python -c "
from database import Base, engine
Base.metadata.create_all(bind=engine)
print('Tables created')
"
```

**Fulfillment Location Debugging** (Key debugging endpoints added)
```bash
# Get available locations for store
curl "http://localhost:8000/debug/locations/1" -H "Authorization: Bearer TOKEN"

# Check recent orders with fulfillment details  
curl "http://localhost:8000/debug/orders/1" -H "Authorization: Bearer TOKEN"

# Test rule against specific order
curl -X POST "http://localhost:8000/debug/test-rule/1/1?order_name=TS1395" -H "Authorization: Bearer TOKEN"

# Manually test fulfillment move
curl -X POST "http://localhost:8000/debug/move-fulfillment?store_id=1&order_name=TS1395&location_id=gid://shopify/Location/123" -H "Authorization: Bearer TOKEN"
```

**Task Queue Debugging**
```bash
# Check worker logs for processing
docker-compose logs worker --tail=50

# Monitor Celery tasks
docker exec shopify_worker celery -A tasks.celery inspect active

# Test Celery connection
docker exec shopify_api python -c "from tasks import test_celery_connection; test_celery_connection.delay()"
```

## Critical Implementation Details

### Shopify GraphQL Integration
- Uses Admin API 2025-04 with proper GraphQL global IDs (`gid://shopify/Location/123`)
- Fulfillment location changes require orders in "open" or "scheduled" status
- Order fetching includes nested structures: `fulfillmentOrders.edges.node.assignedLocation.location`
- Pagination handled with cursor-based navigation

### Rule Processing Safeguards
- `ProcessedOrder` table with unique constraint prevents duplicate processing
- Rules processed by priority (higher numbers first) for proper override behavior
- Failed actions don't block subsequent actions in same rule
- Extensive logging in `OrderLog` for debugging and user visibility

### Background Processing Architecture
- `process_all_orders_if_enabled` checks user settings before queuing store-specific tasks
- Dynamic scheduling: sync frequency adjustable per user (5-60+ minutes)
- Worker concurrency: 4 processes, horizontally scalable
- Task retry logic with error logging for Shopify API failures

### Database Schema Key Points
- User-scoped data isolation (all major tables have `user_id` foreign key)
- JSON columns for flexible rule conditions/actions storage
- Cascade delete relationships prevent orphaned data
- Settings table for per-user sync preferences

### Authentication Flow
- JWT tokens with configurable expiration
- FastAPI Depends() injection for protected endpoints
- Frontend axios interceptors for automatic token refresh
- User registration/login with bcrypt password hashing

This system handles complex real-time order processing with proper error handling, logging, and user isolation - critical for production Shopify automation.

## Critical Bug Fixes & Known Issues

### Weight Filter Bug (Fixed 2025-06-24)
**Issue**: Shopify's `currentTotalWeight` field can return incorrect values that don't match the actual sum of line item weights.
- **Example**: Order with 245g product showed `currentTotalWeight: 33` but calculated weight was 245g
- **Root Cause**: Shopify API data inconsistency between `currentTotalWeight` and individual product weights
- **Fix**: Rule engine now calculates weight from line items and falls back to `currentTotalWeight` only when values match
- **Location**: `backend/rule_engine.py` lines 123-171
- **Warning**: Large discrepancies (>1g) are logged and calculated weight is used instead

```python
# Weight calculation logic - uses line item weights when Shopify's currentTotalWeight is incorrect
if abs(total_calculated_weight - weight_grams) > 1:
    logger.warning(f"Large discrepancy between Shopify currentTotalWeight ({weight_grams}g) and calculated weight ({total_calculated_weight}g). Using calculated weight.")
    return total_calculated_weight
```

**Debug Commands for Weight Issues**:
```bash
# Check detailed weight breakdown for specific order
curl "http://localhost:8000/debug/order-data/1?order_name=TS1404" -H "Authorization: Bearer TOKEN"

# Monitor weight calculations in logs
docker-compose logs api worker --tail=50 | grep -A20 -B5 "order_weight\|Weight\|grams"
```