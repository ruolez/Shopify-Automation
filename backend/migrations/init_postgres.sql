-- PostgreSQL Initialization Script
-- Creates necessary extensions and configurations

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- For UUID generation

-- Set default timezone
SET timezone = 'UTC';

-- Configure statement timeout (30 seconds default, can be overridden per session)
ALTER DATABASE shopify_db SET statement_timeout = '30s';

-- Configure connection limits
ALTER DATABASE shopify_db CONNECTION LIMIT -1;

-- Create indexes for better performance (will be created after tables are created)
-- These will be added by SQLAlchemy when creating tables

-- Maintenance settings
ALTER DATABASE shopify_db SET autovacuum = on;
ALTER DATABASE shopify_db SET autovacuum_vacuum_scale_factor = 0.1;
ALTER DATABASE shopify_db SET autovacuum_analyze_scale_factor = 0.05;

-- Log slow queries (queries taking more than 1 second)
ALTER DATABASE shopify_db SET log_min_duration_statement = 1000;

-- Grant necessary permissions
GRANT ALL PRIVILEGES ON DATABASE shopify_db TO shopify_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO shopify_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO shopify_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO shopify_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO shopify_user;