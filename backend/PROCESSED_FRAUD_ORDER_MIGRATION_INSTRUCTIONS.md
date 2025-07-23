# ProcessedFraudOrder Implementation Instructions

## Overview
This implementation adds a `ProcessedFraudOrder` table to prevent duplicate fraud detection processing of orders, similar to how the existing `ProcessedOrder` table works for regular order processing.

## Files Modified
1. **backend/models.py** - Added `ProcessedFraudOrder` model
2. **backend/tasks.py** - Updated fraud detection to check ProcessedFraudOrder before processing
3. **backend/migrations/add_processed_fraud_orders_table.py** - New migration script

## Running the Migration

### Development Environment
```bash
cd backend
python migrations/add_processed_fraud_orders_table.py
```

### Production Environment (Docker)
```bash
docker exec shopify_api python migrations/add_processed_fraud_orders_table.py
```

## How It Works

1. **Before Processing**: The fraud detection task checks if an order exists in `ProcessedFraudOrder` table
2. **Skip if Exists**: If found, the order is skipped with a debug log message
3. **After Processing**: When fraud analysis completes successfully, a `ProcessedFraudOrder` record is created
4. **Unique Constraint**: The table has a unique constraint on (store_id, order_id) to prevent duplicates at the database level

## Benefits

- **Prevents Duplicate Processing**: Orders won't be analyzed multiple times for fraud
- **Saves Resources**: Avoids unnecessary API calls and computations
- **Consistent Design**: Follows the same pattern as regular order processing
- **Database Integrity**: Enforced at database level, not just application logic
- **Handles Concurrency**: If two processes try to process the same order simultaneously, the unique constraint prevents duplicates

## Migration Details

The migration script:
1. Creates the `processed_fraud_orders` table with appropriate indexes
2. Populates it with existing fraud analyses (if any) to ensure consistency
3. Handles cases where the table already exists (idempotent)

## Edge Cases Handled

- **Concurrent Processing**: If two workers try to process the same order, the unique constraint prevents duplicates
- **Migration Safety**: The migration can be run multiple times safely
- **Existing Data**: The migration populates the table with existing fraud analyses to prevent reprocessing

## Testing

To verify the implementation is working:
1. Run the migration
2. Trigger fraud detection for an order
3. Check that a `ProcessedFraudOrder` record is created
4. Trigger fraud detection again for the same order
5. Verify the order is skipped with a log message like: "Order TS1234 already processed for fraud detection, skipping"