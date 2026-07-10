# PostgreSQL Setup Guide for Shopify Multi-Store Order Management System

## Overview

This guide provides comprehensive instructions for setting up the Shopify Multi-Store Order Management System with PostgreSQL as the primary database.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Installation Scripts](#installation-scripts)
3. [Database Architecture](#database-architecture)
4. [Migration from SQLite](#migration-from-sqlite)
5. [Backup and Restore](#backup-and-restore)
6. [Troubleshooting](#troubleshooting)
7. [Production Deployment](#production-deployment)

## Quick Start

### Prerequisites

- Docker and Docker Compose v2 installed
- At least 4GB RAM (8GB recommended for production)
- 20GB free disk space
- Ports available: 3000, 5432, 6379, 8000

### Basic Installation

```bash
# Clone the repository (if not already done)
git clone <repository-url>
cd shopify-automation

# Run the complete PostgreSQL installation
./install-postgres-complete.sh

# For production deployment
./install-postgres-complete.sh --production --ip YOUR_SERVER_IP
```

### Verify Installation

```bash
# Run the test suite
./test-postgres-installation.sh

# Check service status
docker compose -f docker-compose.postgres.yml ps

# View logs
docker compose -f docker-compose.postgres.yml logs -f
```

## Installation Scripts

### 1. install-postgres-complete.sh

The main installation script that handles everything:

**Features:**
- Automatic Docker and Docker Compose installation
- PostgreSQL 15 setup with optimized configuration
- Database schema initialization
- Admin user creation
- Migration from SQLite support
- Backup and restore capabilities

**Usage:**
```bash
./install-postgres-complete.sh [options]

Options:
  --ip <IP>                 Server IP address (default: localhost)
  --clean                   Clean installation (removes existing data)
  --production              Use production configuration
  --postgres-password <pwd> Set PostgreSQL password
  --admin-password <pwd>    Set admin user password
  --migrate-from-sqlite     Migrate from SQLite database
  --help                    Show help message
```

### 2. test-postgres-installation.sh

Comprehensive test suite to verify installation:

**Tests:**
- Docker services status
- PostgreSQL connectivity
- Database schema verification
- API endpoints
- Admin user existence
- Performance checks

**Usage:**
```bash
./test-postgres-installation.sh
```

## Database Architecture

### Connection Configuration

The system uses PostgreSQL 15 with the following default configuration:

```yaml
Database: shopify_db
Username: shopify_user
Host: postgres (container) / localhost (external)
Port: 5432
```

### Connection Pool Settings

Optimized for production workloads:

```env
DB_POOL_SIZE=20           # Base connection pool size
DB_MAX_OVERFLOW=40        # Maximum overflow connections
DB_POOL_TIMEOUT=30        # Connection timeout in seconds
DB_POOL_RECYCLE=3600      # Recycle connections after 1 hour
```

### Database Schema

The database includes the following main tables:

- **users** - Application users
- **stores** - Shopify store configurations
- **rules** - Processing rules
- **order_logs** - Order processing history
- **processed_orders** - Tracking of processed orders
- **processed_orders_archive** - Archived processed orders
- **task_status** - Background task tracking
- **settings** - User settings
- **admin_users** - Admin panel users
- **admin_audit_logs** - Admin activity logs
- **fraud_analyses** - Fraud detection results
- **fraud_analyses_archive** - Archived fraud analyses
- **schema_migrations** - Database migration tracking

### PostgreSQL Extensions

The following extensions are enabled:

- **uuid-ossp** - UUID generation support
- **pg_stat_statements** - Query performance monitoring

## Migration from SQLite

### Automatic Migration

The installation script supports automatic migration from SQLite:

```bash
# Migrate from default SQLite location
./install-postgres-complete.sh --migrate-from-sqlite

# Migrate from custom SQLite location
./install-postgres-complete.sh --migrate-from-sqlite /path/to/sqlite.db
```

### Manual Migration

If you need to migrate manually:

```bash
# 1. Backup SQLite database
cp backend/app.db backup.db

# 2. Start PostgreSQL
docker compose -f docker-compose.postgres.yml up -d postgres

# 3. Run migration script
docker exec shopify_api python migrations/sqlite_to_postgres.py
```

### Data Integrity

The migration process:
1. Creates a backup of the SQLite database
2. Transfers all tables with data integrity checks
3. Preserves foreign key relationships
4. Maintains created_at timestamps
5. Validates row counts after migration

## Backup and Restore

### Creating Backups

#### Automated Backup
```bash
# Create timestamped backup
docker exec shopify_postgres pg_dump -U shopify_user shopify_db | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz
```

#### Manual Backup via Admin Panel
1. Navigate to http://localhost:3000/admin
2. Go to Database Management
3. Click "Download Backup"

### Restoring Backups

#### From SQL File
```bash
# Restore from gzipped backup
gunzip -c backup.sql.gz | docker exec -i shopify_postgres psql -U shopify_user shopify_db

# Restore from plain SQL
docker exec -i shopify_postgres psql -U shopify_user shopify_db < backup.sql
```

#### Via Admin Panel
1. Navigate to Database Management
2. Upload the backup file (.sql or .sql.gz)
3. Confirm restoration

### Scheduled Backups

Create a cron job for automated backups:

```bash
# Add to crontab
0 2 * * * /opt/shopify-automation/backup.sh

# backup.sh content:
#!/bin/bash
BACKUP_DIR="/backups/postgres"
mkdir -p $BACKUP_DIR
docker exec shopify_postgres pg_dump -U shopify_user shopify_db | \
  gzip > $BACKUP_DIR/backup_$(date +%Y%m%d_%H%M%S).sql.gz
# Keep only last 30 days of backups
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete
```

## Troubleshooting

### Common Issues and Solutions

#### 1. PostgreSQL Container Won't Start

**Symptoms:**
- Container exits immediately
- Health check fails

**Solutions:**
```bash
# Check logs
docker logs shopify_postgres

# Fix permission issues
docker volume rm shopify-automation_postgres_data
docker compose -f docker-compose.postgres.yml up -d

# Check port conflicts
lsof -i :5432
```

#### 2. Connection Refused Errors

**Symptoms:**
- API can't connect to PostgreSQL
- "connection refused" in logs

**Solutions:**
```bash
# Verify PostgreSQL is running
docker exec shopify_postgres pg_isready

# Check environment variables
docker exec shopify_api env | grep DATABASE_URL

# Restart services in correct order
docker compose -f docker-compose.postgres.yml restart postgres
sleep 10
docker compose -f docker-compose.postgres.yml restart api worker scheduler
```

#### 3. Migration Failures

**Symptoms:**
- Schema version mismatch
- Missing columns errors

**Solutions:**
```bash
# Force run all migrations
docker exec shopify_api python run_all_migrations.py --force

# Reset migration tracking
docker exec shopify_postgres psql -U shopify_user -d shopify_db -c \
  "DELETE FROM schema_migrations; DROP TABLE IF EXISTS schema_migrations;"
docker exec shopify_api python run_all_migrations.py
```

#### 4. Performance Issues

**Symptoms:**
- Slow queries
- High CPU usage

**Solutions:**
```bash
# Check slow queries
docker exec shopify_postgres psql -U shopify_user -d shopify_db -c \
  "SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;"

# Run VACUUM and ANALYZE
docker exec shopify_postgres psql -U shopify_user -d shopify_db -c "VACUUM ANALYZE;"

# Increase connection pool
# Edit .env file:
DB_POOL_SIZE=40
DB_MAX_OVERFLOW=60

# Restart services
docker compose -f docker-compose.postgres.yml restart
```

### Diagnostic Commands

```bash
# Check database size
docker exec shopify_postgres psql -U shopify_user -d shopify_db -c \
  "SELECT pg_size_pretty(pg_database_size('shopify_db'));"

# List all tables with row counts
docker exec shopify_postgres psql -U shopify_user -d shopify_db -c \
  "SELECT schemaname,tablename,n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"

# Check active connections
docker exec shopify_postgres psql -U shopify_user -d shopify_db -c \
  "SELECT count(*) FROM pg_stat_activity WHERE datname='shopify_db';"

# View current configuration
docker exec shopify_postgres psql -U shopify_user -d shopify_db -c "SHOW ALL;"
```

## Production Deployment

### System Requirements

**Minimum:**
- 4 CPU cores
- 8GB RAM
- 50GB SSD storage
- Ubuntu 20.04+ or similar

**Recommended:**
- 8 CPU cores
- 16GB RAM
- 100GB SSD storage
- Dedicated database server

### Production Installation

```bash
# Run as root or with sudo
sudo ./install-postgres-complete.sh \
  --production \
  --ip YOUR_PUBLIC_IP \
  --postgres-password "$(openssl rand -base64 32)" \
  --admin-password "$(openssl rand -base64 16)"
```

### Security Hardening

#### 1. Firewall Configuration

```bash
# Allow only necessary ports
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw enable

# PostgreSQL should NOT be exposed externally
# Access only through Docker network
```

#### 2. SSL/TLS Setup

```bash
# Install certbot
apt-get install certbot

# Get SSL certificate
certbot certonly --standalone -d your-domain.com

# Update nginx configuration to use SSL
# Edit nginx/nginx.conf to include SSL settings
```

#### 3. PostgreSQL Security

```sql
-- Limit connections
ALTER DATABASE shopify_db CONNECTION LIMIT 100;

-- Set password complexity
ALTER USER shopify_user PASSWORD 'complex-password-here';

-- Revoke unnecessary privileges
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

#### 4. Environment Variables

```bash
# Use strong passwords (minimum 32 characters)
POSTGRES_PASSWORD=$(openssl rand -base64 32)
SECRET_KEY=$(openssl rand -hex 64)
JWT_SECRET_KEY=$(openssl rand -hex 64)

# Store secrets securely
# Consider using Docker secrets or environment management tools
```

### Monitoring

#### 1. Database Monitoring

```bash
# Create monitoring script
cat > /usr/local/bin/monitor-postgres.sh << 'EOF'
#!/bin/bash
# Check PostgreSQL status
if ! docker exec shopify_postgres pg_isready -U shopify_user; then
    echo "PostgreSQL is down" | mail -s "Alert: PostgreSQL Down" admin@example.com
fi

# Check disk usage
USAGE=$(df /var/lib/docker | tail -1 | awk '{print $5}' | sed 's/%//')
if [ $USAGE -gt 80 ]; then
    echo "Disk usage is at ${USAGE}%" | mail -s "Alert: High Disk Usage" admin@example.com
fi
EOF

chmod +x /usr/local/bin/monitor-postgres.sh

# Add to crontab
*/5 * * * * /usr/local/bin/monitor-postgres.sh
```

#### 2. Application Monitoring

```bash
# Health check endpoint
curl http://localhost:8000/health

# Metrics endpoint (if implemented)
curl http://localhost:8000/metrics
```

### Scaling Considerations

#### 1. Database Optimization

```sql
-- Add indexes for common queries
CREATE INDEX idx_orders_created_at ON processed_orders(created_at);
CREATE INDEX idx_rules_store_id ON rules(store_id);
CREATE INDEX idx_logs_status ON order_logs(status);

-- Partition large tables
-- Consider partitioning processed_orders by month
```

#### 2. Connection Pooling

For high-traffic deployments, consider using PgBouncer:

```yaml
# docker-compose.postgres.yml addition
pgbouncer:
  image: pgbouncer/pgbouncer
  environment:
    - DATABASES_HOST=postgres
    - DATABASES_PORT=5432
    - DATABASES_DBNAME=shopify_db
    - POOL_MODE=transaction
    - MAX_CLIENT_CONN=1000
    - DEFAULT_POOL_SIZE=50
```

#### 3. Read Replicas

For read-heavy workloads, set up read replicas:

```bash
# Configure streaming replication
# On primary:
docker exec shopify_postgres psql -U postgres -c \
  "CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replica_password';"

# Set up standby server with replication
```

## Maintenance

### Regular Maintenance Tasks

```bash
# Weekly: VACUUM and ANALYZE
docker exec shopify_postgres psql -U shopify_user -d shopify_db -c "VACUUM ANALYZE;"

# Monthly: REINDEX
docker exec shopify_postgres psql -U shopify_user -d shopify_db -c "REINDEX DATABASE shopify_db;"

# Quarterly: Full backup and test restore
./backup.sh
# Test restore on staging environment
```

### Update Procedure

```bash
# 1. Backup current state
docker exec shopify_postgres pg_dump -U shopify_user shopify_db > pre_update_backup.sql

# 2. Stop services
docker compose -f docker-compose.postgres.yml stop

# 3. Update code
git pull origin main

# 4. Rebuild and restart
docker compose -f docker-compose.postgres.yml build
docker compose -f docker-compose.postgres.yml up -d

# 5. Run migrations
docker exec shopify_api python run_all_migrations.py

# 6. Verify
./test-postgres-installation.sh
```

## Support and Resources

### Documentation

- [PostgreSQL Documentation](https://www.postgresql.org/docs/15/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)

### Log Files

```bash
# Application logs
tail -f logs/app.log

# PostgreSQL logs
docker logs shopify_postgres

# All service logs
docker compose -f docker-compose.postgres.yml logs -f
```

### Getting Help

1. Check the troubleshooting section above
2. Review log files for specific errors
3. Run the test suite to identify issues
4. Check PostgreSQL connection and credentials
5. Verify Docker services are running

## Appendix

### Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection string | postgresql://... |
| POSTGRES_PASSWORD | Database password | (generated) |
| POSTGRES_DB | Database name | shopify_db |
| POSTGRES_USER | Database username | shopify_user |
| DB_POOL_SIZE | Connection pool size | 20 |
| DB_MAX_OVERFLOW | Max overflow connections | 40 |
| DB_POOL_TIMEOUT | Connection timeout (seconds) | 30 |
| DB_POOL_RECYCLE | Connection recycle time | 3600 |
| SECRET_KEY | Application secret key | (generated) |
| JWT_SECRET_KEY | JWT signing key | (generated) |
| REDIS_URL | Redis connection string | redis://redis:6379/0 |

### Docker Commands Reference

```bash
# View running containers
docker ps

# View all containers (including stopped)
docker ps -a

# View logs for specific service
docker logs shopify_postgres
docker logs shopify_api

# Execute command in container
docker exec shopify_postgres psql -U shopify_user -d shopify_db

# Stop all services
docker compose -f docker-compose.postgres.yml down

# Stop and remove volumes (CAUTION: deletes data)
docker compose -f docker-compose.postgres.yml down -v

# Rebuild specific service
docker compose -f docker-compose.postgres.yml build api

# Scale workers
docker compose -f docker-compose.postgres.yml up -d --scale worker=4
```

### PostgreSQL Commands Reference

```sql
-- Connect to database
\c shopify_db

-- List all tables
\dt

-- Describe table structure
\d table_name

-- Show table sizes
SELECT 
    schemaname AS table_schema,
    tablename AS table_name,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Show active connections
SELECT pid, usename, application_name, client_addr, state
FROM pg_stat_activity
WHERE datname = 'shopify_db';

-- Kill a connection
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'shopify_db' AND pid <> pg_backend_pid();

-- Check index usage
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;
```

---

Last Updated: 2024
Version: 3.0.0