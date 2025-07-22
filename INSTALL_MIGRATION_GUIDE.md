# Shopify Automation - Installation & Migration Guide

## Overview

The updated `install-prod.sh` script now includes comprehensive support for database migrations, ensuring smooth updates when new features are added to the system.

## Key Improvements

### 1. **Smart Admin User Creation**
- Fixed redundant table creation in `init_admin.py`
- Admin user creation no longer fails if tables already exist
- Tables are only created when the script runs standalone

### 2. **Automatic Migration Support**
- New `run_all_migrations.py` script handles all database schema updates
- Migrations are tracked in a `schema_migrations` table
- Migrations run automatically during installation with `--keep-db` option

### 3. **Schema Version Tracking**
- New `check_schema_version.py` script shows current schema status
- Easy way to check which migrations have been applied
- Clear visibility of pending migrations

## Installation Scenarios

### Fresh Installation
```bash
./install-prod.sh
# or
./install-prod.sh --clean
```
- Creates all tables with latest schema
- No migrations needed
- Initializes admin user

### Update with Database Preservation
```bash
./install-prod.sh --keep-db
```
- Preserves existing data
- Automatically checks for pending migrations
- Applies any new schema changes
- Safe for production updates

### Manual Migration Check
```bash
docker exec shopify_api python check_schema_version.py
```
- Shows applied migrations
- Lists pending migrations
- Displays database location

### Manual Migration Run
```bash
docker exec shopify_api python run_all_migrations.py
```
- Applies all pending migrations
- Shows progress and results
- Safe to run multiple times

## Migration List

Current migrations in order:
1. `add_delay_ms_to_rules` - Adds delay_ms column to processing rules
2. `add_timezone_to_settings` - Adds timezone and date_format columns
3. `add_fraud_sync_enabled` - Adds fraud sync control to settings
4. `add_fraud_detection_rules` - Creates fraud detection rules table
5. `add_duplicate_detection_days_column` - Adds duplicate detection window
6. `add_delivery_analytics_column` - Adds delivery analytics to fraud analysis
7. `add_days_since_last_delivery_column` - Adds delivery tracking metric
8. `add_user_id_to_task_status` - Links task status to users

## Testing the Updated Script

### Test 1: Fresh Installation
1. Remove existing installation: `docker compose down -v`
2. Run: `./install-prod.sh`
3. Verify:
   - All services start successfully
   - Database is created with all tables
   - Admin user can log in
   - No migration warnings

### Test 2: Update Existing Installation
1. Have an existing installation running
2. Run: `./install-prod.sh --keep-db`
3. Verify:
   - Existing data is preserved
   - Migrations are detected and applied
   - Services restart successfully
   - Schema version shows all migrations applied

### Test 3: Migration Status Check
1. Run: `docker exec shopify_api python check_schema_version.py`
2. Verify:
   - Shows correct applied migrations
   - No pending migrations after update
   - Displays database path

### Test 4: Backup and Restore
1. Run installation with backup: `./install-prod.sh --keep-db`
2. Check backup created in `backups/` directory
3. Verify restore works if needed

## Troubleshooting

### Migration Fails
- Check logs: `docker logs shopify_api`
- Manually run migration: `docker exec shopify_api python run_all_migrations.py`
- Check specific migration files in `/backend/migrations/`

### Admin User Issues
- If admin creation fails, run: `docker exec shopify_api python init_admin.py`
- Default credentials: admin/admin
- Change password immediately after first login

### Database Not Found
- Check if volume exists: `docker volume ls | grep sqlite`
- Verify database path in container: `docker exec shopify_api ls -la /app/data/`

## Production Deployment

For production updates:
1. Always backup first: `./update.sh --backup-only`
2. Test update on staging environment
3. Run update: `./install-prod.sh --keep-db`
4. Verify schema: `docker exec shopify_api python check_schema_version.py`
5. Monitor logs: `docker compose logs -f`

## Notes

- Migrations are idempotent - safe to run multiple times
- Failed migrations don't block the installation (warning shown)
- Each migration checks if changes already exist before applying
- Migration order is important and defined in `MIGRATION_ORDER`

## Future Migrations

To add new migrations:
1. Create migration file in `/backend/migrations/`
2. Add to `MIGRATION_ORDER` in `run_all_migrations.py`
3. Follow existing migration patterns for safety checks
4. Test on development before production