#!/bin/bash

# Quick fix script to update API URL without full reinstall

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║              Quick API URL Fix Script                    ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Get server IP
read -p "Enter your server IP address (e.g., 192.168.1.112): " SERVER_IP

if [ -z "$SERVER_IP" ]; then
    print_error "Server IP is required!"
    exit 1
fi

print_status "Updating configuration for server IP: $SERVER_IP"

# Update .env file
if [ -f .env ]; then
    print_status "Updating .env file..."
    sed -i "s|VITE_API_URL=.*|VITE_API_URL=http://$SERVER_IP:8000|" .env
    print_success ".env updated"
else
    print_error ".env file not found!"
    exit 1
fi

# Update docker-compose.yml
if [ -f docker-compose.yml ]; then
    print_status "Updating docker-compose.yml..."
    sed -i "s|VITE_API_URL=.*|VITE_API_URL=http://$SERVER_IP:8000|" docker-compose.yml
    print_success "docker-compose.yml updated"
fi

# Update CORS in backend
if [ -f backend/main.py ]; then
    print_status "Updating CORS configuration..."
    sed -i "s|allow_origins=\[.*\]|allow_origins=[\"http://$SERVER_IP:3000\", \"http://$SERVER_IP\", \"http://localhost:3000\", \"http://localhost\"]|" backend/main.py
    print_success "CORS configuration updated"
fi

# Stop services
print_status "Stopping services..."
docker compose down

# Clear Docker cache and rebuild
print_warning "Clearing Docker cache and rebuilding (this may take a few minutes)..."
docker system prune -f
docker compose build --no-cache

# Start services
print_status "Starting services..."
docker compose up -d

# Wait for services
print_status "Waiting for services to start..."
sleep 30

# Test API
print_status "Testing API connection..."
if curl -s -o /dev/null -w "%{http_code}" http://$SERVER_IP:8000/health | grep -q "200"; then
    print_success "API is accessible at http://$SERVER_IP:8000"
else
    print_warning "API test failed - it may still be starting"
fi

# Test frontend
print_status "Testing frontend..."
if curl -s -o /dev/null -w "%{http_code}" http://$SERVER_IP/ | grep -q "200"; then
    print_success "Frontend is accessible at http://$SERVER_IP"
else
    print_warning "Frontend test failed - it may still be starting"
fi

echo
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}              Configuration Updated!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo
echo -e "${BLUE}🌐 Access your application at:${NC}"
echo -e "  • ${GREEN}Frontend: http://$SERVER_IP${NC}"
echo -e "  • ${GREEN}API: http://$SERVER_IP:8000${NC}"
echo
echo -e "${YELLOW}If the registration still doesn't work, try:${NC}"
echo -e "  1. Clear your browser cache (Ctrl+Shift+Del)"
echo -e "  2. Try incognito/private mode"
echo -e "  3. Check browser console for any error details"
echo