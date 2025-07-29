#!/bin/bash

# Shopify Multi-Store Order Management System
# Automated Installation Script for Linux - Production Version

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default to production mode
DEPLOYMENT_MODE="${DEPLOYMENT_MODE:-production}"
COMPOSE_FILE="docker-compose.yml"

# Check if production mode is requested
if [ "$DEPLOYMENT_MODE" = "production" ] || [ "$1" = "--production" ]; then
    DEPLOYMENT_MODE="production"
    COMPOSE_FILE="docker-compose.prod.yml"
fi

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

# Banner
echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Shopify Multi-Store Order Management System           ║"
echo "║       Automated Installation Script - PRODUCTION          ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

print_warning "Running in ${DEPLOYMENT_MODE} mode using ${COMPOSE_FILE}"

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   print_error "This script should not be run as root!"
   exit 1
fi

# Check OS
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    print_error "This script is designed for Linux systems only."
    exit 1
fi

# Function to clean up previous installation
cleanup_previous_installation() {
    print_warning "Cleaning up previous installation..."
    
    # Check if Docker is installed before attempting Docker operations
    if command -v docker &> /dev/null; then
        # Backup database if requested
        if [ "$KEEP_DATABASE" = "true" ]; then
            print_status "Backing up existing database..."
            BACKUP_DIR="./backups/install_backup_$(date +%Y%m%d_%H%M%S)"
            mkdir -p "$BACKUP_DIR"
            
            # Get the correct volume name based on compose file
            if [ "$COMPOSE_FILE" = "docker-compose.prod.yml" ]; then
                VOLUME_PREFIX="shopifyautomation"
            else
                VOLUME_PREFIX="shopify-automation"
            fi
            
            # Backup SQLite database
            if docker volume inspect ${VOLUME_PREFIX}_sqlite_data >/dev/null 2>&1; then
                docker run --rm -v ${VOLUME_PREFIX}_sqlite_data:/source -v "$(pwd)/$BACKUP_DIR:/backup" alpine tar czf /backup/sqlite_data.tar.gz -C /source .
                print_success "Database backed up to $BACKUP_DIR/sqlite_data.tar.gz"
                export RESTORE_DB_PATH="$BACKUP_DIR"
            fi
            
            # Backup Redis data
            if docker volume inspect ${VOLUME_PREFIX}_redis_data >/dev/null 2>&1; then
                docker run --rm -v ${VOLUME_PREFIX}_redis_data:/source -v "$(pwd)/$BACKUP_DIR:/backup" alpine tar czf /backup/redis_data.tar.gz -C /source .
                print_success "Redis data backed up to $BACKUP_DIR/redis_data.tar.gz"
            fi
        fi
        
        # Stop and remove containers
        if docker compose -f $COMPOSE_FILE ps >/dev/null 2>&1; then
            if [ "$KEEP_DATABASE" = "true" ]; then
                docker compose -f $COMPOSE_FILE down 2>/dev/null || true
            else
                docker compose -f $COMPOSE_FILE down -v 2>/dev/null || true
            fi
        fi
        
        # Remove Docker images
        docker rmi $(docker images | grep shopify | awk '{print $3}') 2>/dev/null || true
        
        # Clean up Docker system
        docker system prune -f 2>/dev/null || true
    else
        print_warning "Docker not installed yet, skipping Docker cleanup operations"
    fi
    
    # Remove logs and environment files (these don't require Docker)
    sudo rm -rf logs/* 2>/dev/null || true
    rm -f frontend/.env 2>/dev/null || true
    
    print_success "Previous installation cleaned up."
}

# Function to restore database from backup
restore_database() {
    local backup_path="$1"
    
    if [ ! -d "$backup_path" ]; then
        print_error "Backup directory $backup_path does not exist!"
        return 1
    fi
    
    # Check if Docker is available
    if ! command -v docker &> /dev/null; then
        print_error "Docker is required to restore database backup!"
        return 1
    fi
    
    print_status "Restoring database from backup..."
    
    # Get the correct volume name based on compose file
    if [ "$COMPOSE_FILE" = "docker-compose.prod.yml" ]; then
        VOLUME_PREFIX="shopifyautomation"
    else
        VOLUME_PREFIX="shopify-automation"
    fi
    
    # Restore SQLite database
    if [ -f "$backup_path/sqlite_data.tar.gz" ]; then
        docker run --rm -v ${VOLUME_PREFIX}_sqlite_data:/target -v "$(pwd)/$backup_path:/backup" alpine sh -c "rm -rf /target/* && tar xzf /backup/sqlite_data.tar.gz -C /target"
        print_success "Database restored"
    fi
    
    # Restore Redis data
    if [ -f "$backup_path/redis_data.tar.gz" ]; then
        docker run --rm -v ${VOLUME_PREFIX}_redis_data:/target -v "$(pwd)/$backup_path:/backup" alpine sh -c "rm -rf /target/* && tar xzf /backup/redis_data.tar.gz -C /target"
        print_success "Redis data restored"
    fi
}

# Get server configuration
get_server_config() {
    echo
    print_status "Server Configuration Setup"
    echo
    
    # Get server IP address
    echo -e "${BLUE}Please enter the server IP address that will host this application:${NC}"
    echo -e "${YELLOW}  - For local installation: use 'localhost' or '127.0.0.1'${NC}"
    echo -e "${YELLOW}  - For network installation: use the server's LAN IP (e.g., 192.168.1.112)${NC}"
    echo -e "${YELLOW}  - For internet access: use the server's public IP${NC}"
    echo
    read -p "Server IP address: " SERVER_IP
    
    if [ -z "$SERVER_IP" ]; then
        print_error "Server IP address is required!"
        exit 1
    fi
    
    # Validate IP format (basic check)
    if [[ ! "$SERVER_IP" =~ ^(localhost|127\.0\.0\.1|([0-9]{1,3}\.){3}[0-9]{1,3})$ ]]; then
        print_warning "Warning: '$SERVER_IP' doesn't look like a standard IP address or localhost."
        read -p "Are you sure this is correct? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    export SERVER_IP
    export VITE_API_URL="http://$SERVER_IP:8000"
    print_success "Server IP set to: $SERVER_IP"
}

# Parse command line arguments
KEEP_DATABASE=false
CLEAN_INSTALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --production)
            DEPLOYMENT_MODE="production"
            COMPOSE_FILE="docker-compose.prod.yml"
            shift
            ;;
        --development)
            DEPLOYMENT_MODE="development"
            COMPOSE_FILE="docker-compose.yml"
            shift
            ;;
        --clean)
            CLEAN_INSTALL=true
            shift
            ;;
        --keep-db)
            KEEP_DATABASE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --production          Run in production mode (default)"
            echo "  --development         Run in development mode"
            echo "  --clean               Clean installation (remove all previous data)"
            echo "  --keep-db             Keep existing database during reinstall (runs migrations)"
            echo "  --help, -h            Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Fresh production installation"
            echo "  $0 --development      # Development installation"
            echo "  $0 --clean           # Clean installation (remove all data)"
            echo "  $0 --keep-db          # Reinstall but keep existing database"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

print_status "Starting installation process..."

# Check if required compose file exists
if [ ! -f "$COMPOSE_FILE" ]; then
    print_error "Required file $COMPOSE_FILE not found!"
    print_error "Please ensure you're running this script from the project root directory."
    exit 1
fi

# Check if production Dockerfile exists for frontend
if [ "$DEPLOYMENT_MODE" = "production" ] && [ ! -f "frontend/Dockerfile.prod" ]; then
    print_error "Production Dockerfile (frontend/Dockerfile.prod) not found!"
    print_error "Please ensure all required files are present."
    exit 1
fi

# Check if this is a cleanup/reinstall
if [ "$CLEAN_INSTALL" = true ] || [ -f docker-compose.yml ]; then
    if [ "$CLEAN_INSTALL" = true ]; then
        cleanup_previous_installation
    elif [ "$KEEP_DATABASE" = true ]; then
        print_status "Keeping existing database and updating application..."
        cleanup_previous_installation
    else
        print_warning "Existing installation detected!"
        echo "Do you want to:"
        echo "1) Keep existing database and update application"
        echo "2) Clean installation (remove all data)"
        echo "3) Cancel"
        read -p "Choose an option (1-3): " choice
        
        case $choice in
            1)
                KEEP_DATABASE=true
                cleanup_previous_installation
                ;;
            2)
                cleanup_previous_installation
                ;;
            3)
                print_status "Installation cancelled."
                exit 0
                ;;
            *)
                print_error "Invalid choice. Installation cancelled."
                exit 1
                ;;
        esac
    fi
fi

# Get server configuration
get_server_config

# Step 0: Check and install system dependencies
print_status "Checking system dependencies..."

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
    VER=$VERSION_ID
else
    print_error "Cannot detect OS version"
    exit 1
fi

# Install basic tools if missing
REQUIRED_TOOLS="curl wget git openssl lsof"
MISSING_TOOLS=""

for tool in $REQUIRED_TOOLS; do
    if ! command -v $tool &> /dev/null; then
        MISSING_TOOLS="$MISSING_TOOLS $tool"
    fi
done

if [ ! -z "$MISSING_TOOLS" ]; then
    print_warning "Installing missing tools:$MISSING_TOOLS"
    
    # Update package manager based on OS
    if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
        sudo apt-get update
        sudo apt-get install -y $MISSING_TOOLS
    elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]] || [[ "$OS" == *"Fedora"* ]]; then
        sudo yum install -y $MISSING_TOOLS
    elif [[ "$OS" == *"Amazon Linux"* ]]; then
        sudo yum install -y $MISSING_TOOLS
    else
        print_error "Unsupported OS: $OS. Please install the following tools manually: $MISSING_TOOLS"
        exit 1
    fi
fi

# Step 1: Check Docker installation
print_status "Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    print_warning "Docker is not installed. Installing Docker..."
    
    if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
        # Ubuntu/Debian installation
        sudo apt-get update
        sudo apt-get install -y \
            apt-transport-https \
            ca-certificates \
            curl \
            gnupg \
            lsb-release \
            software-properties-common
        
        # Install lsb-release if missing
        if ! command -v lsb_release &> /dev/null; then
            sudo apt-get install -y lsb-release
        fi
        
        # Add Docker's official GPG key
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
        
        # Determine Ubuntu codename
        if command -v lsb_release &> /dev/null; then
            UBUNTU_CODENAME=$(lsb_release -cs)
        else
            # Fallback method using /etc/os-release
            UBUNTU_CODENAME=$(grep VERSION_CODENAME /etc/os-release | cut -d'=' -f2)
        fi
        
        # Add Docker repository
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
          ${UBUNTU_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        
        # Install Docker
        sudo apt-get update
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io
        
    elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]] || [[ "$OS" == *"Fedora"* ]]; then
        # CentOS/RHEL/Fedora installation
        sudo yum install -y yum-utils
        sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        sudo yum install -y docker-ce docker-ce-cli containerd.io
        sudo systemctl start docker
        sudo systemctl enable docker
        
    elif [[ "$OS" == *"Amazon Linux"* ]]; then
        # Amazon Linux installation
        sudo yum update -y
        sudo amazon-linux-extras install docker -y
        sudo service docker start
        sudo systemctl enable docker
        
    else
        print_error "Unsupported OS for automatic Docker installation: $OS"
        print_error "Please install Docker manually and run this script again."
        exit 1
    fi
    
    # Add user to docker group
    sudo usermod -aG docker $USER
    
    # Start Docker service
    sudo systemctl start docker || sudo service docker start
    sudo systemctl enable docker || true
    
    # Fix Docker socket permissions
    sudo chmod 666 /var/run/docker.sock || true
    
    print_success "Docker installed successfully!"
    print_warning "You need to log out and back in for group changes to take effect."
    
    # Try to activate group without logout (may not work on all systems)
    if [ "$SKIP_GROUP_REFRESH" != "true" ]; then
        export SKIP_GROUP_REFRESH=true
        exec sg docker "$0 $@"
    fi
else
    print_success "Docker is already installed."
fi

# Ensure Docker daemon is running
print_status "Checking Docker daemon..."
if ! docker info >/dev/null 2>&1; then
    print_warning "Docker daemon is not running. Starting Docker..."
    sudo systemctl start docker || sudo service docker start
    sleep 5
    
    # Fix permissions if needed
    sudo chmod 666 /var/run/docker.sock || true
    
    if ! docker info >/dev/null 2>&1; then
        print_error "Docker daemon failed to start. Please check Docker installation."
        exit 1
    fi
fi
print_success "Docker daemon is running."

# Check Docker Compose v2
if ! docker compose version &> /dev/null; then
    print_warning "Docker Compose v2 is not installed. Installing..."
    
    # Method 1: Try to install via package manager (preferred)
    if [[ "$OS" == *"Ubuntu"* ]] || [[ "$OS" == *"Debian"* ]]; then
        # For newer Ubuntu/Debian, docker-compose-plugin should be available
        sudo apt-get update
        if sudo apt-get install -y docker-compose-plugin 2>/dev/null; then
            print_success "Docker Compose v2 installed via package manager"
        else
            MANUAL_INSTALL=true
        fi
    elif [[ "$OS" == *"CentOS"* ]] || [[ "$OS" == *"Red Hat"* ]] || [[ "$OS" == *"Fedora"* ]]; then
        if sudo yum install -y docker-compose-plugin 2>/dev/null; then
            print_success "Docker Compose v2 installed via package manager"
        else
            MANUAL_INSTALL=true
        fi
    else
        MANUAL_INSTALL=true
    fi
    
    # Method 2: Manual installation if package manager failed
    if [ "$MANUAL_INSTALL" = true ]; then
        print_status "Installing Docker Compose v2 manually..."
        
        # Install Docker Compose v2 plugin
        DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
        mkdir -p $DOCKER_CONFIG/cli-plugins
        
        # Get the latest version
        COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep 'tag_name' | cut -d'"' -f4)
        
        if [ -z "$COMPOSE_VERSION" ]; then
            print_warning "Could not determine latest version, using v2.23.0"
            COMPOSE_VERSION="v2.23.0"
        fi
        
        # Determine architecture
        ARCH=$(uname -m)
        case $ARCH in
            x86_64)
                ARCH="x86_64"
                ;;
            aarch64)
                ARCH="aarch64"
                ;;
            armv7l)
                ARCH="armv7"
                ;;
            *)
                print_error "Unsupported architecture: $ARCH"
                exit 1
                ;;
        esac
        
        # Download Docker Compose v2
        DOWNLOAD_URL="https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-${ARCH}"
        print_status "Downloading from: $DOWNLOAD_URL"
        
        if ! curl -SL "$DOWNLOAD_URL" -o $DOCKER_CONFIG/cli-plugins/docker-compose; then
            print_error "Failed to download Docker Compose v2"
            exit 1
        fi
        
        # Make it executable
        chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose
        
        # Also try system-wide installation
        sudo mkdir -p /usr/local/lib/docker/cli-plugins
        sudo cp $DOCKER_CONFIG/cli-plugins/docker-compose /usr/local/lib/docker/cli-plugins/
        sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    fi
    
    # Verify installation
    if docker compose version &> /dev/null; then
        print_success "Docker Compose v2 installed successfully!"
        docker compose version
    else
        print_error "Failed to install Docker Compose v2"
        print_error "Please visit https://docs.docker.com/compose/install/ for manual installation"
        exit 1
    fi
else
    print_success "Docker Compose v2 is already installed."
    docker compose version
fi

# Step 2: Create necessary directories
print_status "Creating necessary directories..."
mkdir -p logs
mkdir -p backups
mkdir -p nginx/ssl

# Step 3: Create .env file if it doesn't exist
if [ ! -f .env ]; then
    print_status "Creating environment configuration..."
    cat > .env <<EOF
# Server Configuration
SERVER_IP=$SERVER_IP
VITE_API_URL=http://$SERVER_IP:8000

# CORS Configuration
CORS_ORIGINS=http://$SERVER_IP,http://$SERVER_IP:3000,http://localhost,http://localhost:3000

# Security
SECRET_KEY=$(openssl rand -hex 32)
ADMIN_SECRET_KEY=$(openssl rand -hex 32)

# Environment
ENVIRONMENT=$DEPLOYMENT_MODE

# Shopify Configuration (Add your credentials here)
SHOPIFY_API_VERSION=2025-04

# JWT Configuration
JWT_SECRET_KEY=$(openssl rand -hex 32)
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Redis Configuration
REDIS_URL=redis://redis:6379/0

# Database Configuration
DATABASE_URL=sqlite:///app/data/app.db
EOF
    print_success "Environment configuration created!"
fi

# Step 4: Configure CORS origins for server IP
print_status "Configuring CORS origins for server IP..."
# CORS will be configured via environment variable in .env file
print_success "CORS will be configured via CORS_ORIGINS environment variable."

# Step 5: Create frontend environment file
print_status "Creating frontend environment configuration..."
cat > frontend/.env <<EOF
VITE_API_URL=http://$SERVER_IP:8000
EOF
print_success "Frontend environment configuration created!"

# Step 6: Verify configuration
print_status "Verifying configuration..."
if grep -q "CORS_ORIGINS=.*$SERVER_IP" .env; then
    print_success "✓ CORS configuration includes server IP"
else
    print_error "✗ CORS configuration missing server IP"
    exit 1
fi

if [ -f frontend/.env ] && grep -q "VITE_API_URL=http://$SERVER_IP:8000" frontend/.env; then
    print_success "✓ Frontend .env file has correct API URL"
else
    print_error "✗ Frontend .env file missing or incorrect"
    exit 1
fi

# Step 7: Build and start services
print_status "Building Docker images ($DEPLOYMENT_MODE mode)..."

# Build with no cache and force pull to ensure fresh build
docker compose -f $COMPOSE_FILE build --no-cache --pull
print_success "Docker images built successfully!"

# Step 8: Start services
print_status "Starting all services..."
docker compose -f $COMPOSE_FILE up -d

# Wait for services to start
print_status "Waiting for services to initialize..."
sleep 30

# Check if services are running
if docker compose -f $COMPOSE_FILE ps | grep -q "Exit"; then
    print_error "Some services failed to start. Checking logs..."
    docker compose -f $COMPOSE_FILE logs --tail=50
    exit 1
fi

print_success "All services started successfully!"

# Step 9: Initialize or restore database
if [ -n "$RESTORE_DB_PATH" ]; then
    print_status "Restoring database from backup..."
    restore_database "$RESTORE_DB_PATH"
    print_success "Database restored from backup!"
    
    # Run migrations after restoring database
    print_status "Checking for database migrations..."
    docker exec shopify_api python run_all_migrations.py --check
    if [ $? -ne 0 ]; then
        print_status "Running pending migrations..."
        docker exec shopify_api python run_all_migrations.py
        if [ $? -eq 0 ]; then
            print_success "Database migrations completed successfully!"
        else
            print_error "Database migrations failed! Check logs for details."
            print_error "This could cause features like fraud detection to malfunction."
            exit 1
        fi
    else
        print_success "Database schema is up to date!"
    fi
elif [ "$KEEP_DATABASE" = "true" ]; then
    # Database was preserved, check if migrations are needed
    print_status "Checking existing database for required migrations..."
    docker exec shopify_api python run_all_migrations.py --check
    if [ $? -ne 0 ]; then
        print_warning "Database schema needs updating. Running migrations..."
        docker exec shopify_api python run_all_migrations.py
        if [ $? -eq 0 ]; then
            print_success "Database migrations completed successfully!"
        else
            print_error "Database migrations failed! Check logs for details."
            print_error "This could cause features like fraud detection to malfunction."
            exit 1
        fi
    else
        print_success "Existing database schema is up to date!"
    fi
else
    print_status "Initializing database..."
    docker exec shopify_api python -c "
from database import Base, engine
from models import *
try:
    Base.metadata.create_all(bind=engine)
    print('Database initialized successfully!')
except Exception as e:
    print(f'Database initialization failed: {e}')
    exit(1)
"

    if [ $? -eq 0 ]; then
        print_success "Database initialized successfully!"
        
        # For fresh installs, migrations are not needed as SQLAlchemy creates
        # the complete schema with all columns. Mark all migrations as applied.
        print_status "Marking all migrations as applied for fresh install..."
        docker exec shopify_api python -c "
import sqlite3
from datetime import datetime

# Connect to database
conn = sqlite3.connect('/app/data/app.db')
cursor = conn.cursor()

# Create migration tracking table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS schema_migrations (
        migration_name TEXT PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# Mark all migrations as applied for fresh install
migrations = [
    'add_delay_ms_to_rules',
    'add_timezone_to_settings',
    'add_fraud_sync_enabled',
    'add_fraud_detection_rules',
    'add_duplicate_detection_days_column',
    'add_delivery_analytics_column',
    'add_days_since_last_delivery_column',
    'add_user_id_to_task_status',
    'add_fraud_analyses_archive'
]

for migration in migrations:
    cursor.execute(
        'INSERT OR IGNORE INTO schema_migrations (migration_name, applied_at) VALUES (?, ?)',
        (migration, datetime.now())
    )

conn.commit()
conn.close()
print('All migrations marked as applied for fresh install.')
"
        if [ $? -eq 0 ]; then
            print_success "Fresh install schema setup completed!"
        else
            print_error "Failed to mark migrations as applied!"
            # Not critical - continue installation
        fi
    else
        print_error "Database initialization failed!"
        exit 1
    fi
fi

# Step 10: Health check
print_status "Performing health check..."
sleep 5

# Check API health
if curl -f -s http://localhost:8000/health > /dev/null; then
    print_success "API is healthy!"
else
    print_error "API health check failed!"
    docker compose -f $COMPOSE_FILE logs api --tail=50
    exit 1
fi

# Check if frontend is accessible
if [ "$DEPLOYMENT_MODE" = "production" ]; then
    # In production, frontend serves static files
    if curl -f -s http://localhost:3000 > /dev/null; then
        print_success "Frontend is accessible!"
    else
        print_error "Frontend is not accessible!"
        docker compose -f $COMPOSE_FILE logs frontend --tail=50
        exit 1
    fi
else
    # In development, frontend runs Vite dev server
    if curl -f -s http://localhost:3000 > /dev/null; then
        print_success "Frontend development server is running!"
    else
        print_warning "Frontend might still be starting up..."
    fi
fi

# Create initial admin user
print_status "Creating initial admin user..."
docker exec shopify_api python -c "
try:
    from init_admin import create_initial_admin
    create_initial_admin()
except FileNotFoundError:
    print('Note: Admin initialization script not found. You can add it later.')
except Exception as e:
    print(f'Admin user might already exist or error occurred: {e}')
"

# Step 11: Display success message
echo
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          Installation completed successfully!             ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo
echo -e "${BLUE}Access the application:${NC}"
echo -e "  Main App:    ${GREEN}http://$SERVER_IP${NC}"
echo -e "  API Docs:    ${GREEN}http://$SERVER_IP:8000/docs${NC}"
echo -e "  Admin Panel: ${GREEN}http://$SERVER_IP/admin/login${NC}"
echo
echo -e "${BLUE}Default Admin Credentials:${NC}"
echo -e "  Username: ${YELLOW}admin${NC}"
echo -e "  Password: ${YELLOW}admin${NC}"
echo -e "  ${RED}⚠️  Change the admin password immediately after first login!${NC}"
echo
echo -e "${BLUE}Monitor services:${NC}"
echo -e "  View logs:      ${YELLOW}docker compose -f $COMPOSE_FILE logs -f${NC}"
echo -e "  Service status: ${YELLOW}docker compose -f $COMPOSE_FILE ps${NC}"
echo -e "  Schema version: ${YELLOW}docker exec shopify_api python check_schema_version.py${NC}"

# Verify schema is up to date
print_status "Verifying database schema..."
docker exec shopify_api python run_all_migrations.py --check > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database schema is up to date${NC}"
else
    echo -e "${YELLOW}⚠ Database schema may need attention. Run: docker exec shopify_api python run_all_migrations.py${NC}"
fi
echo
echo -e "${BLUE}Environment:${NC} ${YELLOW}$DEPLOYMENT_MODE${NC}"
echo -e "${BLUE}Compose file:${NC} ${YELLOW}$COMPOSE_FILE${NC}"
echo

if [ "$DEPLOYMENT_MODE" = "development" ]; then
    print_warning "Running in DEVELOPMENT mode - not suitable for production use!"
    print_warning "For production deployment, run: ./install-prod.sh --production"
fi

print_success "Installation complete! 🎉"