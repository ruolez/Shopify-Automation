#!/bin/bash

# Shopify Multi-Store Order Management System
# Update Script - Pull latest changes and rebuild

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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
echo "║                    Update Script                          ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker and try again."
    exit 1
fi

# Step 1: Check for uncommitted changes
print_status "Checking for uncommitted changes..."
if [[ -n $(git status -s) ]]; then
    print_warning "You have uncommitted changes:"
    git status -s
    read -p "Do you want to stash these changes and continue? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git stash push -m "Auto-stash before update $(date +%Y%m%d-%H%M%S)"
        print_success "Changes stashed."
    else
        print_error "Update cancelled. Please commit or stash your changes first."
        exit 1
    fi
fi

# Step 2: Pull latest changes
print_status "Pulling latest changes from repository..."
git pull origin main
if [ $? -eq 0 ]; then
    print_success "Successfully pulled latest changes."
else
    print_error "Failed to pull changes. Please check your git configuration."
    exit 1
fi

# Step 3: Check for .env updates
print_status "Checking for environment configuration updates..."
if [ -f .env.example ]; then
    # Check if there are new variables in .env.example that aren't in .env
    if [ -f .env ]; then
        NEW_VARS=$(comm -23 <(grep -E "^[A-Z_]+=" .env.example | cut -d= -f1 | sort) <(grep -E "^[A-Z_]+=" .env | cut -d= -f1 | sort))
        if [ ! -z "$NEW_VARS" ]; then
            print_warning "New environment variables detected:"
            echo "$NEW_VARS"
            print_warning "Please add these to your .env file after the update."
        fi
    fi
fi

# Step 4: Backup database
print_status "Creating database backup..."
BACKUP_NAME="db-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
if docker run --rm -v shopify-automation_sqlite_data:/data -v $(pwd)/backups:/backup alpine tar czf /backup/$BACKUP_NAME -C /data . 2>/dev/null; then
    print_success "Database backed up to backups/$BACKUP_NAME"
else
    print_warning "Database backup failed. Continuing anyway..."
fi

# Step 5: Stop services
print_status "Stopping services..."
docker compose down
print_success "Services stopped."

# Step 6: Clear Docker cache (important for frontend changes)
print_status "Clearing Docker build cache..."
docker system prune -f
print_success "Docker cache cleared."

# Step 7: Rebuild images
print_status "Rebuilding Docker images (this may take a few minutes)..."
docker compose build --no-cache
print_success "Docker images rebuilt."

# Step 8: Start services
print_status "Starting services..."
docker compose up -d

# Wait for services to start
print_status "Waiting for services to initialize..."
sleep 30

# Step 9: Run database migrations if needed
print_status "Checking for database updates..."
docker exec shopify_api python -c "
from database import Base, engine
from models import *
try:
    # This will create any new tables/columns
    Base.metadata.create_all(bind=engine)
    print('Database schema updated successfully!')
except Exception as e:
    print(f'Database update failed: {e}')
    exit(1)
"

if [ $? -eq 0 ]; then
    print_success "Database schema updated!"
else
    print_warning "Database update failed. Manual intervention may be required."
fi

# Step 10: Health check
print_status "Performing health check..."
sleep 5

# Check API health
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health | grep -q "200"; then
    print_success "API is healthy!"
else
    print_warning "API health check failed. It may still be starting up."
fi

# Check services status
print_status "Checking service status..."
docker compose ps

# Final summary
echo
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}            Update completed successfully!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo
echo -e "${BLUE}Your application has been updated to the latest version.${NC}"
echo
echo -e "${YELLOW}Post-update checklist:${NC}"
echo -e "  • Check logs for any errors: ${GREEN}docker compose logs -f${NC}"
echo -e "  • Verify your stores are still connected"
echo -e "  • Test your processing rules"
echo -e "  • Review any new environment variables in .env.example"
echo
echo -e "${BLUE}Access your application at:${NC}"
echo -e "  • Frontend: ${GREEN}http://localhost:3000${NC}"
echo -e "  • API Docs: ${GREEN}http://localhost:8000/docs${NC}"
echo

# Check if there were stashed changes
if git stash list | grep -q "Auto-stash before update"; then
    print_warning "You have stashed changes. To restore them, run: git stash pop"
fi