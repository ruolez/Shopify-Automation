# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Shopify Multi-Store Order Management System - a comprehensive automated order processing and tagging system with a modern UI and background processing capabilities. The system allows users to connect multiple Shopify stores, create complex automation rules, and process orders automatically based on conditions like weight, shipping location, product types, etc.

## Architecture

### Core Components

**Backend (FastAPI + SQLAlchemy + Celery)**
- `backend/main.py` - FastAPI application with REST endpoints and debugging endpoints
- `backend/models.py` - SQLAlchemy models (User, ShopifyStore, ProcessingRule, OrderLog, Settings, ProcessedOrder, LocationAlias, LocationMapping, OutOfStockIncident, ExcludedSKU)
- `backend/rule_engine.py` - Rule evaluation engine with 15+ operators and field extraction
- `backend/tasks.py` - Celery background tasks for order processing and store synchronization
- `backend/shopify_client.py` - Shopify Admin API GraphQL client with order management and fulfillment operations
- `backend/database.py` - Database configuration and session management
- `backend/auth.py` - JWT authentication and user management

**Frontend (React + TypeScript + Tailwind)**
- `frontend/src/pages/` - Main application pages (Dashboard, Stores, Rules, RuleBuilder, Settings, OrderLogs, Reports)
- `frontend/src/components/` - Reusable UI components
- `frontend/src/contexts/` - React Context providers for global state management
  - `AuthContext.tsx` - Authentication state management
  - `TimezoneContext.tsx` - Centralized timezone and date formatting state
  - `SettingsContext.tsx` - User settings management (legacy, superseded by TimezoneContext)
- `frontend/src/utils/` - Utility functions and API clients
  - `api.ts` - Axios API client with interceptors
  - `dateFormat.ts` - Centralized date formatting with timezone support

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

# Run backend tests (uses Pytest framework)
cd backend
pytest                    # Run all tests
pytest -m "not slow"      # Skip slow integration tests
pytest -m unit           # Run only unit tests
pytest -m integration    # Run only integration tests
pytest -v                # Verbose output
pytest --cov=.           # Generate coverage report

# Access database via container
docker exec shopify_api python -c "from database import engine; print('DB accessible')"
```

### Frontend Development

**Hot Reload Setup (Recommended)**
The Docker setup is configured for development mode with hot reload and volume mounting:
```bash
# Start all services with hot reload enabled
docker-compose up -d

# Frontend automatically runs in development mode with hot reload
# Changes to React/CSS files are instantly visible without rebuilds
```

**Local Development (Alternative)**
```bash
# Start backend services then run frontend locally
docker-compose up -d redis api worker scheduler
cd frontend
npm install
npm run dev

# Build for production
npm run build

# Run tests (uses Vitest framework)
npm test                # Run all tests
npm run test:ui         # Interactive test UI
npm run test:coverage   # Generate coverage report
npm run test:watch      # Watch mode for development

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

### Production Update and Deployment

**Update Script Usage (2025-06-25)**
The `update.sh` script provides flexible deployment options for production servers:

```bash
# Full update with data protection (DEFAULT - RECOMMENDED)
./update.sh
# - Creates backup of database and Redis data
# - Pulls latest code from git
# - Rebuilds containers with new code  
# - Automatically restores database from backup
# - Use when: deploying code changes with maximum safety

# Code-only update (preserves existing data as-is)
./update.sh --keep-db
# - No backup created or restored
# - Pulls latest code from git
# - Rebuilds containers with new code
# - Database volume persists unchanged through rebuild
# - Use when: confident in data integrity, want faster updates

# Other options
./update.sh --backup-only           # Just create backup, no update
./update.sh --restore-from BACKUP   # Restore from specific backup  
./update.sh --no-pull              # Update without pulling git changes
```

**Migration-Safe Updates**
For schema changes, use `update-with-migration.sh`:
```bash
# Schema-safe update (handles database structure changes)
./update-with-migration.sh
# - Exports data as SQL before update (schema-independent)
# - Pulls latest code and rebuilds containers
# - Imports data into new schema structure
# - Use when: database model changes, new tables added
```

## Critical Implementation Details

### Shopify GraphQL Integration
- Uses Admin API 2025-04 with proper GraphQL global IDs (`gid://shopify/Location/123`)
- Fulfillment location changes require orders in "open" or "scheduled" status
- Order fetching includes nested structures: `fulfillmentOrders.edges.node.assignedLocation.location`
- Pagination handled with cursor-based navigation

### Rule Processing Safeguards
- `ProcessedOrder` table with unique constraint prevents duplicate processing
- Rules processed by priority in ascending order (0→1→2→3) - lower numbers execute first
- Failed actions don't block subsequent actions in same rule
- Extensive logging in `OrderLog` for debugging and user visibility
- **All-or-Nothing Fulfillment Policy**: Products only move if ALL can be fulfilled at target location
- Inventory pre-check validation before attempting fulfillment moves

### Background Processing Architecture
- `process_all_orders_if_enabled` checks user settings before queuing store-specific tasks
- Dynamic scheduling: sync frequency adjustable per user (5-60+ minutes)
- Worker concurrency: 4 processes, horizontally scalable
- Task retry logic with error logging for Shopify API failures

### Database Schema Key Points
- User-scoped data isolation (all major tables have `user_id` foreign key)
- JSON columns for flexible rule conditions/actions storage
- Cascade delete relationships prevent orphaned data
- Settings table for per-user sync preferences and timezone configuration
- Timezone-aware datetime storage (UTC) with proper timezone handling in API responses

### Authentication Flow
- JWT tokens with configurable expiration
- FastAPI Depends() injection for protected endpoints
- Frontend axios interceptors for automatic token refresh
- User registration/login with bcrypt password hashing

This system handles complex real-time order processing with proper error handling, logging, and user isolation - critical for production Shopify automation.

### Recent Feature Additions

#### Comprehensive Timezone Management System (2025-07-06)
**Purpose**: Provides global timezone management with real-time updates across the entire application.
- **Key Features**:
  - User-configurable timezone and date format settings in Settings page
  - Centralized `TimezoneContext` for global state management across all components
  - Proper UTC timestamp storage with client-side timezone conversion
  - Real-time timezone updates without page refresh using custom events
  - Grouped timezone selector with current time preview
- **Database Changes**:
  - Added `timezone` and `date_format` columns to Settings model
  - Fixed OrderLog timestamp storage to use actual Shopify order creation times instead of processing times
  - Proper timezone-aware datetime handling with UTC storage
- **API Enhancements**:
  - `GET /settings/timezones` - Returns grouped timezone list with pytz integration
  - `GET /settings/date-formats` - Returns available date format options with examples
  - Updated OrderLog API responses to include proper UTC timezone markers (`Z` suffix)
- **Frontend Architecture**:
  - `TimezoneContext.tsx` - Centralized timezone state management with custom event handling
  - `dateFormat.ts` - Unified date formatting utilities using date-fns-tz
  - All components updated to use centralized date formatting (`useTimezone()` hook)
  - Cross-window timezone sync using localStorage and custom events
- **UI Improvements**:
  - Removed timezone search field (simplified to dropdown only)
  - Added current time preview in selected timezone
  - Removed non-functional "Generate" button from Reports page
- **Technical Implementation**:
  - Uses `date-fns-tz` for proper timezone conversion
  - Backend stores all timestamps in UTC with timezone-aware handling
  - API serializes timestamps with 'Z' suffix to indicate UTC
  - Frontend converts UTC times to user's selected timezone for display
- **Fixes Critical Issue**: Resolved 5-hour timezone discrepancy where OrderLog entries showed processing time instead of actual order creation time

**Migration Notes**: 
- Added `pytz==2024.1` and `date-fns-tz` dependencies
- Existing timestamps are treated as UTC for proper conversion
- Hot reload enabled for frontend development workflow

#### SKU Exclusion System (2025-06-25)
**Purpose**: Allows users to exclude specific SKU patterns from weight calculations and OOS reporting while preserving fulfillment functionality.
- **Location**: Settings page → Excluded SKUs section
- **Key Features**:
  - Case-insensitive substring pattern matching (e.g., "TEST", "SAMPLE", "_EXCLUDED")
  - User-scoped exclusion patterns with optional descriptions
  - Active/inactive toggle for temporary exclusions
  - Comprehensive CRUD operations via UI and API
- **Database**: New `ExcludedSKU` model with automatic table creation
- **API Endpoints**: 
  - `GET /settings/excluded-skus` - List all patterns
  - `POST /settings/excluded-skus` - Create new pattern
  - `PUT /settings/excluded-skus/{id}` - Update pattern
  - `DELETE /settings/excluded-skus/{id}` - Delete pattern
- **Frontend Integration**: Uses centralized date formatting with timezone support for creation dates
- **Behavior**:
  - Excluded SKUs are filtered from weight calculations in rule conditions
  - Excluded SKUs don't generate OOS incidents when unavailable
  - **Critical**: Excluded SKUs still participate in fulfillment location moves
  - Extensive logging for debugging and visibility

**Security Hardening (2025-06-25)**:
- **Critical vulnerability fixed**: Partial fulfillment scenarios where Shopify API returned incomplete SKU data
- **SKU lookup fallback**: Automatically retrieves missing SKU data from original order when API fails
- **Enhanced monitoring**: Comprehensive logging with `✅ EXCLUDED:` markers for tracking effectiveness
- **Parameter validation**: All OOS recording functions include exclusion checks with warnings for compromised data
- **100% coverage**: Both normal processing and retry processing properly exclude SKUs

#### OOS Reports Deduplication System (2025-06-25)
**Purpose**: Prevents duplicate orders from appearing in reports when multiple retries or rules affect the same order.
- **Key Improvements**:
  - **Order-Level Deduplication**: OOS orders report now shows each order only once (keeps most recent entry)
  - **Product-Level Deduplication**: OOS products report uses composite key deduplication for accurate incident counts
  - **Transparent Metrics**: Reports show both `unique_incidents` (deduplicated) and `total_records` (raw count)
  - **Prevention Logic**: Database-level checks prevent duplicate OOS incident creation
- **Implementation**: 
  - `backend/main.py` - Updated report endpoints with deduplication queries
  - `backend/tasks.py` - Added existence checks before creating OOS incidents
  - Applied to all three OOS recording functions: `_record_oos_incident`, `_record_oos_incident_for_failed_items`
- **Result**: Accurate reporting regardless of how many times orders are retried or processed by multiple rules

#### Order Logs Status Classification (2025-06-25)
**Purpose**: Provides clear, meaningful status classification that distinguishes rule matching from action outcomes.
- **New Status Logic**:
  - **"Match"** = Rule matched and was applied (even if fulfillment failed due to inventory issues)
  - **"Skipped"** = No rules matched the order
  - **"Error"** = System errors or Shopify API errors (non-inventory issues)
- **Key Changes**:
  - Rule matching always shows "Match" status regardless of action success/failure
  - `fulfillment_move_failed` logs use "info" status (don't affect main order status)
  - Frontend updated with new status icons and filter options
  - Backward compatibility maintained for historical data
- **Implementation**:
  - `backend/tasks.py` - Updated rule processing and retry logic status assignment
  - `frontend/src/pages/OrderLogs.tsx` - New status icons, filters, and grouping logic
- **Benefits**:
  - Clear distinction between "rule matched" vs "actions succeeded"
  - Out-of-stock fulfillment failures don't mask successful rule application
  - Better user understanding of order processing outcomes

#### Order Logs Search Enhancement (2025-07-08)
**Purpose**: Adds search functionality to the Order Logs page for easier order lookup.
- **Key Features**:
  - Search input field for order number filtering
  - Debounced search with 500ms delay to reduce API calls
  - Search state preserved during pagination
  - Automatic page reset to 1 when search changes
- **Implementation**:
  - `backend/main.py`: Added `search` parameter to `/order-logs` endpoint
  - `frontend/src/pages/OrderLogs.tsx`: Added search input with debouncing logic
- **API**: `GET /order-logs?search=PW110446` filters logs by order number substring match

#### Configurable Order Sync Window (2025-07-08)  
**Purpose**: Allows users to configure how many days back to fetch orders during sync operations.
- **Key Features**:
  - New `sync_window_days` setting (default: 7 days)
  - Configurable from 1-365 days in Settings page
  - Replaces hardcoded 24-hour sync window
  - Helps recover older missed orders when needed
- **Implementation**:
  - `backend/models.py`: Added `sync_window_days` column to Settings model
  - `backend/tasks.py`: Updated order sync logic to use configurable window
  - `frontend/src/pages/Settings.tsx`: Added UI control for sync window configuration
- **Use Cases**:
  - Set to 1 day for normal operations (recent orders only)
  - Set to 7-30 days for recovering missed orders after system downtime
  - Adjust based on order volume and processing needs

#### Previous Features (2025-06-24)

#### Enhanced Order Logs Page
- **Grouped View**: Orders now grouped by order number with expand/collapse functionality
- **Sorting**: All columns (Order, Store, Actions, Status, Latest Activity) are sortable
- **Space Efficiency**: One line per order by default, expandable to show all log entries
- **Status Indicators**: Visual badges showing Match, Error, Skipped status for each order (updated in 2025-06-25)
- **Action Count**: Badge showing number of events per order
- **Timezone Integration**: All timestamps display in user's selected timezone with proper conversion

#### Data Reset Feature
**Purpose**: Allows users to purge operational data while preserving configuration.
- **Location**: Settings page → Data Management section
- **Safety Features**: Two-factor confirmation with "RESET" typing requirement
- **Selective Reset**: Checkboxes for order logs, processed orders, OOS incidents, task status
- **Preserves**: User accounts, store connections, rules, settings, location aliases
- **Endpoint**: `POST /settings/reset-data` with confirmation validation

#### Dashboard Simplification
- **Removed Redundancy**: Eliminated "Recent Activity" section that duplicated Order Logs functionality
- **Focused Design**: Dashboard now focuses on essential metrics (stores, rules) and quick actions
- **Improved UX**: Users directed to enhanced Order Logs page for detailed order processing information

## Critical Bug Fixes & Known Issues

### Rule Priority Execution Order (Fixed 2025-06-24)
**Issue**: Rules were executing in descending priority order (3→2→1→0) instead of ascending.
- **Impact**: Remove tag rules ran before prerequisite rules that added the target tags
- **Fix**: Changed from `.order_by(ProcessingRule.priority.desc())` to `.order_by(ProcessingRule.priority.asc())`
- **Location**: `backend/tasks.py:430` and `backend/main.py:235`
- **Behavior**: Rules now execute 0→1→2→3 (lower priority numbers first)

### Rule Execution Timing and Synchronization (Fixed 2025-06-24)
**Issue**: Rules weren't seeing state changes from previous rules due to caching and timing issues.
- **Problems Solved**:
  - Order refresh now happens after ANY matching rule (not just successful ones)
  - Added configurable `delay_ms` parameter to each rule (default 10ms, max 60000ms)
  - Added critical 1000ms delay after OOS tag addition to ensure proper synchronization
  - Fixed IN LIST operator case sensitivity for province/state fields
- **UI Enhancement**: Rules page now shows delay_ms with purple badge
- **Database**: Added `delay_ms` column to ProcessingRule model

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

### Order Processing Date Filter Issues
**Issue**: Orders created during sync windows can be missed due to timing gaps.
- **Symptom**: New orders show `processed_orders: 0` and aren't processed despite being recent
- **Cause**: `last_sync` timestamp is updated after processing completes, creating timing gaps
- **Debug**: Check `last_sync` time vs order creation time in logs
- **Workaround**: Manually reset store's `last_sync` to time before problem order was created
- **Long-term Fix**: Use sync start time instead of completion time for date filtering

### Frontend Docker Cache Issues (CRITICAL)
**Problem**: Docker caches frontend builds, preventing new React changes from appearing in the browser.
**Solution**: ALWAYS purge Docker cache when frontend changes don't appear:
```bash
# REQUIRED process for frontend changes
docker-compose down
docker system prune -f  # Purges all cache including build cache
docker-compose up -d
```
**When to use**: Every time frontend changes aren't visible after container restart.
**Note**: Simple `docker-compose restart frontend` is NOT sufficient - cache persists.

### All-or-Nothing Fulfillment Policy (Added 2025-06-24)
**Feature**: Fulfillment location changes only proceed if ALL products in an order can be fulfilled at the target location.
- **Implementation**: Pre-check inventory availability before attempting fulfillment moves
- **Behavior**: If any product is out of stock at target location, no products are moved
- **OOS Recording**: Only products that are actually unavailable are recorded as OOS incidents
- **Location**: `backend/tasks.py` - `_check_inventory_availability()` and fulfillment action processing

### Out of Stock (OOS) Reporting System
**Components**:
1. **OOS Incident Tracking**: `OutOfStockIncident` model records product-level OOS data
2. **Reports Page**: Three tabs - Fulfillment Errors, OOS Orders, Product Analysis
3. **Product Analysis**: 
   - Aggregates OOS incidents by product/variant
   - Shows total incidents, affected quantities, and locations
   - Supports analyzing selected orders or date ranges
4. **Location Alias System**: Maps user-friendly names to Shopify location IDs

### GraphQL Query Optimization (Fixed 2025-06-24)
**Issue**: Shopify GraphQL queries exceeded cost limit (1241 > 1000)
**Fix**: Reduced fetch limits:
- `fulfillmentOrders`: 10 → 5
- `lineItems`: 100 → 20
**Note**: Pagination may be needed for orders with many items

### Fulfillment Location Conditional Logic (Fixed 2025-07-08)
**Issue**: Rules with fulfillment location conditions would never match orders.
- **Root Cause**: The rule engine was comparing the entire location array against a single string value using exact equality
- **Example**: Order had `['gid://shopify/Location/104204796206', 'SC Warehouse', 'SC']` but rule checked if this entire array equals `"SC"`
- **Fix**: 
  - Added special handling for `fulfillment_location` field with `equals`/`not_equals` operators
  - Now checks if the expected value exists anywhere in the location list (ANY match)
  - Backend validation restricts fulfillment_location to only `equals`/`not_equals` operators
  - Frontend UI updated to show only valid operators for fulfillment_location fields
- **Implementation**: 
  - `backend/rule_engine.py`: Added special case handling in `_evaluate_condition()` method
  - `backend/schemas.py`: Added Pydantic validator to restrict operators
  - `frontend/src/pages/RuleBuilder.tsx`: Updated `getOperatorsForField()` to filter operators
- **Result**: Fulfillment location conditions now work correctly, matching when ANY location in the order matches the rule condition

### Critical CSS Classes
**Issue**: `btn-primary` and `btn-secondary` classes don't exist in Tailwind
**Fix**: Use explicit Tailwind classes:
```tsx
// Correct button styling
className="inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-shopify-600 hover:bg-shopify-700"
```

## Docker Development Workflow

### Development vs Production
- **Development**: Uses volume mounting for hot reload (Vite polling enabled for Docker compatibility)
- **Production**: Frontend built into static files, served by Nginx with security headers and rate limiting

### Hot Reload Configuration (Fixed 2025-06-25)
**Important**: The Docker setup now includes proper hot reload configuration that persists across new installations:

**Frontend Dockerfile** - Configured for development mode:
```dockerfile
# Start in development mode with hot reload
CMD ["npm", "run", "dev"]
```

**docker-compose.yml** - Volume mounting enabled:
```yaml
frontend:
  volumes:
    - ./frontend:/app
    - /app/node_modules
```

**For New Installations**: Hot reload is automatically enabled. No manual configuration needed.
**Benefits**: 
- CSS/React changes instantly visible without rebuilds
- No more Docker cache purging required for UI updates
- Consistent development experience across all environments

### Timezone Display Issues (Fixed 2025-07-06)
**Issue**: 5-hour timezone discrepancy where OrderLog entries showed processing time instead of actual order creation time.
- **Root Cause**: OrderLog was storing Celery task execution time instead of Shopify order creation timestamp
- **Symptoms**: Order created at 10:53 AM displayed as 15:53 in system (5-hour difference)
- **Fix**: Updated `_log_order_action()` to accept and use actual Shopify `createdAt` timestamp
- **Technical Solution**:
  - Parse Shopify ISO timestamps with proper timezone awareness
  - Store as UTC in database with timezone information preserved
  - API returns timestamps with 'Z' suffix for proper frontend interpretation
  - Frontend uses TimezoneContext for proper local timezone conversion
- **Implementation**: `backend/tasks.py` - Added `order_created_at` parameter to logging functions
- **Result**: All timestamps now accurately reflect actual order creation times in user's selected timezone

### Critical Frontend Cache Issues (Legacy - Now Fixed)
**Previous Problem**: Docker aggressively cached builds, preventing new React changes from appearing.
**Fixed**: Hot reload now eliminates the need for cache purging in most cases.
**Legacy Solution** (only if hot reload fails):
```bash
# REQUIRED process - simple restart is NOT enough
docker-compose down
docker system prune -f  # Purges build cache
docker-compose up -d
```

### Service Management
```bash
# Restart individual services (preserves cache)
docker-compose restart api worker scheduler

# View logs for debugging
docker-compose logs -f worker  # Background processing
docker-compose logs -f api     # API requests and rule evaluation

# Production deployment with build
docker-compose up -d --build
```

## Testing Framework Details

### Backend Testing (Pytest)
The project uses a comprehensive Pytest setup with:
- **Test Markers**: `unit`, `integration`, `slow` for selective test execution
- **Isolated Test Database**: In-memory SQLite for each test session
- **Fixtures**: Pre-configured authentication, stores, and rules for testing
- **Coverage**: Built-in coverage reporting with pytest-cov

**Test Structure**:
- Unit tests: Fast, isolated component testing
- Integration tests: End-to-end API and database testing
- Slow tests: External API calls and complex workflows

### Frontend Testing (Vitest)
Modern testing setup with:
- **Browser API Mocking**: IntersectionObserver, ResizeObserver, localStorage automatically mocked
- **JSX/DOM Testing**: Complete React component testing environment
- **Coverage**: V8-based coverage reporting
- **Interactive UI**: `npm run test:ui` for visual test debugging

## Production Infrastructure

### Nginx Configuration
Production setup includes:
- **Rate Limiting**: 100 req/min for API, 20 req/min for auth endpoints
- **Security Headers**: HSTS, XSS protection, frame options, content type sniffing protection
- **SSL Ready**: Configuration prepared for SSL certificate integration
- **Reverse Proxy**: Load balancing between frontend and API services

### Environment Variables
Comprehensive configuration via `.env.example`:
- Database settings and JWT configuration
- Redis connection parameters
- Shopify API settings and debug flags
- Docker service ports and volumes

### Data Persistence
- **SQLite Database**: Persistent volume for production data
- **Redis**: Persistent volume for task queue state
- **Logs**: Mounted directory for centralized logging

## Admin Panel System (2025-07-03)

**Purpose**: Comprehensive admin panel for managing the entire platform, users, and system monitoring.

### Admin Panel Architecture

**Admin Database Models** (`backend/models.py`)
- `AdminUser`: Admin accounts with role-based access control
  - Roles: `super_admin`, `admin`, `support`, `read_only`
  - Separate from user accounts for security isolation
  - BCrypt password hashing with 8-hour JWT tokens
- `AdminAuditLog`: Complete audit trail of all admin actions
  - Tracks who did what, when, where (IP/user agent)
  - Links to affected resources with detailed JSON metadata
- `SystemSettings`: Global system configuration management

**Admin Authentication** (`backend/admin_auth.py`)
- Separate JWT authentication system from user auth
- 8-hour token expiration for admin sessions
- Role-based permissions with dependency injection
- Secure password change functionality with current password verification

**Admin API Endpoints** (`backend/main.py` - 13 new endpoints)
```python
# Authentication
POST /admin/auth/login              # Admin login with audit logging
GET  /admin/auth/me                 # Get current admin user
PUT  /admin/auth/change-password    # Change admin password

# Dashboard & Statistics  
GET  /admin/stats                   # System overview statistics

# User Management
GET  /admin/users                   # List all users with activity metrics
PUT  /admin/users/{id}/toggle-active  # Activate/deactivate users
DELETE /admin/users/{id}            # Delete users (with cascade)

# Resource Monitoring
GET  /admin/stores                  # All connected stores across users
GET  /admin/rules                   # All processing rules across users
GET  /admin/order-logs              # System-wide order processing logs

# Audit & Compliance
GET  /admin/audit-logs              # Admin action audit trail
POST /admin/users                   # Create additional admin users
```

**Admin Frontend Components**
- `AdminLogin.tsx` - Dedicated admin authentication page
- `AdminDashboard.tsx` - System metrics and quick actions with password change
- `AdminUsers.tsx` - User management interface with activate/deactivate/delete
- `adminApi.ts` - Admin API client with token management

**Admin Routes** (`frontend/src/App.tsx`)
```
/admin/login      # Admin authentication
/admin/dashboard  # Main admin dashboard  
/admin/users      # User management
```

### Key Admin Features

**System Statistics Dashboard**
- Total users (active/inactive breakdown)
- Connected stores (active/inactive breakdown)  
- Processing rules (active/inactive breakdown)
- Processed orders and log entries
- Recent registrations (7-day window)

**User Management**
- View all user accounts with activity metrics
- See stores and rules count per user
- Activate/deactivate user accounts
- Delete users with full cascade deletion
- Last activity tracking

**Security & Audit**
- Complete audit trail of all admin actions
- IP address and user agent logging
- Role-based access control for admin functions
- Secure password management with current password verification
- Separate admin authentication from user authentication

**Quick Actions Dashboard**
- Direct links to user management
- System monitoring shortcuts
- Recent activity overview
- Password change functionality

### Admin Setup & Usage

**Initial Setup**
```bash
# Create default admin user (run once)
docker exec shopify_api python init_admin.py

# Default credentials created:
# Username: admin
# Password: admin
```

**Admin Panel Access**
- **URL**: http://localhost:3000/admin/login
- **Default Credentials**: admin/admin
- **Security**: Change default password immediately after first login

**Database Integration**
- Admin tables created automatically with existing database
- No migration required - seamlessly integrates with current schema
- Audit logging starts immediately upon admin system activation

**Production Considerations**
- Change `ADMIN_SECRET_KEY` environment variable for production
- Consider shorter token expiration for high-security environments
- Admin audit logs provide complete compliance trail
- Role-based permissions allow delegation of admin tasks

### Security Features

**Authentication Isolation**
- Completely separate authentication system from user accounts
- Admin tokens stored separately with different expiration
- No cross-contamination between user and admin sessions

**Audit Compliance**
- Every admin action logged with full context
- IP address and user agent tracking
- JSON metadata for detailed action parameters
- Immutable audit trail for compliance requirements

**Role-Based Access**
- `super_admin`: Full system access
- `admin`: Standard admin operations
- `support`: Read-only with limited actions
- `read_only`: View-only access to system data

This admin panel provides complete platform management capabilities while maintaining security isolation and comprehensive audit trails for production use.

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.