# Fraud Detection Reconcile Fix Summary

## Issue Identified
The reconcile logic in fraud detection was failing after PostgreSQL implementation due to a foreign key constraint violation. When trying to archive fulfilled or cancelled fraud analyses, the system couldn't delete records from the `fraud_analyses` table because they were still referenced by the `processed_fraud_orders` table.

## Root Cause
The `_archive_analysis` method in `FraudArchiveService` was trying to delete fraud analysis records without first handling the related `ProcessedFraudOrder` records that had foreign key references to them.

## Solution Implemented

### 1. Modified `fraud_archive_service.py`
- Updated the `_archive_analysis` method to:
  - First delete any related `ProcessedFraudOrder` records that reference the fraud analysis
  - Then proceed with archiving the fraud analysis to the archive table
  - Finally delete the fraud analysis from the main table
- Added import for `ProcessedFraudOrder` model
- Added logging to track how many related orders were deleted during archiving

### 2. Archive Table Creation
The system now automatically creates the `fraud_analyses_archive` table if it doesn't exist, with all necessary columns to preserve the fraud analysis data.

## How the Reconcile Process Works

### Automatic Background Process
- Runs every hour via Celery scheduled task
- Processes users with `fraud_sync_enabled = True`
- Archives fraud analyses for orders that are:
  - Fulfilled (fulfillment_status = "FULFILLED")
  - Cancelled (fulfillment_status = "CANCELLED" or financial_status = "VOIDED"/"REFUNDED")
- Processes in batches to avoid database locks
- Respects user's `reconciliation_batch_size` setting (default: 500)

### Manual Trigger
- Endpoint: `POST /fraud-detection/archive-fulfilled-cancelled`
- Can be triggered from the frontend or via API
- Returns detailed information about:
  - Number of orders checked
  - Number of orders archived
  - Reasons for archiving
  - List of archived orders
  - Number of remaining orders to process

## Testing Performed
1. Created `test_reconcile_postgres.py` to verify:
   - Archive table existence and structure
   - Single archive operation functionality
   - Full reconcile process execution
   
2. Test Results:
   - ✓ Archive table created successfully
   - ✓ Foreign key constraint issue resolved
   - ✓ Successfully archived 4 fulfilled orders in test run
   - ✓ Related ProcessedFraudOrder records properly handled

## Files Modified
- `backend/fraud_archive_service.py` - Fixed the `_archive_analysis` method
- Created `backend/test_reconcile_postgres.py` - Test script for verification
- Created `backend/test_manual_reconcile.py` - Test script for manual endpoint

## Verification Steps
To verify the fix is working:

1. Check if orders are being archived:
   ```sql
   SELECT COUNT(*) FROM fraud_analyses_archive WHERE user_id = <user_id>;
   ```

2. Monitor the logs:
   ```bash
   docker logs shopify_worker -f | grep -i "archive"
   ```

3. Test manual trigger:
   ```bash
   python backend/test_manual_reconcile.py <auth_token>
   ```

4. Check scheduled task execution:
   ```bash
   docker exec shopify_scheduler celery -A tasks inspect scheduled
   ```

## Impact
- Prevents database growth by archiving completed fraud analyses
- Maintains referential integrity in PostgreSQL
- Improves system performance by keeping active tables smaller
- Preserves all fraud analysis data in archive table for historical reference