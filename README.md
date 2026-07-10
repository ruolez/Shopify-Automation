# Shopify Multi-Store Order Management

## Quick start (recommended)

`install.sh` is the unified installer — it prompts for everything (server
address, Shopify OAuth keys, admin password) and auto-generates all secrets,
so there is no manual `.env` editing:

```bash
git clone https://github.com/ruolez/Shopify-Automation.git
cd Shopify-Automation
sudo ./install.sh
```

Menu options:
1. **Install** — fresh installation (prompts for keys, generates secrets, builds and starts the stack, runs migrations, creates the admin account)
2. **Update from GitHub** — backs up `.env` + PostgreSQL, `git pull`, rebuild, pending migrations, then prunes unused Docker images/build cache
3. **Backup** — settings + database dump into `backups/<timestamp>/`
4. **Remove** — stops the stack; optionally deletes data volumes (typed confirmation) and images

For HTTPS with Let's Encrypt use `install-ssl-production.sh` (below).
`update.sh` and `update-with-migration.sh` are superseded by `./install.sh` → Update.

---

⏺ Summary

  I've created a comprehensive production installation script for Ubuntu Server 24 with SSL/TLS support using Let's Encrypt. Here's what was created:

  Main Files Created:

  1. install-ssl-production.sh - Complete production installation script with:
    - Automatic SSL certificate generation via Let's Encrypt
    - Auto-renewal setup using systemd timers
    - Full CORS configuration
    - Nginx reverse proxy with optimized settings
    - PostgreSQL and Redis setup
    - Firewall configuration (UFW)
    - System optimization and monitoring
    - Backup automation
  2. nginx/nginx.prod.conf - Production-ready nginx configuration with:
    - SSL/TLS best practices
    - Rate limiting zones
    - Cache configuration
    - Security headers
    - WebSocket support
  3. nginx/app-locations.conf - Shared location blocks for:
    - API endpoints with proper CORS
    - Authentication endpoints with stricter rate limiting
    - Webhook endpoints for Shopify
    - Static file serving with caching
    - Frontend proxying
  4. Error pages in nginx/errors/:
    - 404.html - Not found page
    - 50x.html - Server error page
    - maintenance.html - Maintenance mode page
  5. SSL_PRODUCTION_SETUP.md - Complete documentation

  Key Features:

  - SSL/TLS with Let's Encrypt: Automatic certificate generation and renewal
  - CORS Configuration: Properly configured for both HTTP and HTTPS
  - Security: Firewall rules, rate limiting, security headers (HSTS, CSP, etc.)
  - Performance: Nginx caching, gzip compression, connection pooling
  - Monitoring: Health checks, automatic service monitoring and restart
  - Backups: Automated daily backups with retention policy
  - Cloudflare Support: Compatible with Cloudflare proxy
  - Maintenance Mode: Easy enable/disable for updates

  Usage:

  # Basic installation with SSL
  ./install-ssl-production.sh --domain shop.example.com --email admin@example.com

  # With all options
  ./install-ssl-production.sh \
    --domain shop.example.com \
    --email admin@example.com \
    --postgres-password "SecurePassword" \
    --server-ip 1.2.3.4

  # For testing (uses Let's Encrypt staging)
  ./install-ssl-production.sh --domain shop.example.com --email admin@example.com --staging

  # With Cloudflare
  ./install-ssl-production.sh --domain shop.example.com --email admin@example.com --cloudflare

  The script handles everything from system dependencies to SSL setup, database initialization, and monitoring configuration, making it a complete one-command deployment solution for production
  environments.

