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

# Default to production mode with PostgreSQL
DEPLOYMENT_MODE="${DEPLOYMENT_MODE:-production}"
DATABASE_TYPE="postgresql"  # Always use PostgreSQL
COMPOSE_FILE="docker-compose.postgres.yml"
POSTGRES_PASSWORD=""
POSTGRES_CONTAINER="shopify_postgres"
API_CONTAINER="shopify_api"

# Check if production mode is requested
if [ "$DEPLOYMENT_MODE" = "production" ] || [ "$1" = "--production" ]; then
    DEPLOYMENT_MODE="production"
    COMPOSE_FILE="docker-compose.postgres.prod.yml"
    POSTGRES_CONTAINER="shopify_postgres_prod"
    API_CONTAINER="shopify_api_prod"
    # Check if prod compose file exists, if not use regular postgres compose
    if [ ! -f "$COMPOSE_FILE" ]; then
        COMPOSE_FILE="docker-compose.postgres.yml"
        POSTGRES_CONTAINER="shopify_postgres"
        API_CONTAINER="shopify_api"
    fi
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

# Function: Update from GitHub
update_from_github() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║     Shopify Multi-Store Order Management System           ║"
    echo "║           UPDATE FROM GITHUB                              ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"

    # --- Pre-flight checks ---
    if [ ! -d ".git" ]; then
        print_error "Not a git repository! Run this from the project root."
        exit 1
    fi

    if ! command -v docker &> /dev/null || ! docker info >/dev/null 2>&1; then
        print_error "Docker is not installed or not running. Cannot update."
        exit 1
    fi

    if [ ! -f .env ]; then
        print_error ".env file not found! Run a full install first."
        exit 1
    fi

    # Load SERVER_IP from existing .env
    SERVER_IP=$(grep '^SERVER_IP=' .env | cut -d'=' -f2-)
    if [ -z "$SERVER_IP" ]; then
        print_error "SERVER_IP not found in .env. Run a full install first."
        exit 1
    fi
    print_status "Server IP: $SERVER_IP"

    # Determine the git remote branch to pull from
    GIT_BRANCH="${UPDATE_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
    GIT_REMOTE="${UPDATE_REMOTE:-origin}"
    CURRENT_COMMIT=$(git rev-parse --short HEAD)
    print_status "Current branch: $GIT_BRANCH (commit: $CURRENT_COMMIT)"

    # --- Step 1: Backup database ---
    print_status "Step 1/7: Backing up database..."
    BACKUP_DIR="./backups/update_backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"

    if docker ps --format '{{.Names}}' | grep -q "$POSTGRES_CONTAINER"; then
        if docker exec $POSTGRES_CONTAINER pg_dump -U shopify_user -d shopify_db 2>/dev/null | gzip > "$BACKUP_DIR/postgres_backup.sql.gz"; then
            BACKUP_SIZE=$(du -h "$BACKUP_DIR/postgres_backup.sql.gz" | cut -f1)
            print_success "Database backed up ($BACKUP_SIZE) -> $BACKUP_DIR/postgres_backup.sql.gz"
        else
            print_error "Database backup failed!"
            read -p "Continue without backup? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        print_warning "PostgreSQL container not running. Skipping database backup."
        print_warning "Data volumes will be preserved."
    fi

    # Backup .env files
    cp .env "$BACKUP_DIR/.env.backup"
    [ -f frontend/.env ] && cp frontend/.env "$BACKUP_DIR/frontend.env.backup"
    print_success "Configuration files backed up"

    # --- Step 2: Pull latest code from GitHub ---
    print_status "Step 2/7: Pulling latest code from $GIT_REMOTE/$GIT_BRANCH..."

    # Stash any local changes (uncommitted work)
    LOCAL_CHANGES=false
    if ! git diff --quiet HEAD 2>/dev/null || ! git diff --cached --quiet HEAD 2>/dev/null; then
        LOCAL_CHANGES=true
        print_warning "Local changes detected, stashing them..."
        git stash push -m "auto-stash before update $(date +%Y%m%d_%H%M%S)"
        print_success "Local changes stashed"
    fi

    # Fetch and pull
    if ! git fetch "$GIT_REMOTE" "$GIT_BRANCH"; then
        print_error "Failed to fetch from $GIT_REMOTE/$GIT_BRANCH"
        if [ "$LOCAL_CHANGES" = true ]; then
            print_status "Restoring stashed changes..."
            git stash pop
        fi
        exit 1
    fi

    NEW_COMMIT=$(git rev-parse --short "$GIT_REMOTE/$GIT_BRANCH")
    if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
        print_success "Already up to date (commit: $CURRENT_COMMIT)"
        if [ "$FORCE_UPDATE" != "true" ]; then
            print_status "Use --force to rebuild anyway."
            if [ "$LOCAL_CHANGES" = true ]; then
                git stash pop
            fi
            exit 0
        fi
        print_warning "Forcing rebuild..."
    else
        print_status "Updating: $CURRENT_COMMIT -> $NEW_COMMIT"
    fi

    if ! git merge "$GIT_REMOTE/$GIT_BRANCH" --ff-only; then
        print_error "Fast-forward merge failed. You may have diverged commits."
        print_error "Resolve manually: git merge $GIT_REMOTE/$GIT_BRANCH"
        if [ "$LOCAL_CHANGES" = true ]; then
            print_status "Restoring stashed changes..."
            git stash pop
        fi
        exit 1
    fi

    UPDATED_COMMIT=$(git rev-parse --short HEAD)
    print_success "Code updated to commit: $UPDATED_COMMIT"

    # Show what changed
    echo
    print_status "Changes pulled:"
    git log --oneline "$CURRENT_COMMIT..$UPDATED_COMMIT" 2>/dev/null | head -20
    echo

    # Re-apply stashed changes if any
    if [ "$LOCAL_CHANGES" = true ]; then
        print_status "Re-applying stashed local changes..."
        if git stash pop; then
            print_success "Local changes restored"
        else
            print_warning "Could not auto-apply local changes. They are saved in git stash."
        fi
    fi

    # --- Step 3: Update configuration files ---
    print_status "Step 3/7: Updating configuration..."

    # Update frontend .env based on deployment mode
    if [ "$DEPLOYMENT_MODE" = "production" ]; then
        cat > frontend/.env <<ENVEOF
VITE_API_URL=/api
ENVEOF
        print_success "Frontend .env updated (nginx proxy mode)"
    else
        cat > frontend/.env <<ENVEOF
VITE_API_URL=http://$SERVER_IP:8000
ENVEOF
        print_success "Frontend .env updated (direct API mode)"
    fi

    # Ensure any new required env vars exist in .env (added by code updates)
    # ENCRYPTION_KEY: required for token encryption (added in audit fix #5)
    if ! grep -q '^ENCRYPTION_KEY=' .env; then
        print_warning "Adding missing ENCRYPTION_KEY to .env..."
        ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || openssl rand -base64 32)
        echo "" >> .env
        echo "# Encryption key (auto-added during update)" >> .env
        echo "ENCRYPTION_KEY=${ENCRYPTION_KEY}" >> .env
        print_success "ENCRYPTION_KEY added to .env"
    fi

    # SHOPIFY_API_VERSION: configurable API version (added in audit fix #26)
    if ! grep -q '^SHOPIFY_API_VERSION=' .env; then
        echo "" >> .env
        echo "# Shopify API version (auto-added during update)" >> .env
        echo "SHOPIFY_API_VERSION=2025-04" >> .env
        print_success "SHOPIFY_API_VERSION added to .env"
    fi

    # --- Step 4: Stop running containers ---
    print_status "Step 4/7: Stopping running containers..."
    docker compose -f $COMPOSE_FILE stop api worker scheduler frontend nginx 2>/dev/null || true
    print_success "Application containers stopped (database kept running)"

    # --- Step 5: Rebuild images ---
    print_status "Step 5/7: Rebuilding Docker images..."
    if ! docker compose -f $COMPOSE_FILE build --no-cache api worker scheduler frontend nginx 2>/dev/null; then
        # Fallback: try building all services if specific ones fail
        if ! docker compose -f $COMPOSE_FILE build --no-cache; then
            print_error "Build failed! Rolling back..."
            print_error "Your database backup is at: $BACKUP_DIR"
            print_error "To revert code: git checkout $CURRENT_COMMIT"
            exit 1
        fi
    fi
    print_success "Docker images rebuilt"

    # --- Step 6: Start services ---
    print_status "Step 6/7: Starting all services..."
    docker compose -f $COMPOSE_FILE up -d

    # Wait for services
    print_status "Waiting for services to initialize..."
    for i in {1..60}; do
        if curl -f -s http://localhost:8000/health > /dev/null 2>&1; then
            break
        fi
        echo -n "."
        sleep 2
    done
    echo

    # Check services
    if docker compose -f $COMPOSE_FILE ps 2>/dev/null | grep -q "Exit"; then
        print_error "Some services failed to start!"
        docker compose -f $COMPOSE_FILE logs --tail=30 api worker scheduler 2>/dev/null
        print_error "Your database backup is at: $BACKUP_DIR"
        exit 1
    fi

    # --- Step 7: Run migrations ---
    print_status "Step 7/7: Checking for database migrations..."
    sleep 5  # Give the API container time to fully start

    if docker exec $API_CONTAINER python run_all_migrations.py --check 2>/dev/null; then
        print_success "Database schema is up to date"
    else
        print_warning "Running pending migrations..."
        if docker exec $API_CONTAINER python run_all_migrations.py 2>/dev/null; then
            print_success "Database migrations completed"
        else
            print_warning "Migration runner returned an error. Check manually:"
            print_warning "  docker exec $API_CONTAINER python run_all_migrations.py"
        fi
    fi

    # --- Health check ---
    if curl -f -s http://localhost:8000/health > /dev/null 2>&1; then
        print_success "API is healthy"
    else
        print_error "API health check failed after update!"
        print_error "Check logs: docker compose -f $COMPOSE_FILE logs api --tail=50"
        print_error "Database backup: $BACKUP_DIR"
        exit 1
    fi

    # --- Done ---
    echo
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║             Update completed successfully!                ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo
    echo -e "${BLUE}Update summary:${NC}"
    echo -e "  Previous commit: ${YELLOW}$CURRENT_COMMIT${NC}"
    echo -e "  Current commit:  ${GREEN}$UPDATED_COMMIT${NC}"
    echo -e "  Database backup: ${YELLOW}$BACKUP_DIR${NC}"
    echo
    echo -e "${BLUE}Access the application:${NC}"
    echo -e "  Main App:    ${GREEN}http://$SERVER_IP${NC}"
    echo -e "  Admin Panel: ${GREEN}http://$SERVER_IP/admin${NC}"
    echo
    echo -e "${BLUE}If something went wrong:${NC}"
    echo -e "  Revert code:      ${YELLOW}git checkout $CURRENT_COMMIT${NC}"
    echo -e "  Restore database: ${YELLOW}gunzip -c $BACKUP_DIR/postgres_backup.sql.gz | docker exec -i $POSTGRES_CONTAINER psql -U shopify_user -d shopify_db${NC}"
    echo -e "  View logs:        ${YELLOW}docker compose -f $COMPOSE_FILE logs -f${NC}"
    echo
    print_success "Update complete!"
    exit 0
}

# Banner
echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║     Shopify Multi-Store Order Management System           ║"
echo "║    PostgreSQL Installation Script - PRODUCTION            ║"
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
            
            # Backup PostgreSQL database (safety net only — volumes are preserved)
            if docker ps | grep -q $POSTGRES_CONTAINER; then
                docker exec $POSTGRES_CONTAINER pg_dump -U shopify_user -d shopify_db | gzip > "$BACKUP_DIR/postgres_backup.sql.gz"
                print_success "PostgreSQL database backed up to $BACKUP_DIR/postgres_backup.sql.gz"
            elif docker volume inspect ${VOLUME_PREFIX}_postgres_data >/dev/null 2>&1; then
                # If container not running but volume exists, backup the volume
                docker run --rm -v ${VOLUME_PREFIX}_postgres_data:/source -v "$(pwd)/$BACKUP_DIR:/backup" alpine tar czf /backup/postgres_data.tar.gz -C /source .
                print_success "PostgreSQL data volume backed up to $BACKUP_DIR/postgres_data.tar.gz"
            fi
            # NOTE: Do NOT set RESTORE_DB_PATH here. The database volume is preserved,
            # so restore is unnecessary. The backup is just a safety net.
            
            # Backup Redis data
            if docker volume inspect ${VOLUME_PREFIX}_redis_data >/dev/null 2>&1; then
                docker run --rm -v ${VOLUME_PREFIX}_redis_data:/source -v "$(pwd)/$BACKUP_DIR:/backup" alpine tar czf /backup/redis_data.tar.gz -C /source .
                print_success "Redis data backed up to $BACKUP_DIR/redis_data.tar.gz"
            fi
        fi
        
        # Force stop all shopify containers first (avoids hangs)
        print_status "Stopping containers..."
        docker ps -aq --filter "name=shopify" | xargs -r docker stop -t 5 2>/dev/null || true
        docker ps -aq --filter "name=shopify" | xargs -r docker rm -f 2>/dev/null || true

        # Remove compose project (networks, volumes if clean install)
        if [ "$KEEP_DATABASE" = "true" ]; then
            docker compose -f $COMPOSE_FILE down --remove-orphans 2>/dev/null || true
        else
            docker compose -f $COMPOSE_FILE down -v --remove-orphans 2>/dev/null || true
        fi

        # Remove Docker images
        docker images --filter "reference=*shopify*" -q | xargs -r docker rmi -f 2>/dev/null || true

        # Clean up Docker system
        docker network prune -f 2>/dev/null || true
        docker system prune -f 2>/dev/null || true
    else
        print_warning "Docker not installed yet, skipping Docker cleanup operations"
    fi
    
    # Remove logs (these don't require Docker)
    sudo rm -rf logs/* 2>/dev/null || true
    # Only remove frontend/.env on clean install; it gets recreated later either way
    if [ "$KEEP_DATABASE" != "true" ]; then
        rm -f frontend/.env 2>/dev/null || true
    fi
    
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
    
    # Restore PostgreSQL database
    if [ -f "$backup_path/postgres_backup.sql.gz" ]; then
        # Wait for PostgreSQL to be ready
        print_status "Waiting for PostgreSQL to be ready..."
        for i in {1..30}; do
            if docker exec $POSTGRES_CONTAINER pg_isready -U shopify_user -d shopify_db &>/dev/null; then
                break
            fi
            sleep 2
        done
        
        # Restore from SQL backup
        gunzip -c "$backup_path/postgres_backup.sql.gz" | docker exec -i $POSTGRES_CONTAINER psql -U shopify_user -d shopify_db
        print_success "PostgreSQL database restored from SQL backup"
    elif [ -f "$backup_path/postgres_data.tar.gz" ]; then
        # Restore from volume backup
        docker run --rm -v ${VOLUME_PREFIX}_postgres_data:/target -v "$(pwd)/$backup_path:/backup" alpine sh -c "rm -rf /target/* && tar xzf /backup/postgres_data.tar.gz -C /target"
        print_success "PostgreSQL data volume restored"
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
MIGRATE_FROM_SQLITE=false
SQLITE_PATH="./backend/app.db"
UPDATE_MODE=false
FORCE_UPDATE=false
UPDATE_BRANCH=""
UPDATE_REMOTE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --update)
            UPDATE_MODE=true
            shift
            ;;
        --force)
            FORCE_UPDATE=true
            shift
            ;;
        --branch)
            UPDATE_BRANCH="$2"
            shift 2
            ;;
        --remote)
            UPDATE_REMOTE="$2"
            shift 2
            ;;
        --production)
            DEPLOYMENT_MODE="production"
            COMPOSE_FILE="docker-compose.postgres.prod.yml"
            POSTGRES_CONTAINER="shopify_postgres_prod"
            API_CONTAINER="shopify_api_prod"
            if [ ! -f "$COMPOSE_FILE" ]; then
                COMPOSE_FILE="docker-compose.postgres.yml"
                POSTGRES_CONTAINER="shopify_postgres"
                API_CONTAINER="shopify_api"
            fi
            shift
            ;;
        --development)
            DEPLOYMENT_MODE="development"
            COMPOSE_FILE="docker-compose.postgres.yml"
            POSTGRES_CONTAINER="shopify_postgres"
            API_CONTAINER="shopify_api"
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
        --postgres-password)
            POSTGRES_PASSWORD="$2"
            shift 2
            ;;
        --migrate-from-sqlite)
            MIGRATE_FROM_SQLITE=true
            if [ -n "$2" ] && [[ "$2" != --* ]]; then
                SQLITE_PATH="$2"
                shift 2
            else
                shift
            fi
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Commands:"
            echo "  --update                  Pull latest code from GitHub, backup DB, rebuild & restart"
            echo ""
            echo "Update options (use with --update):"
            echo "  --force                   Rebuild even if already up to date"
            echo "  --branch <branch>         Pull from specific branch (default: current branch)"
            echo "  --remote <remote>         Pull from specific remote (default: origin)"
            echo ""
            echo "Install options:"
            echo "  --production              Run in production mode (default)"
            echo "  --development             Run in development mode"
            echo "  --clean                   Clean installation (remove all previous data)"
            echo "  --keep-db                 Keep existing database during reinstall"
            echo "  --postgres-password <pwd> Set PostgreSQL password (generated if not provided)"
            echo "  --migrate-from-sqlite     Migrate from SQLite to PostgreSQL"
            echo "  --help, -h                Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 --update               # Pull latest from GitHub, backup DB, rebuild"
            echo "  $0 --update --force       # Force rebuild even if no new commits"
            echo "  $0 --update --branch dev  # Update from a specific branch"
            echo "  $0                        # Fresh PostgreSQL production installation"
            echo "  $0 --clean                # Clean installation (remove all data)"
            echo "  $0 --keep-db              # Reinstall but keep existing database"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# If --update was passed, run the update flow and exit
if [ "$UPDATE_MODE" = true ]; then
    update_from_github
fi

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
        echo
        echo -e "${BLUE}What would you like to do?${NC}"
        echo
        echo "  1) Update from GitHub   — Pull latest code, backup DB, rebuild (recommended)"
        echo "  2) Reinstall (keep DB)  — Full reinstall but preserve your database"
        echo "  3) Clean install        — Remove ALL data and start fresh"
        echo "  4) Cancel"
        echo
        read -p "Choose an option (1-4): " choice

        case $choice in
            1)
                update_from_github
                ;;
            2)
                KEEP_DATABASE=true
                cleanup_previous_installation
                ;;
            3)
                echo
                echo -e "${RED}WARNING: This will delete ALL data (users, stores, rules, fraud analyses).${NC}"
                read -p "Are you sure? Type 'yes' to confirm: " confirm
                if [ "$confirm" != "yes" ]; then
                    print_status "Cancelled."
                    exit 0
                fi
                cleanup_previous_installation
                ;;
            4)
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
        exec sg docker "$0" "$@"
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

# Step 3: Preserve existing settings or generate new ones
EXISTING_POSTGRES_PASSWORD=""
EXISTING_SECRET_KEY=""
EXISTING_ADMIN_SECRET_KEY=""
EXISTING_JWT_SECRET_KEY=""
EXISTING_ENCRYPTION_KEY=""

if [ "$KEEP_DATABASE" = "true" ]; then
    if [ -f .env ]; then
        print_status "Preserving existing secrets from .env..."
        EXISTING_POSTGRES_PASSWORD=$(grep '^POSTGRES_PASSWORD=' .env | cut -d'=' -f2- || true)
        EXISTING_SECRET_KEY=$(grep '^SECRET_KEY=' .env | cut -d'=' -f2- || true)
        EXISTING_ADMIN_SECRET_KEY=$(grep '^ADMIN_SECRET_KEY=' .env | cut -d'=' -f2- || true)
        EXISTING_JWT_SECRET_KEY=$(grep '^JWT_SECRET_KEY=' .env | cut -d'=' -f2- || true)
        EXISTING_ENCRYPTION_KEY=$(grep '^ENCRYPTION_KEY=' .env | cut -d'=' -f2- || true)
        if [ -n "$EXISTING_POSTGRES_PASSWORD" ]; then
            print_success "Existing secrets preserved (DB password, JWT keys, etc.)"
        else
            print_error "Could not read POSTGRES_PASSWORD from .env!"
            print_error "The database volume expects the original password."
            print_error "Check your backup at: ./backups/ for a .env.backup file"
            exit 1
        fi
    else
        # Check if there's a backup .env we can recover from
        LATEST_BACKUP_ENV=$(ls -t ./backups/*/\.env.backup 2>/dev/null | head -1)
        if [ -n "$LATEST_BACKUP_ENV" ]; then
            print_warning ".env not found, but found backup: $LATEST_BACKUP_ENV"
            print_status "Recovering secrets from backup..."
            EXISTING_POSTGRES_PASSWORD=$(grep '^POSTGRES_PASSWORD=' "$LATEST_BACKUP_ENV" | cut -d'=' -f2- || true)
            EXISTING_SECRET_KEY=$(grep '^SECRET_KEY=' "$LATEST_BACKUP_ENV" | cut -d'=' -f2- || true)
            EXISTING_ADMIN_SECRET_KEY=$(grep '^ADMIN_SECRET_KEY=' "$LATEST_BACKUP_ENV" | cut -d'=' -f2- || true)
            EXISTING_JWT_SECRET_KEY=$(grep '^JWT_SECRET_KEY=' "$LATEST_BACKUP_ENV" | cut -d'=' -f2- || true)
            EXISTING_ENCRYPTION_KEY=$(grep '^ENCRYPTION_KEY=' "$LATEST_BACKUP_ENV" | cut -d'=' -f2- || true)
            if [ -n "$EXISTING_POSTGRES_PASSWORD" ]; then
                print_success "Secrets recovered from backup"
            else
                print_error "Could not recover POSTGRES_PASSWORD from backup!"
                print_error "Cannot keep database without the original password."
                exit 1
            fi
        else
            print_error ".env file not found and no backup available!"
            print_error "Cannot keep database without the original password."
            print_error "Use --clean for a fresh installation instead."
            exit 1
        fi
    fi
fi

# Use existing values if preserving, otherwise generate new ones
if [ -n "$EXISTING_POSTGRES_PASSWORD" ]; then
    POSTGRES_PASSWORD="$EXISTING_POSTGRES_PASSWORD"
elif [ -z "$POSTGRES_PASSWORD" ]; then
    POSTGRES_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)
    print_warning "Generated PostgreSQL password (saved in .env file)"
fi

SECRET_KEY="${EXISTING_SECRET_KEY:-$(openssl rand -hex 32)}"
ADMIN_SECRET_KEY="${EXISTING_ADMIN_SECRET_KEY:-$(openssl rand -hex 32)}"
JWT_SECRET_KEY="${EXISTING_JWT_SECRET_KEY:-$(openssl rand -hex 32)}"
ENCRYPTION_KEY="${EXISTING_ENCRYPTION_KEY:-$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null || openssl rand -base64 32)}"

# Create .env file
print_status "Creating environment configuration..."
cat > .env <<EOF
# Server Configuration
SERVER_IP=$SERVER_IP
VITE_API_URL=http://$SERVER_IP:8000
ENVIRONMENT=$DEPLOYMENT_MODE

# Database Configuration (PostgreSQL)
DATABASE_URL=postgresql://shopify_user:${POSTGRES_PASSWORD}@postgres:5432/shopify_db
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=shopify_db
POSTGRES_USER=shopify_user
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Connection Pool Settings
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600

# CORS Configuration
CORS_ORIGINS=http://$SERVER_IP,http://$SERVER_IP:3000,http://localhost,http://localhost:3000

# Security
SECRET_KEY=${SECRET_KEY}
ADMIN_SECRET_KEY=${ADMIN_SECRET_KEY}
JWT_SECRET_KEY=${JWT_SECRET_KEY}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Shopify Configuration
SHOPIFY_API_VERSION=2025-04

# Redis Configuration
REDIS_URL=redis://redis:6379/0
REDIS_PASSWORD=
REDIS_MAX_CONNECTIONS=50

# Application Settings
LOG_LEVEL=$( [ "$DEPLOYMENT_MODE" = "production" ] && echo "INFO" || echo "DEBUG" )
WORKERS=$( [ "$DEPLOYMENT_MODE" = "production" ] && echo "4" || echo "1" )
EOF
print_success "Environment configuration created with PostgreSQL settings!"

# Step 4: Configure CORS origins for server IP
print_status "Configuring CORS origins for server IP..."
# CORS will be configured via environment variable in .env file
print_success "CORS will be configured via CORS_ORIGINS environment variable."

# Step 5: Create frontend environment file
print_status "Creating frontend environment configuration..."
if [ "$DEPLOYMENT_MODE" = "production" ]; then
    # In production, frontend goes through nginx /api/ proxy (no CORS needed)
    cat > frontend/.env <<EOF
VITE_API_URL=/api
EOF
    print_success "Frontend configured to use nginx proxy (/api)"
else
    # In development, frontend calls API directly
    cat > frontend/.env <<EOF
VITE_API_URL=http://$SERVER_IP:8000
EOF
    print_success "Frontend configured for direct API access"
fi

# Step 6: Verify configuration
print_status "Verifying configuration..."
if grep -q "CORS_ORIGINS=.*$SERVER_IP" .env; then
    print_success "✓ CORS configuration includes server IP"
else
    print_error "✗ CORS configuration missing server IP"
    exit 1
fi

if [ -f frontend/.env ] && grep -q "VITE_API_URL=" frontend/.env; then
    FRONTEND_API_URL=$(grep 'VITE_API_URL=' frontend/.env | cut -d'=' -f2-)
    print_success "✓ Frontend .env file has API URL: $FRONTEND_API_URL"
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
    docker exec $API_CONTAINER python run_all_migrations.py --check
    if [ $? -ne 0 ]; then
        print_status "Running pending migrations..."
        docker exec $API_CONTAINER python run_all_migrations.py
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
    docker exec $API_CONTAINER python run_all_migrations.py --check
    if [ $? -ne 0 ]; then
        print_warning "Database schema needs updating. Running migrations..."
        docker exec $API_CONTAINER python run_all_migrations.py
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
    print_status "Initializing PostgreSQL database..."
    
    # Wait for PostgreSQL to be ready
    print_status "Waiting for PostgreSQL to initialize..."
    for i in {1..30}; do
        if docker exec $POSTGRES_CONTAINER pg_isready -U shopify_user -d shopify_db &>/dev/null; then
            print_success "PostgreSQL is ready"
            break
        fi
        echo -n "."
        sleep 2
    done
    
    # Initialize database schema
    docker exec $API_CONTAINER python -c "
import sys
sys.path.append('/app')
from database import Base, engine
from models import *
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    # Create all tables
    Base.metadata.create_all(bind=engine)
    logger.info('PostgreSQL database schema created successfully')
    
    # Verify tables were created
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    logger.info(f'Created {len(tables)} tables: {tables}')
    
except Exception as e:
    logger.error(f'Failed to create database schema: {e}')
    sys.exit(1)
"

    if [ $? -eq 0 ]; then
        print_success "PostgreSQL database initialized successfully!"
        
        # Create migration tracking table for PostgreSQL
        print_status "Setting up migration tracking..."
        docker exec $API_CONTAINER python -c "
import sys
sys.path.append('/app')
from sqlalchemy import create_engine, text
import os
from datetime import datetime

DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Create migration tracking table
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_name TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''))
    
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
        'add_fraud_analyses_archive',
        'remove_age_checker_from_archive'
    ]
    
    for migration in migrations:
        conn.execute(text(
            'INSERT INTO schema_migrations (migration_name, applied_at) VALUES (:name, :date) ON CONFLICT DO NOTHING'
        ), {'name': migration, 'date': datetime.now()})
    
    conn.commit()
    print('Migration tracking configured for PostgreSQL')
"
        if [ $? -eq 0 ]; then
            print_success "Fresh install schema setup completed!"
        else
            print_warning "Migration tracking setup had issues (not critical)"
        fi
    else
        print_error "Database initialization failed!"
        exit 1
    fi
    
    # Check if we should migrate from SQLite
    if [ "$MIGRATE_FROM_SQLITE" = true ] && [ -f "$SQLITE_PATH" ]; then
        print_status "Migrating data from SQLite to PostgreSQL..."
        
        # Copy SQLite database to container
        docker cp "$SQLITE_PATH" $API_CONTAINER:/tmp/sqlite_backup.db
        
        # Perform migration
        docker exec $API_CONTAINER python -c "
import sys
sys.path.append('/app')
import sqlite3
from sqlalchemy import create_engine, text
from database import SessionLocal
import os
import json

# Connect to SQLite
sqlite_conn = sqlite3.connect('/tmp/sqlite_backup.db')
sqlite_conn.row_factory = sqlite3.Row
sqlite_cursor = sqlite_conn.cursor()

# Connect to PostgreSQL
pg_session = SessionLocal()

try:
    # Migrate users
    print('Migrating users...')
    sqlite_cursor.execute('SELECT * FROM users')
    users = sqlite_cursor.fetchall()
    for user in users:
        pg_session.execute(text('''
            INSERT INTO users (id, email, username, password_hash, full_name, is_active, created_at)
            VALUES (:id, :email, :username, :password_hash, :full_name, :is_active, :created_at)
            ON CONFLICT (id) DO NOTHING
        '''), dict(user))
    
    # Migrate stores
    print('Migrating stores...')
    sqlite_cursor.execute('SELECT * FROM stores')
    stores = sqlite_cursor.fetchall()
    for store in stores:
        pg_session.execute(text('''
            INSERT INTO stores (id, user_id, store_name, shop_domain, access_token, webhook_id, is_active, created_at)
            VALUES (:id, :user_id, :store_name, :shop_domain, :access_token, :webhook_id, :is_active, :created_at)
            ON CONFLICT (id) DO NOTHING
        '''), dict(store))
    
    # Migrate rules
    print('Migrating rules...')
    sqlite_cursor.execute('SELECT * FROM rules')
    rules = sqlite_cursor.fetchall()
    for rule in rules:
        pg_session.execute(text('''
            INSERT INTO rules (id, store_id, name, description, conditions, actions, priority, is_active, created_at, delay_ms)
            VALUES (:id, :store_id, :name, :description, :conditions, :actions, :priority, :is_active, :created_at, :delay_ms)
            ON CONFLICT (id) DO NOTHING
        '''), dict(rule))
    
    pg_session.commit()
    print('Data migration completed successfully')
    
except Exception as e:
    print(f'Migration error: {e}')
    pg_session.rollback()
finally:
    sqlite_conn.close()
    pg_session.close()
"
        
        if [ $? -eq 0 ]; then
            print_success "Data migrated from SQLite to PostgreSQL"
        else
            print_warning "Data migration had issues (some data may not have migrated)"
        fi
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
    # In production, nginx serves on port 80
    if curl -f -s http://localhost > /dev/null; then
        print_success "Frontend is accessible on port 80!"
    else
        print_warning "Frontend might still be starting up (nginx may need a moment)..."
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
docker exec $API_CONTAINER python -c "
import sys
sys.path.append('/app')
from database import SessionLocal
from models import AdminUser
from admin_auth import get_admin_password_hash

db = SessionLocal()
try:
    # Check if admin user already exists
    existing_admin = db.query(AdminUser).filter(AdminUser.username == 'admin').first()
    if not existing_admin:
        # Create default admin user
        admin_user = AdminUser(
            username='admin',
            email='admin@shopify-automation.local',
            full_name='System Administrator',
            hashed_password=get_admin_password_hash('admin'),
            role='super_admin',
            is_active=True
        )
        db.add(admin_user)
        db.commit()
        print('✅ Admin user created successfully!')
        print('  Username: admin')
        print('  Password: admin')
    else:
        print('✅ Admin user already exists')
        print('  Username: admin')
        print('  Password: admin (if not changed)')
except Exception as e:
    print(f'Error with admin user: {e}')
    db.rollback()
finally:
    db.close()
"

# Step 11: Display success message
echo
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          Installation completed successfully!             ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo
echo -e "${BLUE}Access the application:${NC}"
echo -e "  Main App:    ${GREEN}http://$SERVER_IP${NC}"
echo -e "  API Docs:    ${GREEN}http://$SERVER_IP/docs${NC}"
echo -e "  Admin Panel: ${GREEN}http://$SERVER_IP/admin${NC}"
echo
echo -e "${BLUE}PostgreSQL Database:${NC}"
echo -e "  Host:     localhost (or container: postgres)"
echo -e "  Port:     5432"
echo -e "  Database: shopify_db"
echo -e "  Username: shopify_user"
echo -e "  Password: ${YELLOW}[Saved in .env file]${NC}"
echo
echo -e "${BLUE}Default Admin Credentials:${NC}"
echo -e "  Username: ${YELLOW}admin${NC}"
echo -e "  Password: ${YELLOW}admin${NC}"
echo -e "  ${RED}⚠️  Change the admin password immediately after first login!${NC}"
echo
echo -e "${BLUE}Monitor services:${NC}"
echo -e "  View logs:        ${YELLOW}docker compose -f $COMPOSE_FILE logs -f${NC}"
echo -e "  Service status:   ${YELLOW}docker compose -f $COMPOSE_FILE ps${NC}"
echo -e "  Database console: ${YELLOW}docker exec -it $POSTGRES_CONTAINER psql -U shopify_user -d shopify_db${NC}"
echo -e "  Backup database:  ${YELLOW}docker exec $POSTGRES_CONTAINER pg_dump -U shopify_user shopify_db > backup.sql${NC}"

# Verify schema is up to date
print_status "Verifying database schema..."
docker exec $API_CONTAINER python run_all_migrations.py --check > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Database schema is up to date${NC}"
else
    echo -e "${YELLOW}⚠ Database schema may need attention. Run: docker exec $API_CONTAINER python run_all_migrations.py${NC}"
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