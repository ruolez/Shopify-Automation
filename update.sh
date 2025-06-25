#!/bin/bash

# Shopify Automation - Update Script
# Safely updates the application while preserving data

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
COMPOSE_FILE="docker-compose.prod.yml"

# Get server IP from existing configuration
get_server_ip() {
    # Try to get server IP from existing frontend/.env
    if [ -f "frontend/.env" ]; then
        SERVER_IP=$(grep "VITE_API_URL" frontend/.env | cut -d'=' -f2 | sed 's/http:\/\/\([^:]*\):.*/\1/')
    elif [ -f ".env" ]; then
        SERVER_IP=$(grep "VITE_API_URL" .env | cut -d'=' -f2 | sed 's/http:\/\/\([^:]*\):.*/\1/')
    else
        SERVER_IP="localhost"
    fi
    
    if [ -z "$SERVER_IP" ] || [ "$SERVER_IP" = "localhost" ]; then
        print_warning "Could not determine server IP from configuration files."
        read -p "Please enter your server IP address (e.g., 192.168.1.112): " SERVER_IP
        if [ -z "$SERVER_IP" ]; then
            SERVER_IP="localhost"
        fi
    fi
    
    export SERVER_IP
    export VITE_API_URL="http://$SERVER_IP:8000"
    print_info "Using server IP: $SERVER_IP"
}

print_header() {
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}     Shopify Automation - Update Script        ${NC}"
    echo -e "${BLUE}================================================${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Function to backup database and redis data
backup_data() {
    print_info "Creating backup in $BACKUP_DIR..."
    mkdir -p "$BACKUP_DIR"
    
    # Backup SQLite database
    if docker volume inspect shopify-automation_sqlite_data >/dev/null 2>&1; then
        print_info "Backing up SQLite database..."
        docker run --rm -v shopify-automation_sqlite_data:/source -v "$(pwd)/$BACKUP_DIR:/backup" alpine tar czf /backup/sqlite_data.tar.gz -C /source .
        print_success "Database backed up to $BACKUP_DIR/sqlite_data.tar.gz"
    else
        print_warning "SQLite volume not found, skipping database backup"
    fi
    
    # Backup Redis data
    if docker volume inspect shopify-automation_redis_data >/dev/null 2>&1; then
        print_info "Backing up Redis data..."
        docker run --rm -v shopify-automation_redis_data:/source -v "$(pwd)/$BACKUP_DIR:/backup" alpine tar czf /backup/redis_data.tar.gz -C /source .
        print_success "Redis data backed up to $BACKUP_DIR/redis_data.tar.gz"
    else
        print_warning "Redis volume not found, skipping Redis backup"
    fi
    
    # Backup logs if they exist
    if [ -d "./logs" ]; then
        print_info "Backing up logs..."
        cp -r ./logs "$BACKUP_DIR/"
        print_success "Logs backed up"
    fi
}

# Function to restore database from backup
restore_data() {
    local backup_path="$1"
    
    if [ ! -d "$backup_path" ]; then
        print_error "Backup directory $backup_path does not exist!"
        return 1
    fi
    
    print_info "Restoring data from $backup_path..."
    
    # Restore SQLite database
    if [ -f "$backup_path/sqlite_data.tar.gz" ]; then
        print_info "Restoring SQLite database..."
        docker run --rm -v shopify-automation_sqlite_data:/target -v "$(pwd)/$backup_path:/backup" alpine sh -c "rm -rf /target/* && tar xzf /backup/sqlite_data.tar.gz -C /target"
        print_success "Database restored"
    fi
    
    # Restore Redis data
    if [ -f "$backup_path/redis_data.tar.gz" ]; then
        print_info "Restoring Redis data..."
        docker run --rm -v shopify-automation_redis_data:/target -v "$(pwd)/$backup_path:/backup" alpine sh -c "rm -rf /target/* && tar xzf /backup/redis_data.tar.gz -C /target"
        print_success "Redis data restored"
    fi
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --keep-db              Keep existing database (don't backup/restore)"
    echo "  --backup-only          Only create backup, don't update"
    echo "  --restore-from PATH    Restore from specific backup directory"
    echo "  --no-pull              Don't pull latest code from git"
    echo "  --help, -h             Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                     # Full update with backup"
    echo "  $0 --keep-db           # Update code only, keep existing database"
    echo "  $0 --backup-only       # Just create a backup"
    echo "  $0 --restore-from ./backups/20231225_143000  # Restore from specific backup"
}

# Parse command line arguments
KEEP_DB=false
BACKUP_ONLY=false
RESTORE_FROM=""
NO_PULL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-db)
            KEEP_DB=true
            shift
            ;;
        --backup-only)
            BACKUP_ONLY=true
            shift
            ;;
        --restore-from)
            RESTORE_FROM="$2"
            shift 2
            ;;
        --no-pull)
            NO_PULL=true
            shift
            ;;
        --help|-h)
            show_usage
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Main execution
print_header

# Get server configuration
get_server_ip

# Handle restore-from option
if [ -n "$RESTORE_FROM" ]; then
    print_info "Restoring from backup: $RESTORE_FROM"
    
    # Stop services
    print_info "Stopping services..."
    docker-compose -f "$COMPOSE_FILE" down
    
    # Restore data
    restore_data "$RESTORE_FROM"
    
    # Start services
    print_info "Starting services..."
    docker-compose -f "$COMPOSE_FILE" up -d
    
    print_success "Restore completed!"
    exit 0
fi

# Create backup (unless keeping database)
BACKUP_CREATED=false
if [ "$BACKUP_ONLY" = true ] || [ "$KEEP_DB" = false ]; then
    backup_data
    BACKUP_CREATED=true
fi

# Exit if backup-only
if [ "$BACKUP_ONLY" = true ]; then
    print_success "Backup completed!"
    exit 0
fi

# Pull latest code
if [ "$NO_PULL" = false ]; then
    print_info "Pulling latest code from repository..."
    if git pull origin main; then
        print_success "Code updated successfully"
    else
        print_warning "Git pull failed, continuing with local changes"
    fi
fi

# Update configuration files with server IP
print_info "Updating configuration files with server IP: $SERVER_IP"

# Create/update frontend .env file
print_info "Creating frontend .env file..."
cat > frontend/.env << EOF
VITE_API_URL=http://$SERVER_IP:8000
EOF

# Update CORS configuration in backend
print_info "Updating CORS configuration..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    sed -i '' "s|allow_origins=\[.*\]|allow_origins=[\"http://$SERVER_IP:3000\", \"http://$SERVER_IP\", \"http://localhost:3000\", \"http://localhost\"]|" backend/main.py
else
    # Linux
    sed -i "s|allow_origins=\[.*\]|allow_origins=[\"http://$SERVER_IP:3000\", \"http://$SERVER_IP\", \"http://localhost:3000\", \"http://localhost\"]|" backend/main.py
fi

print_success "Configuration updated for server IP: $SERVER_IP"

# Stop services
print_info "Stopping services..."
docker-compose -f "$COMPOSE_FILE" down

# Rebuild containers (force rebuild to get latest changes)
print_info "Rebuilding containers..."
docker-compose -f "$COMPOSE_FILE" build --no-cache

# Start services
print_info "Starting updated services..."
docker-compose -f "$COMPOSE_FILE" up -d

# Wait for services to be ready
print_info "Waiting for services to start..."
sleep 10

# Restore database backup if one was created
if [ "$BACKUP_CREATED" = true ] && [ "$KEEP_DB" = false ]; then
    print_info "Restoring database from backup created during this update..."
    restore_data "$BACKUP_DIR"
    print_success "Database restored from backup!"
fi

# Check if services are running
print_info "Checking service status..."
if docker-compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
    print_success "Services are running!"
else
    print_error "Some services may not be running properly"
    docker-compose -f "$COMPOSE_FILE" ps
fi

print_success "Update completed!"
print_info "Backup saved to: $BACKUP_DIR"

if [ "$KEEP_DB" = false ]; then
    print_info "Database was backed up and automatically restored"
else
    print_info "Database was kept without backup (using existing data)"
fi

print_info "You can now access the application at http://localhost"
print_info "Hot reload is enabled for frontend development"

echo ""
print_info "Useful commands:"
echo "  docker-compose -f $COMPOSE_FILE logs -f     # View logs"
echo "  docker-compose -f $COMPOSE_FILE ps          # Check status"
echo "  ./update.sh --restore-from $BACKUP_DIR      # Restore this backup"