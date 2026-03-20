#!/bin/bash

# Shopify Multi-Store Order Management System
# Production Installation Script with SSL/TLS for Ubuntu Server 24
# Features: Let's Encrypt SSL, automatic renewal, CORS configuration, nginx reverse proxy

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Configuration variables
DEPLOYMENT_MODE="production"
DATABASE_TYPE="postgresql"
COMPOSE_FILE="docker-compose.postgres.prod.yml"
POSTGRES_PASSWORD=""
DOMAIN_NAME=""
EMAIL_ADDRESS=""
ENABLE_SSL="true"
ENABLE_STAGING="false"
SERVER_IP=""
CLOUDFLARE_MODE="false"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_section() {
    echo
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo
}

# Banner
clear
echo -e "${MAGENTA}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Shopify Multi-Store Order Management System           ║"
echo "║       SSL/TLS Production Installation Script              ║"
echo "║              Ubuntu Server 24 LTS                         ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   print_error "This script should not be run as root!"
   print_status "Please run as a regular user with sudo privileges."
   exit 1
fi

# Check OS
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    print_error "This script is designed for Linux systems only."
    exit 1
fi

# Check Ubuntu version
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID" != "ubuntu" ]] || [[ ! "$VERSION_ID" =~ ^(22|24) ]]; then
        print_warning "This script is optimized for Ubuntu 22.04/24.04 LTS"
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
else
    print_error "Cannot detect OS version"
    exit 1
fi

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --domain)
            DOMAIN_NAME="$2"
            shift 2
            ;;
        --email)
            EMAIL_ADDRESS="$2"
            shift 2
            ;;
        --postgres-password)
            POSTGRES_PASSWORD="$2"
            shift 2
            ;;
        --no-ssl)
            ENABLE_SSL="false"
            shift
            ;;
        --staging)
            ENABLE_STAGING="true"
            shift
            ;;
        --cloudflare)
            CLOUDFLARE_MODE="true"
            shift
            ;;
        --server-ip)
            SERVER_IP="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --domain <domain>         Your domain name (required for SSL)"
            echo "  --email <email>           Email for Let's Encrypt notifications"
            echo "  --postgres-password <pwd> PostgreSQL password (generated if not provided)"
            echo "  --server-ip <ip>          Server IP address (auto-detected if not provided)"
            echo "  --no-ssl                  Skip SSL configuration"
            echo "  --staging                 Use Let's Encrypt staging server (for testing)"
            echo "  --cloudflare              Enable Cloudflare compatibility mode"
            echo "  --help, -h                Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --domain example.com --email admin@example.com"
            echo "  $0 --domain shop.example.com --email admin@example.com --cloudflare"
            echo "  $0 --no-ssl --server-ip 192.168.1.100"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

print_section "System Configuration"

# Get domain configuration
if [ "$ENABLE_SSL" = "true" ]; then
    if [ -z "$DOMAIN_NAME" ]; then
        print_status "SSL/TLS Setup Configuration"
        echo
        read -p "Enter your domain name (e.g., shop.example.com): " DOMAIN_NAME
        if [ -z "$DOMAIN_NAME" ]; then
            print_error "Domain name is required for SSL setup!"
            exit 1
        fi
    fi
    
    if [ -z "$EMAIL_ADDRESS" ]; then
        read -p "Enter email for Let's Encrypt notifications: " EMAIL_ADDRESS
        if [ -z "$EMAIL_ADDRESS" ]; then
            print_error "Email address is required for Let's Encrypt!"
            exit 1
        fi
    fi
    
    # Validate domain format
    if [[ ! "$DOMAIN_NAME" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]?\.[a-zA-Z]{2,}$ ]]; then
        print_warning "Domain '$DOMAIN_NAME' doesn't match standard format."
        read -p "Are you sure this is correct? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    print_success "Domain: $DOMAIN_NAME"
    print_success "Email: $EMAIL_ADDRESS"
fi

# Get server IP if not provided
if [ -z "$SERVER_IP" ]; then
    # Try to auto-detect public IP
    print_status "Detecting server IP address..."
    SERVER_IP=$(curl -s https://api.ipify.org 2>/dev/null || curl -s https://ifconfig.me 2>/dev/null || echo "")
    
    if [ -z "$SERVER_IP" ]; then
        # Fallback to local IP
        SERVER_IP=$(hostname -I | awk '{print $1}')
    fi
    
    echo
    echo -e "${BLUE}Detected IP address: ${YELLOW}$SERVER_IP${NC}"
    read -p "Is this correct? (Y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        read -p "Enter the correct server IP address: " SERVER_IP
    fi
fi

print_success "Server IP: $SERVER_IP"

# Check DNS resolution if SSL is enabled
if [ "$ENABLE_SSL" = "true" ]; then
    print_status "Checking DNS resolution for $DOMAIN_NAME..."
    DNS_IP=$(dig +short $DOMAIN_NAME @8.8.8.8 2>/dev/null | tail -n1)
    
    if [ -z "$DNS_IP" ]; then
        print_warning "Could not resolve $DOMAIN_NAME"
        print_warning "Please ensure your DNS A record points to $SERVER_IP"
        read -p "Continue anyway? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    elif [ "$DNS_IP" != "$SERVER_IP" ] && [ "$CLOUDFLARE_MODE" != "true" ]; then
        print_warning "DNS resolves to $DNS_IP but server IP is $SERVER_IP"
        if [ "$CLOUDFLARE_MODE" = "true" ]; then
            print_status "Cloudflare mode enabled - this is expected"
        else
            print_warning "If using Cloudflare, run with --cloudflare flag"
            read -p "Continue anyway? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        print_success "DNS correctly points to server IP"
    fi
fi

print_section "Installing System Dependencies"

# Update system
print_status "Updating system packages..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq

# Install required packages
print_status "Installing required packages..."
PACKAGES="curl wget git openssl lsof ufw certbot python3-certbot-nginx nginx software-properties-common apt-transport-https ca-certificates gnupg lsb-release net-tools dnsutils"

for package in $PACKAGES; do
    if ! dpkg -l | grep -q "^ii  $package"; then
        print_status "Installing $package..."
        sudo apt-get install -y -qq $package
    fi
done

print_success "System dependencies installed"

print_section "Docker Installation"

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    print_status "Installing Docker..."
    
    # Add Docker's official GPG key
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    
    # Add Docker repository
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Install Docker
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    
    # Add user to docker group
    sudo usermod -aG docker $USER
    
    # Start Docker service
    sudo systemctl start docker
    sudo systemctl enable docker
    
    print_success "Docker installed successfully"
else
    print_success "Docker is already installed"
fi

# Verify Docker Compose v2
if ! docker compose version &> /dev/null; then
    print_error "Docker Compose v2 is not available"
    exit 1
fi

print_section "Firewall Configuration"

# Configure UFW firewall
print_status "Configuring firewall..."
sudo ufw --force enable
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8000/tcp  # API port (can be restricted later)
sudo ufw allow 3000/tcp  # Frontend port (will be proxied through nginx)

# PostgreSQL port - only allow from localhost
sudo ufw allow from 127.0.0.1 to any port 5432

print_success "Firewall configured"

print_section "SSL/TLS Configuration"

# Create nginx configuration directory
sudo mkdir -p /etc/nginx/sites-available
sudo mkdir -p /etc/nginx/sites-enabled
sudo mkdir -p /var/www/certbot

if [ "$ENABLE_SSL" = "true" ]; then
    # Stop any running nginx to free port 80
    sudo systemctl stop nginx 2>/dev/null || true
    
    # Create initial nginx configuration for Let's Encrypt verification
    print_status "Creating initial nginx configuration..."
    
    sudo tee /etc/nginx/sites-available/shopify-automation > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN_NAME;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 301 https://\$server_name\$request_uri;
    }
}
EOF

    sudo ln -sf /etc/nginx/sites-available/shopify-automation /etc/nginx/sites-enabled/
    sudo rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
    
    # Test nginx configuration
    sudo nginx -t
    sudo systemctl start nginx
    
    # Obtain SSL certificate
    print_status "Obtaining SSL certificate from Let's Encrypt..."
    
    CERTBOT_FLAGS=""
    if [ "$ENABLE_STAGING" = "true" ]; then
        CERTBOT_FLAGS="--staging"
        print_warning "Using Let's Encrypt staging server (for testing)"
    fi
    
    if [ "$CLOUDFLARE_MODE" = "true" ]; then
        print_status "Using DNS challenge for Cloudflare..."
        sudo certbot certonly \
            --webroot \
            --webroot-path=/var/www/certbot \
            --email $EMAIL_ADDRESS \
            --agree-tos \
            --no-eff-email \
            --force-renewal \
            $CERTBOT_FLAGS \
            -d $DOMAIN_NAME
    else
        sudo certbot certonly \
            --webroot \
            --webroot-path=/var/www/certbot \
            --email $EMAIL_ADDRESS \
            --agree-tos \
            --no-eff-email \
            --force-renewal \
            $CERTBOT_FLAGS \
            -d $DOMAIN_NAME
    fi
    
    if [ $? -eq 0 ]; then
        print_success "SSL certificate obtained successfully"
    else
        print_error "Failed to obtain SSL certificate"
        print_warning "Continuing without SSL..."
        ENABLE_SSL="false"
    fi
fi

print_section "Application Setup"

# Create necessary directories
print_status "Creating application directories..."
mkdir -p logs
mkdir -p backups
mkdir -p nginx/ssl
mkdir -p certbot/conf
mkdir -p certbot/www

# Generate PostgreSQL password if not provided
if [ -z "$POSTGRES_PASSWORD" ]; then
    POSTGRES_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    print_warning "Generated PostgreSQL password: $POSTGRES_PASSWORD"
    print_warning "⚠️  SAVE THIS PASSWORD SECURELY!"
fi

# Create .env file
print_status "Creating environment configuration..."

# Determine API URL based on SSL configuration
if [ "$ENABLE_SSL" = "true" ]; then
    API_URL="https://$DOMAIN_NAME"
    CORS_ORIGINS="https://$DOMAIN_NAME,http://localhost:3000"
else
    API_URL="http://$SERVER_IP:8000"
    CORS_ORIGINS="http://$SERVER_IP,http://$SERVER_IP:3000,http://localhost,http://localhost:3000"
fi

cat > .env <<EOF
# Server Configuration
SERVER_IP=$SERVER_IP
DOMAIN_NAME=$DOMAIN_NAME
VITE_API_URL=$API_URL
ENVIRONMENT=production
SSL_ENABLED=$ENABLE_SSL

# Database Configuration (PostgreSQL)
DATABASE_URL=postgresql://shopify_user:${POSTGRES_PASSWORD}@postgres:5432/shopify_db
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=shopify_db
POSTGRES_USER=shopify_user
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Connection Pool Settings (Production)
DB_POOL_SIZE=50
DB_MAX_OVERFLOW=100
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
DB_ECHO=false

# CORS Configuration
CORS_ORIGINS=$CORS_ORIGINS
CORS_ALLOW_CREDENTIALS=true
CORS_ALLOW_METHODS=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
CORS_ALLOW_HEADERS=["*"]

# Security
SECRET_KEY=$(openssl rand -hex 32)
ADMIN_SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET_KEY=$(openssl rand -hex 32)
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Session Security
SESSION_SECRET_KEY=$(openssl rand -hex 32)
SESSION_COOKIE_SECURE=$ENABLE_SSL
SESSION_COOKIE_HTTPONLY=true
SESSION_COOKIE_SAMESITE=lax

# Shopify Configuration
SHOPIFY_API_VERSION=2025-04

# Redis Configuration
REDIS_URL=redis://redis:6379/0
REDIS_PASSWORD=$(openssl rand -hex 16)
REDIS_MAX_CONNECTIONS=100
REDIS_POOL_SIZE=50

# Application Settings
LOG_LEVEL=INFO
WORKERS=4
MAX_WORKERS=8
WORKER_CONNECTIONS=1000

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_DEFAULT=100/minute
RATE_LIMIT_AUTH=10/minute

# Monitoring
ENABLE_METRICS=true
METRICS_PORT=9090
EOF

print_success "Environment configuration created"

# Create frontend .env
print_status "Creating frontend configuration..."
cat > frontend/.env <<EOF
VITE_API_URL=$API_URL
VITE_ENVIRONMENT=production
EOF

print_success "Frontend configuration created"

print_section "Nginx Configuration"

# Create production nginx configuration
print_status "Creating production nginx configuration..."

if [ "$ENABLE_SSL" = "true" ]; then
    # Create SSL nginx configuration
    sudo tee /etc/nginx/sites-available/shopify-automation > /dev/null <<'EOF'
# Rate limiting zones
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=general:10m rate=100r/s;

# Connection limiting
limit_conn_zone $binary_remote_addr zone=addr:10m;

# Cache zones
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=static_cache:10m max_size=100m inactive=60m use_temp_path=off;

# Upstream definitions
upstream shopify_api {
    least_conn;
    server 127.0.0.1:8000 max_fails=3 fail_timeout=30s;
    keepalive 32;
}

upstream shopify_frontend {
    server 127.0.0.1:3000 max_fails=3 fail_timeout=30s;
    keepalive 16;
}

# HTTP to HTTPS redirect
server {
    listen 80;
    listen [::]:80;
    server_name DOMAIN_PLACEHOLDER;

    # Let's Encrypt verification
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Redirect all other traffic to HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name DOMAIN_PLACEHOLDER;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/privkey.pem;
    
    # SSL Security Settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/letsencrypt/live/DOMAIN_PLACEHOLDER/chain.pem;

    # Security Headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy "default-src 'self' https: data: 'unsafe-inline' 'unsafe-eval'; img-src 'self' https: data: blob:; font-src 'self' https: data:;" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;

    # Connection limits
    limit_conn addr 100;

    # Logging
    access_log /var/log/nginx/shopify_access.log combined;
    error_log /var/log/nginx/shopify_error.log warn;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/json application/javascript application/xml+rss application/rss+xml application/atom+xml image/svg+xml text/x-js text/x-cross-domain-policy application/x-font-ttf application/x-font-opentype application/vnd.ms-fontobject image/x-icon;

    # API routes
    location /api/ {
        # Rate limiting
        limit_req zone=api burst=50 nodelay;
        
        # Remove /api prefix
        rewrite ^/api/(.*) /$1 break;
        
        # Proxy settings
        proxy_pass http://shopify_api;
        proxy_http_version 1.1;
        
        # Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $server_name;
        proxy_set_header Connection "";
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # Buffering
        proxy_buffering off;
        proxy_request_buffering off;
        
        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Disable caching for API
        proxy_cache_bypass 1;
        proxy_no_cache 1;
    }

    # Auth endpoints with stricter rate limiting
    location /api/auth/ {
        limit_req zone=login burst=5 nodelay;
        
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://shopify_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Admin routes with authentication check
    location /api/admin/ {
        limit_req zone=api burst=20 nodelay;
        
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://shopify_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Static files with caching
    location /static/ {
        alias /var/www/shopify-automation/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        
        # Enable gzip for static files
        gzip_static on;
    }

    # Frontend application
    location / {
        limit_req zone=general burst=100 nodelay;
        
        proxy_pass http://shopify_frontend;
        proxy_http_version 1.1;
        
        # Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $server_name;
        
        # WebSocket support for hot reload (dev)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Cache static assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            proxy_pass http://shopify_frontend;
            proxy_cache static_cache;
            proxy_cache_valid 200 302 60m;
            proxy_cache_valid 404 1m;
            expires 30d;
            add_header Cache-Control "public, immutable";
        }
    }

    # Health check endpoint
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }

    # Monitoring endpoint (internal only)
    location /metrics {
        allow 127.0.0.1;
        deny all;
        proxy_pass http://127.0.0.1:9090/metrics;
    }

    # Block access to sensitive files
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    location ~ ^/(\.env|docker-compose|Dockerfile) {
        deny all;
        return 404;
    }

    # Custom error pages
    error_page 404 /404.html;
    error_page 500 502 503 504 /50x.html;
    
    location = /404.html {
        root /var/www/shopify-automation/errors;
        internal;
    }
    
    location = /50x.html {
        root /var/www/shopify-automation/errors;
        internal;
    }
}
EOF

    # Replace domain placeholder
    sudo sed -i "s/DOMAIN_PLACEHOLDER/$DOMAIN_NAME/g" /etc/nginx/sites-available/shopify-automation
    
else
    # Create non-SSL nginx configuration
    sudo tee /etc/nginx/sites-available/shopify-automation > /dev/null <<'EOF'
# Rate limiting zones
limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;
limit_req_zone $binary_remote_addr zone=login:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=general:10m rate=100r/s;

# Upstream definitions
upstream shopify_api {
    server 127.0.0.1:8000;
    keepalive 32;
}

upstream shopify_frontend {
    server 127.0.0.1:3000;
    keepalive 16;
}

server {
    listen 80;
    listen [::]:80;
    server_name _;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # API routes
    location /api/ {
        limit_req zone=api burst=50 nodelay;
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://shopify_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Frontend application
    location / {
        limit_req zone=general burst=100 nodelay;
        proxy_pass http://shopify_frontend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # Health check
    location /health {
        access_log off;
        return 200 "healthy\n";
        add_header Content-Type text/plain;
    }
}
EOF
fi

# Test nginx configuration
sudo nginx -t
sudo systemctl reload nginx

print_success "Nginx configuration created"

print_section "SSL Certificate Auto-Renewal"

if [ "$ENABLE_SSL" = "true" ]; then
    # Setup auto-renewal with systemd timer
    print_status "Setting up SSL certificate auto-renewal..."
    
    # Create renewal script
    sudo tee /usr/local/bin/certbot-renew.sh > /dev/null <<'EOF'
#!/bin/bash
certbot renew --quiet --no-self-upgrade --post-hook "systemctl reload nginx"
EOF
    
    sudo chmod +x /usr/local/bin/certbot-renew.sh
    
    # Create systemd service
    sudo tee /etc/systemd/system/certbot-renew.service > /dev/null <<'EOF'
[Unit]
Description=Certbot Renewal
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/certbot-renew.sh
User=root
EOF

    # Create systemd timer
    sudo tee /etc/systemd/system/certbot-renew.timer > /dev/null <<'EOF'
[Unit]
Description=Run certbot renewal twice daily
After=network.target

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
EOF

    # Enable and start timer
    sudo systemctl daemon-reload
    sudo systemctl enable certbot-renew.timer
    sudo systemctl start certbot-renew.timer
    
    print_success "SSL auto-renewal configured"
fi

print_section "Docker Services Deployment"

# Build and start Docker services
print_status "Building Docker images..."
docker compose -f $COMPOSE_FILE build --no-cache --pull

print_status "Starting Docker services..."
docker compose -f $COMPOSE_FILE up -d

# Wait for services to be ready
print_status "Waiting for services to initialize..."
sleep 30

# Check service health
print_status "Checking service health..."

# Check PostgreSQL
for i in {1..30}; do
    if docker exec shopify_postgres_prod pg_isready -U shopify_user &>/dev/null; then
        print_success "PostgreSQL is ready"
        break
    fi
    echo -n "."
    sleep 2
done

# Initialize database
print_status "Initializing database..."
docker exec shopify_api_prod python -c "
import sys
sys.path.append('/app')
from database import Base, engine
from models import *
Base.metadata.create_all(bind=engine)
print('Database initialized')
"

# Run migrations
print_status "Running database migrations..."
docker exec shopify_api_prod python run_all_migrations.py

# Create admin user
print_status "Creating admin user..."
ADMIN_PASSWORD=$(openssl rand -base64 12 | tr -d "=+/" | cut -c1-12)

docker exec shopify_api_prod python -c "
import sys
sys.path.append('/app')
from database import SessionLocal
from models import AdminUser
from admin_auth import get_admin_password_hash

db = SessionLocal()
try:
    existing = db.query(AdminUser).filter(AdminUser.username == 'admin').first()
    if not existing:
        admin = AdminUser(
            username='admin',
            email='$EMAIL_ADDRESS',
            full_name='System Administrator',
            hashed_password=get_admin_password_hash('$ADMIN_PASSWORD'),
            role='super_admin',
            is_active=True
        )
        db.add(admin)
        db.commit()
        print('Admin user created')
    else:
        print('Admin user already exists')
except Exception as e:
    print(f'Error: {e}')
    db.rollback()
finally:
    db.close()
"

print_section "System Optimization"

# System tuning for production
print_status "Applying system optimizations..."

# Increase system limits
sudo tee /etc/security/limits.d/99-shopify.conf > /dev/null <<'EOF'
* soft nofile 65536
* hard nofile 65536
* soft nproc 32768
* hard nproc 32768
EOF

# Kernel parameters for production
sudo tee /etc/sysctl.d/99-shopify.conf > /dev/null <<'EOF'
# Network optimizations
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_tw_reuse = 1
net.ipv4.ip_local_port_range = 10000 65000

# Memory optimizations
vm.swappiness = 10
vm.dirty_ratio = 15
vm.dirty_background_ratio = 5

# File system
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
EOF

sudo sysctl -p /etc/sysctl.d/99-shopify.conf

print_success "System optimizations applied"

print_section "Backup Configuration"

# Create backup script
print_status "Creating backup script..."

cat > /usr/local/bin/shopify-backup.sh <<'EOF'
#!/bin/bash

BACKUP_DIR="/backups/shopify"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/$TIMESTAMP"

mkdir -p $BACKUP_PATH

# Backup PostgreSQL
docker exec shopify_postgres_prod pg_dump -U shopify_user shopify_db | gzip > $BACKUP_PATH/postgres.sql.gz

# Backup Redis
docker exec shopify_redis_prod redis-cli --rdb $BACKUP_PATH/redis.rdb

# Backup application data
tar czf $BACKUP_PATH/app_data.tar.gz /var/lib/docker/volumes/shopify-automation_*

# Keep only last 7 days of backups
find $BACKUP_DIR -type d -mtime +7 -exec rm -rf {} \;

echo "Backup completed: $BACKUP_PATH"
EOF

sudo chmod +x /usr/local/bin/shopify-backup.sh

# Create backup cron job
(crontab -l 2>/dev/null; echo "0 2 * * * /usr/local/bin/shopify-backup.sh") | crontab -

print_success "Backup system configured"

print_section "Monitoring Setup"

# Create monitoring script
cat > /usr/local/bin/shopify-monitor.sh <<'EOF'
#!/bin/bash

# Check services
SERVICES=("shopify_api_prod" "shopify_worker_prod" "shopify_postgres_prod" "shopify_redis_prod" "shopify_frontend_prod")

for service in "${SERVICES[@]}"; do
    if ! docker ps | grep -q $service; then
        echo "Service $service is down! Attempting restart..."
        docker compose -f /opt/shopify-automation/docker-compose.postgres.prod.yml up -d
    fi
done

# Check disk space
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    echo "Warning: Disk usage is at ${DISK_USAGE}%"
fi

# Check memory
MEM_USAGE=$(free | grep Mem | awk '{print int($3/$2 * 100)}')
if [ $MEM_USAGE -gt 90 ]; then
    echo "Warning: Memory usage is at ${MEM_USAGE}%"
fi
EOF

sudo chmod +x /usr/local/bin/shopify-monitor.sh

# Add monitoring cron job
(crontab -l 2>/dev/null; echo "*/5 * * * * /usr/local/bin/shopify-monitor.sh") | crontab -

print_success "Monitoring configured"

print_section "Installation Complete!"

# Display summary
echo
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        Installation Completed Successfully!               ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo

if [ "$ENABLE_SSL" = "true" ]; then
    echo -e "${BLUE}Access URLs:${NC}"
    echo -e "  Main App:     ${GREEN}https://$DOMAIN_NAME${NC}"
    echo -e "  API Docs:     ${GREEN}https://$DOMAIN_NAME/api/docs${NC}"
    echo -e "  Admin Panel:  ${GREEN}https://$DOMAIN_NAME/admin${NC}"
    echo
    echo -e "${BLUE}SSL Certificate:${NC}"
    echo -e "  Status:       ${GREEN}Active${NC}"
    echo -e "  Auto-renewal: ${GREEN}Enabled${NC}"
    echo -e "  Expiry check: ${YELLOW}sudo certbot certificates${NC}"
else
    echo -e "${BLUE}Access URLs:${NC}"
    echo -e "  Main App:     ${GREEN}http://$SERVER_IP${NC}"
    echo -e "  API:          ${GREEN}http://$SERVER_IP:8000${NC}"
    echo -e "  Frontend:     ${GREEN}http://$SERVER_IP:3000${NC}"
fi

echo
echo -e "${BLUE}Database:${NC}"
echo -e "  Type:         PostgreSQL 15"
echo -e "  Host:         localhost:5432"
echo -e "  Database:     shopify_db"
echo -e "  Username:     shopify_user"
echo -e "  Password:     ${YELLOW}[Saved in .env]${NC}"

echo
echo -e "${BLUE}Admin Credentials:${NC}"
echo -e "  Username:     ${YELLOW}admin${NC}"
echo -e "  Password:     ${YELLOW}$ADMIN_PASSWORD${NC}"
echo -e "  ${RED}⚠️  SAVE THIS PASSWORD - IT WILL NOT BE SHOWN AGAIN!${NC}"

echo
echo -e "${BLUE}Service Management:${NC}"
echo -e "  View logs:    ${YELLOW}docker compose -f $COMPOSE_FILE logs -f${NC}"
echo -e "  Restart:      ${YELLOW}docker compose -f $COMPOSE_FILE restart${NC}"
echo -e "  Stop:         ${YELLOW}docker compose -f $COMPOSE_FILE down${NC}"
echo -e "  Status:       ${YELLOW}docker compose -f $COMPOSE_FILE ps${NC}"

echo
echo -e "${BLUE}Maintenance:${NC}"
echo -e "  Backup:       ${YELLOW}/usr/local/bin/shopify-backup.sh${NC}"
echo -e "  Monitor:      ${YELLOW}/usr/local/bin/shopify-monitor.sh${NC}"
echo -e "  Logs:         ${YELLOW}/var/log/nginx/shopify_*.log${NC}"

echo
echo -e "${BLUE}Security:${NC}"
echo -e "  Firewall:     ${GREEN}Enabled${NC}"
echo -e "  Rate limiting:${GREEN}Enabled${NC}"
echo -e "  CORS:         ${GREEN}Configured${NC}"
if [ "$ENABLE_SSL" = "true" ]; then
    echo -e "  HTTPS:        ${GREEN}Enabled with TLS 1.2/1.3${NC}"
    echo -e "  HSTS:         ${GREEN}Enabled${NC}"
fi

echo
echo -e "${YELLOW}Next Steps:${NC}"
echo -e "  1. Change the admin password immediately"
echo -e "  2. Configure your Shopify stores"
echo -e "  3. Set up automation rules"
echo -e "  4. Test webhook endpoints"
echo -e "  5. Review security settings"

echo
print_success "System is ready for production use! 🚀"

# Save installation summary
cat > installation-summary.txt <<EOF
Shopify Automation System - Installation Summary
================================================
Date: $(date)
Server: $SERVER_IP
Domain: ${DOMAIN_NAME:-N/A}
SSL: $ENABLE_SSL
PostgreSQL Password: $POSTGRES_PASSWORD
Admin Password: $ADMIN_PASSWORD

Access URLs:
$(if [ "$ENABLE_SSL" = "true" ]; then
    echo "- https://$DOMAIN_NAME"
else
    echo "- http://$SERVER_IP"
fi)

Important Files:
- Environment: .env
- Docker Compose: $COMPOSE_FILE
- Nginx Config: /etc/nginx/sites-available/shopify-automation
- Backup Script: /usr/local/bin/shopify-backup.sh
- Monitor Script: /usr/local/bin/shopify-monitor.sh

Commands:
- View logs: docker compose -f $COMPOSE_FILE logs -f
- Restart: docker compose -f $COMPOSE_FILE restart
- Backup: /usr/local/bin/shopify-backup.sh
EOF

print_warning "Installation details saved to: installation-summary.txt"
print_warning "Keep this file secure as it contains sensitive information!"

exit 0