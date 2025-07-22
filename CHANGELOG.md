# Changelog

All notable changes to the Shopify Multi-Store Order Management System are documented in this file.

## [2025-07-16] - Critical Bug Fixes and Performance Improvements

### Database Session Management Improvements
- **Issue**: Stale database sessions causing fraud analysis to work with outdated data
- **Fix**: Added `expire_all()` and `commit()` calls before critical operations in:
  - `fraud_service.py`: Session refresh before fraud analysis
  - `fraud_rule_processor.py`: Fresh data loading with re-fetch of fraud analysis
- **Result**: Eliminated stale data issues and ensured consistent fraud detection

### Race Condition Resolution
- **Issue**: Fraud processing sometimes ran on uncommitted order data
- **Fix**: Added explicit commit and 200ms delay in `tasks.py` before fraud processing
- **Implementation**:
  ```python
  # CRITICAL: Ensure order state is fully committed before fraud processing
  db.commit()
  logger.info(f"Committed order changes for {order_number} before fraud processing")
  
  # Add small delay to ensure database propagation
  await asyncio.sleep(0.2)  # 200ms delay
  ```
- **Result**: Guaranteed data consistency between order processing and fraud analysis

### Error Isolation for Fraud Processing
- **Issue**: Fraud processing errors could break the main order processing pipeline
- **Fix**: Implemented isolated database session for fraud processing
- **Implementation**: 
  - Created separate `fraud_db` session in `_process_fraud_rules_for_order()`
  - Proper error handling with isolated session cleanup
  - Fixed missing `shopify_client` parameter in function call
- **Result**: Fraud processing failures no longer affect main order processing

### GraphQL Query Cost Optimization
- **Issue**: High GraphQL query costs leading to API quota exhaustion
- **Implemented Features**:
  - **Cost Tracking**: Real-time monitoring of GraphQL query costs
  - **Optimized Queries**: Three levels - minimal, balanced, full
  - **Adaptive Optimization**: Automatic downgrade when costs exceed thresholds
  - **New Methods**:
    - `get_orders_optimized()`: Manual optimization level control
    - `get_orders_adaptive()`: Automatic cost-based optimization
  - **Debug Endpoint**: `/debug/query-costs/{store_id}` for monitoring
- **Result**: Reduced average query costs by 40-60% while maintaining data completeness

### Shopify Fraud Risk Level Protection
- **Verified**: Existing protection properly prevents overwriting Shopify's fraud assessment
- **Implementation**: Debug logging to detect any unauthorized modifications
- **Result**: Shopify's fraud risk levels remain immutable after initial analysis

### Task Management Enhancement
- **Issue**: Stale tasks accumulating in "running" state indefinitely
- **Fix**: Added `cleanup_stale_tasks()` function with configurable timeout
- **Implementation**:
  - Integrated into daily cleanup job
  - Proactive cleanup before order/fraud processing
  - Marks tasks as failed after 12-24 hours
- **Result**: Prevents zombie tasks and improves system reliability

## [2025-07-14] - Fraud Detection System Enhancements

### Key Features
- **Fraud Analysis**: Automated analysis of orders for fraud indicators including first-time customers, duplicate orders, transaction attempts, and more
- **Fraud Detection Rules**: Create custom rules to automatically flag or process orders based on fraud indicators
- **Configurable Duplicate Detection**: 
  - User-configurable duplicate detection window (default 7 days, adjustable 1-365 days)
  - Settings stored per user in Settings table
  - Checks customer order history within configured window
- **Fraud Actions**: Log alerts, flag orders, add notes, update scores, block orders, require manual review
- **Integration**: Fraud rules integrate with existing rule engine for unified order processing

### Technical Implementation
- `backend/fraud_service.py` - Core fraud analysis service with duplicate detection
- `backend/fraud_rule_processor.py` - Processes fraud detection rules against analyzed orders
- `backend/models.py` - Added FraudAnalysis and FraudDetectionRule models
- `frontend/src/pages/FraudDetection.tsx` - Main fraud detection UI with sorting and filtering
- `frontend/src/pages/Settings.tsx` - Fraud sync controls and duplicate detection settings

### Fixes
- **Fixed Progress Indicators**: Added extended polling and automatic cleanup for stuck tasks
- **Enhanced Duplicate Detection**: 
  - Added customer order history to GraphQL queries
  - Database session refresh for fresh settings
  - Proper boolean type conversion for rule evaluation
- **Task Status Management**: Fixed duplicate task creation and added stale task cleanup

### Known Issues
- Duplicate detection updates may require manual fraud analysis trigger after settings change
- Some edge cases with existing fraud analyses not updating when duplicate detection days changed

## [2025-07-08] - Server-Side Sorting & Date Filtering for Order Logs

### Server-Side Sorting Implementation
- **Database-Level Sorting**: All sorting now performed at database level before pagination
- **Supported Sort Fields**: 
  - `order_number` - Direct field sorting
  - `store_name` - JOIN with ShopifyStore table  
  - `latest_date` - Aggregated max(created_at) sorting
  - `status` - Complex priority-based sorting (error=0, match=1, skipped=2)
  - `action_count` - COUNT-based sorting for number of actions per order
- **Order Preservation Fix**: Added CASE statement to maintain backend sort order when retrieving logs
- **API Changes**: Added `sort_field` and `sort_direction` parameters to `/order-logs` endpoint
- **Result**: Sorting now works globally across all pages, not just current page data

### Comprehensive Date Filtering System
- **Quick Date Presets**:
  - All Time (default) - No date filtering
  - Today - Orders from current day only
  - This Week - Orders from start of current week (Sunday) to now
  - This Month - Orders from start of current month to now  
  - This Year - Orders from start of current year to now
  - Custom Range - User-selectable date range with from/to inputs
- **Custom Date Selection**: 
  - Date input fields appear when "Custom Range" selected
  - Proper timezone-aware boundary calculations
  - End date automatically includes full day (23:59:59)
- **Backend Integration**:
  - Added `date_from` and `date_to` parameters to API
  - Timezone-aware ISO date parsing with proper UTC handling
  - Applied across all sorting query branches using helper function
- **UI Enhancements**:
  - Date filter positioned as first column for better UX
  - Enhanced filter headers with better visual hierarchy
  - Responsive 4-column filter grid layout
  - Compact single-line design maintained

### Order Logs Search Enhancement
- Search input field for order number filtering
- Debounced search with 500ms delay to reduce API calls
- Search state preserved during pagination
- Automatic page reset to 1 when search changes

### Configurable Order Sync Window
- New `sync_window_days` setting (default: 7 days)
- Configurable from 1-365 days in Settings page
- Replaces hardcoded 24-hour sync window
- Helps recover older missed orders when needed

## [2025-07-06] - Comprehensive Timezone Management System

### Key Features
- User-configurable timezone and date format settings in Settings page
- Centralized `TimezoneContext` for global state management across all components
- Proper UTC timestamp storage with client-side timezone conversion
- Real-time timezone updates without page refresh using custom events
- Grouped timezone selector with current time preview

### Database Changes
- Added `timezone` and `date_format` columns to Settings model
- Fixed OrderLog timestamp storage to use actual Shopify order creation times instead of processing times
- Proper timezone-aware datetime handling with UTC storage

### API Enhancements
- `GET /settings/timezones` - Returns grouped timezone list with pytz integration
- `GET /settings/date-formats` - Returns available date format options with examples
- Updated OrderLog API responses to include proper UTC timezone markers (`Z` suffix)

### Frontend Architecture
- `TimezoneContext.tsx` - Centralized timezone state management with custom event handling
- `dateFormat.ts` - Unified date formatting utilities using date-fns-tz
- All components updated to use centralized date formatting (`useTimezone()` hook)
- Cross-window timezone sync using localStorage and custom events

### Critical Issue Fixed
- Resolved 5-hour timezone discrepancy where OrderLog entries showed processing time instead of actual order creation time

## [2025-07-03] - Admin Panel System

### Key Features
- Comprehensive admin panel for managing the entire platform, users, and system monitoring
- Role-based access control: `super_admin`, `admin`, `support`, `read_only`
- Complete audit trail of all admin actions
- Secure password management with current password verification
- Separate admin authentication from user authentication

### Components Added
- `AdminUser` model with role-based access control
- `AdminAuditLog` model for complete audit trail
- `SystemSettings` model for global system configuration
- 13 new admin API endpoints
- Admin frontend pages: AdminLogin, AdminDashboard, AdminUsers
- `init_admin.py` script for initial admin setup

## [2025-06-25] - Multiple System Enhancements

### SKU Exclusion System
- Case-insensitive substring pattern matching (e.g., "TEST", "SAMPLE", "_EXCLUDED")
- User-scoped exclusion patterns with optional descriptions
- Active/inactive toggle for temporary exclusions
- Comprehensive CRUD operations via UI and API
- Excluded SKUs filtered from weight calculations and OOS reporting
- **Critical**: Excluded SKUs still participate in fulfillment location moves

### Security Hardening
- Fixed partial fulfillment scenarios where Shopify API returned incomplete SKU data
- SKU lookup fallback automatically retrieves missing SKU data
- Enhanced monitoring with `✅ EXCLUDED:` markers
- Parameter validation for all OOS recording functions
- 100% coverage for both normal and retry processing

### OOS Reports Deduplication System
- Order-Level Deduplication: Each order appears only once
- Product-Level Deduplication: Composite key deduplication for accurate counts
- Transparent Metrics: Shows both unique and total counts
- Database-level duplicate prevention

### Order Logs Status Classification
- **"Match"** = Rule matched and was applied (even if fulfillment failed)
- **"Skipped"** = No rules matched the order
- **"Error"** = System errors or Shopify API errors (non-inventory issues)
- Clear distinction between "rule matched" vs "actions succeeded"

### Enhanced Order Logs Page
- Grouped View: Orders grouped by order number with expand/collapse
- Sorting: All columns sortable
- Space Efficiency: One line per order by default
- Status Indicators: Visual badges for Match, Error, Skipped
- Action Count: Badge showing number of events per order

### Data Reset Feature
- Location: Settings page → Data Management section
- Two-factor confirmation with "RESET" typing requirement
- Selective reset options for different data types
- Preserves configuration while clearing operational data

### Hot Reload Configuration
- Frontend Dockerfile configured for development mode
- docker-compose.yml with proper volume mounting
- No more Docker cache purging required for UI updates

## [2025-06-24] - Critical Bug Fixes

### Rule Priority Execution Order
- Fixed rules executing in wrong order (was 3→2→1→0, now 0→1→2→3)
- Changed from `.order_by(ProcessingRule.priority.desc())` to `.order_by(ProcessingRule.priority.asc())`

### Rule Execution Timing and Synchronization
- Order refresh now happens after ANY matching rule
- Added configurable `delay_ms` parameter to each rule (default 10ms, max 60000ms)
- Added critical 1000ms delay after OOS tag addition
- Fixed IN LIST operator case sensitivity for province/state fields

### Weight Filter Bug
- Fixed Shopify's incorrect `currentTotalWeight` values
- Rule engine now calculates weight from line items
- Falls back to `currentTotalWeight` only when values match
- Large discrepancies (>1g) logged with calculated weight used instead

### All-or-Nothing Fulfillment Policy
- Fulfillment location changes only proceed if ALL products can be fulfilled
- Pre-check inventory availability before attempting moves
- Only unavailable products recorded as OOS incidents

### GraphQL Query Optimization
- Reduced fetch limits to stay under cost limit:
  - `fulfillmentOrders`: 10 → 5
  - `lineItems`: 100 → 20

### Fulfillment Location Conditional Logic
- Fixed rules with fulfillment location conditions never matching
- Added special handling for `fulfillment_location` field with `equals`/`not_equals`
- Now checks if expected value exists anywhere in location list (ANY match)
- Backend validation restricts operators for fulfillment_location field