# Date Filtering Issues - Investigation and Fixes

## Issues Identified

### 1. Custom Date Range Timezone Boundary Issue

**Problem**: When users selected a custom date range (e.g., July 7th to July 7th), entries from the previous day were incorrectly included.

**Root Cause**: 
- Frontend created Date objects from date strings using `new Date(customDateFrom)`, which interpreted the date in the user's local timezone
- When converted to UTC with `.toISOString()`, this created timezone boundary shifts
- Example: Selecting "July 7th to July 7th" in Pacific timezone (UTC-7) resulted in:
  - From: `2025-07-07T00:00:00.000Z` (which is 5PM July 6th in Pacific)
  - To: `2025-07-08T06:59:59.000Z` (which is 11:59PM July 7th in Pacific)
- This caused entries from 5PM-11:59PM on July 6th to be included when they shouldn't be

**Fix**: Modified `getDateRange()` function in OrderLogs.tsx to create timezone-aware boundaries:
```typescript
const fromDate = new Date(customDateFrom + 'T00:00:00');
const toDate = new Date(customDateTo + 'T23:59:59');
```

### 2. "This Week" Calculation Inconsistency

**Problem**: "This Week" filter sometimes showed missing entries due to timezone handling inconsistencies.

**Root Cause**: 
- Week start calculation used `today.getDay()` but didn't consistently handle timezone boundaries
- Date objects were created at different times during request processing

**Fix**: Updated week calculation to be more explicit about timezone boundaries:
```typescript
const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
weekStart.setDate(weekStart.getDate() - weekStart.getDay());
weekStart.setHours(0, 0, 0, 0);
```

### 3. Backend Date Processing Redundancy

**Problem**: Backend was modifying the `to_date` by adding 23:59:59, which was redundant after frontend fixes.

**Root Cause**: The backend assumed frontend was only sending date without time, so it added end-of-day time.

**Fix**: Removed the time modification in backend since frontend now sends complete timezone-aware timestamps:
```python
# Before
to_date = to_date.replace(hour=23, minute=59, second=59)

# After  
# Don't modify the to_date since frontend now sends the correct end-of-day time
```

### 4. Reports Page Date Filtering

**Problem**: Reports page had the same timezone boundary issue as OrderLogs.

**Root Cause**: Same pattern of concatenating 'Z' to date strings without timezone awareness.

**Fix**: Updated `getDateParams()` function in Reports.tsx to use proper timezone handling:
```typescript
const fromDate = new Date(startDate + 'T00:00:00');
params.append('start_date', fromDate.toISOString());
```

## Technical Details

### Before Fix (Problematic Flow)
1. User selects "July 7th to July 7th" in Pacific timezone (UTC-7)
2. Frontend sends: `from=2025-07-07T00:00:00.000Z, to=2025-07-08T06:59:59.000Z`
3. This translates to 5PM July 6th to 11:59PM July 7th in Pacific time
4. Entries from late July 6th get incorrectly included

### After Fix (Correct Flow)
1. User selects "July 7th to July 7th" in Pacific timezone (UTC-7)
2. Frontend creates dates in local timezone: `new Date('2025-07-07T00:00:00')` and `new Date('2025-07-07T23:59:59')`
3. Frontend sends: `from=2025-07-07T07:00:00.000Z, to=2025-07-08T06:59:59.000Z`
4. This correctly translates to midnight July 7th to 11:59PM July 7th in Pacific time
5. Only entries from July 7th are included

## Files Modified

1. **frontend/src/pages/OrderLogs.tsx**
   - Fixed `getDateRange()` function for all date filter types
   - Improved timezone handling for custom dates, today, week, month, year filters

2. **frontend/src/pages/Reports.tsx**
   - Fixed `getDateParams()` function for consistent timezone handling

3. **backend/main.py**
   - Removed redundant time modification in order-logs endpoint
   - Fixed both main query and helper function date parsing

4. **frontend/src/utils/dateFormat.ts**
   - Removed debug logging (cleanup)

## Validation

### Test Results (Pacific Timezone, UTC-7)
- **Custom Range July 7th-7th**: ✅ Only includes entries from July 7th 00:00 to 23:59 in Pacific time
- **This Week**: ✅ Starts from Sunday 00:00 in Pacific time
- **Today**: ✅ Includes only current day 00:00 to 23:59 in Pacific time

### Expected Behavior
- Date filters now respect user's local timezone
- Custom date ranges include only the selected dates in user's timezone
- "This Week" starts from Sunday in user's timezone
- No more entries from wrong dates appearing in filtered results

## Impact

- **User Experience**: Date filtering now works intuitively - selecting a date range includes only entries from those dates in the user's timezone
- **Data Accuracy**: Eliminates false inclusions of entries from adjacent dates
- **Consistency**: All date filtering (OrderLogs and Reports) now uses the same timezone-aware logic
- **Backward Compatibility**: Existing data and API contracts remain unchanged

## Prevention

- All future date filtering implementations should use timezone-aware Date object creation
- Pattern: `new Date(dateString + 'T00:00:00')` for start of day, `new Date(dateString + 'T23:59:59')` for end of day
- Avoid concatenating 'Z' directly to date strings without timezone consideration
- Always test date filtering across timezone boundaries