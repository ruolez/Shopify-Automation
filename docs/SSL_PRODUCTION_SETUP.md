# SSL/TLS Production Setup Guide

## Overview

This guide covers the complete production deployment of the Shopify Multi-Store Order Management System with SSL/TLS encryption using Let's Encrypt on Ubuntu Server 24 LTS.

## Features

- ✅ **Automatic SSL/TLS** with Let's Encrypt
- ✅ **Auto-renewal** of SSL certificates
- ✅ **CORS configuration** for secure cross-origin requests
- ✅ **Nginx reverse proxy** with optimized configuration
- ✅ **PostgreSQL database** with production settings
- ✅ **Redis caching** with persistence
- ✅ **Firewall configuration** (UFW)
- ✅ **Rate limiting** for API protection
- ✅ **Automatic backups** with cron jobs
- ✅ **Health monitoring** and auto-restart
- ✅ **Security headers** (HSTS, CSP, etc.)
- ✅ **WebSocket support** for real-time updates
- ✅ **Cloudflare compatibility** mode

## Prerequisites

### System Requirements

- **OS**: Ubuntu Server 22.04/24.04 LTS
- **RAM**: Minimum 4GB (8GB recommended)
- **CPU**: 2+ cores
- **Storage**: 20GB+ free space
- **Network**: Static IP or domain name

### DNS Configuration

Before running the installation:

1. **Domain Name**: Purchase or have access to a domain
2. **DNS A Record**: Point your domain to your server's IP
   ```
   Type: A
   Name: @ (or subdomain)
   Value: YOUR_SERVER_IP
   TTL: 300
   ```
3. **Wait for propagation**: Usually 5-30 minutes

### Firewall Ports

The installer will configure these automatically:
- **80**: HTTP (redirects to HTTPS)
- **443**: HTTPS
- **22**: SSH (ensure you don't lock yourself out)

## Installation

### Quick Install (Recommended)

```bash
# Download the installation script
wget https://raw.githubusercontent.com/your-repo/install-ssl-production.sh

# Make it executable
chmod +x install-ssl-production.sh

# Run with your domain and email
./install-ssl-production.sh --domain shop.example.com --email admin@example.com
```

### Installation Options

```bash
# Full SSL setup with custom options
./install-ssl-production.sh \
  --domain shop.example.com \
  --email admin@example.com \
  --postgres-password "SecurePass123!" \
  --server-ip 192.168.1.100

# Testing with Let's Encrypt staging (no rate limits)
./install-ssl-production.sh \
  --domain shop.example.com \
  --email admin@example.com \
  --staging

# Cloudflare proxy mode
./install-ssl-production.sh \
  --domain shop.example.com \
  --email admin@example.com \
  --cloudflare

# Non-SSL installation (not recommended for production)
./install-ssl-production.sh \
  --no-ssl \
  --server-ip 192.168.1.100
```

## Post-Installation

### 1. Change Admin Password

```bash
# The installer creates an admin user with a random password
# Login immediately and change it via the UI or API
```

### 2. Configure Shopify Stores

1. Navigate to `https://your-domain.com/admin`
2. Add your Shopify stores
3. Configure webhooks
4. Set up automation rules

### 3. Verify SSL Certificate

```bash
# Check certificate status
sudo certbot certificates

# Test auto-renewal
sudo certbot renew --dry-run

# View certificate details
openssl s_client -connect your-domain.com:443 -servername your-domain.com
```

### 4. Monitor Services

```bash
# View all services
docker compose -f docker-compose.postgres.prod.yml ps

# Check logs
docker compose -f docker-compose.postgres.prod.yml logs -f

# Monitor specific service
docker logs -f shopify_api_prod

# Check system resources
htop
df -h
```

## CORS Configuration

The system automatically configures CORS based on your domain:

### With SSL
```
Origins: https://your-domain.com
Methods: GET, POST, PUT, DELETE, OPTIONS
Credentials: true
```

### Without SSL
```
Origins: http://server-ip, http://server-ip:3000
Methods: GET, POST, PUT, DELETE, OPTIONS
Credentials: true
```

### Custom CORS Settings

Edit `.env` file:
```bash
CORS_ORIGINS=https://your-domain.com,https://app.your-domain.com
CORS_ALLOW_CREDENTIALS=true
CORS_ALLOW_METHODS=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
```

## SSL Management

### Certificate Renewal

Auto-renewal is configured via systemd timer:

```bash
# Check timer status
sudo systemctl status certbot-renew.timer

# View timer schedule
sudo systemctl list-timers | grep certbot

# Manual renewal
sudo /usr/local/bin/certbot-renew.sh

# Force renewal (only if needed)
sudo certbot renew --force-renewal
```

### SSL Security Headers

The nginx configuration includes:
- **HSTS**: Strict-Transport-Security (2 years)
- **CSP**: Content-Security-Policy
- **X-Frame-Options**: SAMEORIGIN
- **X-Content-Type-Options**: nosniff
- **X-XSS-Protection**: 1; mode=block

### SSL Test

Test your SSL configuration:
- https://www.ssllabs.com/ssltest/
- https://securityheaders.com/

## Backup & Recovery

### Automatic Backups

Daily backups at 2 AM:
```bash
# View backup schedule
crontab -l

# Manual backup
sudo /usr/local/bin/shopify-backup.sh

# Backups location
ls -la /backups/shopify/
```

### Restore from Backup

```bash
# Stop services
docker compose -f docker-compose.postgres.prod.yml down

# Restore PostgreSQL
gunzip -c /backups/shopify/20240101_020000/postgres.sql.gz | \
  docker exec -i shopify_postgres_prod psql -U shopify_user shopify_db

# Restore Redis
docker exec shopify_redis_prod redis-cli --rdb /backups/shopify/20240101_020000/redis.rdb

# Restart services
docker compose -f docker-compose.postgres.prod.yml up -d
```

## Monitoring

### Health Checks

```bash
# API health
curl https://your-domain.com/api/health

# Frontend health
curl https://your-domain.com/health

# Database health
docker exec shopify_postgres_prod pg_isready
```

### Monitoring Script

Auto-monitoring every 5 minutes:
```bash
# Check monitoring
sudo /usr/local/bin/shopify-monitor.sh

# View monitoring logs
grep shopify /var/log/syslog
```

### Logs

```bash
# Nginx logs
sudo tail -f /var/log/nginx/shopify_access.log
sudo tail -f /var/log/nginx/shopify_error.log

# Application logs
docker logs -f shopify_api_prod
docker logs -f shopify_worker_prod

# All logs
docker compose -f docker-compose.postgres.prod.yml logs -f
```

## Troubleshooting

### SSL Issues

```bash
# Certificate not obtained
sudo certbot certonly --webroot -w /var/www/certbot -d your-domain.com

# DNS not resolving
dig your-domain.com
nslookup your-domain.com

# Port 80/443 blocked
sudo ufw status
sudo netstat -tlnp | grep -E ':(80|443)'
```

### Service Issues

```bash
# Restart all services
docker compose -f docker-compose.postgres.prod.yml restart

# Rebuild services
docker compose -f docker-compose.postgres.prod.yml up -d --build

# Reset database
docker exec shopify_api_prod python run_all_migrations.py

# Clear Redis cache
docker exec shopify_redis_prod redis-cli FLUSHALL
```

### Performance Issues

```bash
# Check resource usage
docker stats
htop
iostat -x 1

# Optimize PostgreSQL
docker exec shopify_postgres_prod psql -U shopify_user -c "VACUUM ANALYZE;"

# Check nginx connections
sudo nginx -T | grep worker_connections
```

## Security Best Practices

### 1. Firewall Rules

```bash
# Only allow necessary ports
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 2. SSH Hardening

```bash
# Disable root login
sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config

# Use SSH keys only
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config

# Restart SSH
sudo systemctl restart sshd
```

### 3. Database Security

```bash
# Change default passwords
docker exec -it shopify_postgres_prod psql -U shopify_user -c "ALTER USER shopify_user WITH PASSWORD 'NewSecurePassword';"

# Restrict connections
# Edit pg_hba.conf to limit access
```

### 4. Regular Updates

```bash
# System updates
sudo apt update && sudo apt upgrade -y

# Docker updates
docker compose -f docker-compose.postgres.prod.yml pull
docker compose -f docker-compose.postgres.prod.yml up -d

# SSL certificate updates (automatic)
```

## Maintenance Mode

### Enable Maintenance

```bash
# Create maintenance flag
sudo touch /var/www/maintenance.flag

# Remove to disable
sudo rm /var/www/maintenance.flag
```

### Planned Maintenance

```bash
# Notify users (update maintenance.html)
sudo nano /usr/share/nginx/html/errors/maintenance.html

# Enable maintenance
sudo touch /var/www/maintenance.flag

# Perform updates
docker compose -f docker-compose.postgres.prod.yml down
# ... perform maintenance ...
docker compose -f docker-compose.postgres.prod.yml up -d

# Disable maintenance
sudo rm /var/www/maintenance.flag
```

## Performance Optimization

### Nginx Tuning

```nginx
# /etc/nginx/nginx.conf
worker_processes auto;
worker_connections 4096;
keepalive_timeout 65;
keepalive_requests 100;
```

### PostgreSQL Tuning

```sql
-- Check current settings
SHOW max_connections;
SHOW shared_buffers;

-- Optimize for your workload
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET shared_buffers = '256MB';
```

### Redis Optimization

```bash
# Set max memory
docker exec shopify_redis_prod redis-cli CONFIG SET maxmemory 1gb
docker exec shopify_redis_prod redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

## Support

### Logs Collection

```bash
# Create support bundle
mkdir support_bundle
docker compose -f docker-compose.postgres.prod.yml logs > support_bundle/docker.log
sudo journalctl -u nginx > support_bundle/nginx.log
tar czf support_bundle_$(date +%Y%m%d).tar.gz support_bundle/
```

### Common Commands Reference

```bash
# Service management
docker compose -f docker-compose.postgres.prod.yml [up|down|restart|logs|ps]

# Database access
docker exec -it shopify_postgres_prod psql -U shopify_user -d shopify_db

# Redis access
docker exec -it shopify_redis_prod redis-cli

# Nginx reload
sudo nginx -s reload

# SSL renewal
sudo certbot renew

# Backup
sudo /usr/local/bin/shopify-backup.sh

# Monitor
sudo /usr/local/bin/shopify-monitor.sh
```

## License

Copyright © 2024 - Shopify Multi-Store Order Management System