#!/bin/bash

# Shopify Multi-Store Order Management System
# Automated Installation Script for Linux

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
echo "║              Automated Installation Script                ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

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
    
    # Stop and remove containers
    if docker compose ps >/dev/null 2>&1; then
        docker compose down -v 2>/dev/null || true
    fi
    
    # Remove Docker images
    docker rmi $(docker images | grep shopify | awk '{print $3}') 2>/dev/null || true
    
    # Clean up Docker system
    docker system prune -f
    
    # Remove logs
    sudo rm -rf logs/* 2>/dev/null || true
    
    print_success "Previous installation cleaned up."
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
    print_success "Server IP set to: $SERVER_IP"
}

print_status "Starting installation process..."

# Check if this is a cleanup/reinstall
if [ "$1" = "--clean" ] || [ -f docker-compose.yml ]; then
    if [ "$1" = "--clean" ]; then
        cleanup_previous_installation
    else
        read -p "Previous installation detected. Clean up first? (Y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            cleanup_previous_installation
        fi
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
        print_error "Try running: sudo dockerd"
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
mkdir -p nginx/ssl
print_success "Directories created."

# Step 3: Setup environment file and docker-compose
print_status "Setting up environment configuration..."

# Always recreate .env with current settings
if [ -f .env.example ]; then
    cp .env.example .env
    
    # Generate a secure secret key
    SECRET_KEY=$(openssl rand -hex 32)
    
    # Update the secret key and API URL in .env
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/your-secret-key-change-this-in-production-use-at-least-32-chars/$SECRET_KEY/" .env
        sed -i '' "s|VITE_API_URL=http://localhost:8000|VITE_API_URL=http://$SERVER_IP/api|" .env
    else
        # Linux
        sed -i "s/your-secret-key-change-this-in-production-use-at-least-32-chars/$SECRET_KEY/" .env
        sed -i "s|VITE_API_URL=http://localhost:8000|VITE_API_URL=http://$SERVER_IP/api|" .env
    fi
    
    print_success "Environment file created with secure secret key and correct API URL."
else
    print_error ".env.example file not found!"
    exit 1
fi

# Update docker-compose.yml with correct API URL
print_status "Updating docker-compose configuration..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    sed -i '' "s|VITE_API_URL=http://localhost:8000|VITE_API_URL=http://$SERVER_IP/api|" docker-compose.yml
else
    # Linux
    sed -i "s|VITE_API_URL=http://localhost:8000|VITE_API_URL=http://$SERVER_IP/api|" docker-compose.yml
fi

print_success "Docker configuration updated with correct API URL."

# Step 4: Check port availability
print_status "Checking port availability..."
PORTS=(8000 3000 80 6379)
PORTS_IN_USE=()

for port in "${PORTS[@]}"; do
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        PORTS_IN_USE+=($port)
    fi
done

if [ ${#PORTS_IN_USE[@]} -ne 0 ]; then
    print_warning "The following ports are already in use: ${PORTS_IN_USE[*]}"
    print_warning "Please stop the conflicting services or change the ports in .env file"
    read -p "Do you want to continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Step 5: Build Docker images
print_status "Building Docker images (this may take a few minutes)..."
docker compose build
print_success "Docker images built successfully!"

# Step 6: Start services
print_status "Starting all services..."
docker compose up -d

# Wait for services to start
print_status "Waiting for services to initialize..."
sleep 30

# Check if services are running
if docker compose ps | grep -q "Exit"; then
    print_error "Some services failed to start. Checking logs..."
    docker compose logs --tail=50
    exit 1
fi

print_success "All services started successfully!"

# Step 7: Initialize database
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
else
    print_error "Database initialization failed!"
    exit 1
fi

# Step 8: Health check
print_status "Performing health check..."
sleep 5

# Check application health via nginx
if curl -s -o /dev/null -w "%{http_code}" http://$SERVER_IP/health | grep -q "200"; then
    print_success "Application is healthy and accessible via nginx!"
else
    print_warning "Health check failed. The application may still be starting up."
fi

# Check direct API health
if curl -s -o /dev/null -w "%{http_code}" http://$SERVER_IP:8000/health | grep -q "200"; then
    print_success "Direct API is also healthy!"
else
    print_warning "Direct API health check failed but this is normal if using nginx proxy only."
fi

# Final summary
echo
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}       Installation completed successfully!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo
echo -e "${BLUE}🌐 Access your application at:${NC}"
echo -e "  • ${GREEN}Frontend (Main App): http://$SERVER_IP${NC}"
echo -e "  • ${GREEN}API Documentation: http://$SERVER_IP/api/docs${NC}"
echo -e "  • ${GREEN}Direct API Access: http://$SERVER_IP:8000/docs${NC} (if needed)"
echo
echo -e "${BLUE}📝 Next steps:${NC}"
echo -e "  1. Open ${GREEN}http://$SERVER_IP${NC} in your browser"
echo -e "  2. Register a new user account"
echo -e "  3. Add your Shopify stores in Settings → Stores"
echo -e "  4. Create processing rules in the Rules section"
echo -e "  5. Configure sync settings in Settings → Order Processing"
echo
echo -e "${YELLOW}⚙️  Management commands:${NC}"
echo -e "  • View logs: ${GREEN}docker compose logs -f${NC}"
echo -e "  • Stop services: ${GREEN}docker compose stop${NC}"
echo -e "  • Update application: ${GREEN}./update.sh${NC}"
echo -e "  • Clean reinstall: ${GREEN}./install.sh --clean${NC}"
echo
echo -e "${YELLOW}🔧 Configuration:${NC}"
echo -e "  • Server IP: ${GREEN}$SERVER_IP${NC}"
echo -e "  • Frontend served via nginx on port 80"
echo -e "  • API proxied through /api/ path"
echo -e "  • Backend running on port 8000 (internal)"
echo
if [[ "$SERVER_IP" != "localhost" && "$SERVER_IP" != "127.0.0.1" ]]; then
    echo -e "${BLUE}🌐 Network Access:${NC}"
    echo -e "  • The application is accessible from other devices on your network"
    echo -e "  • Make sure port 80 is open in your firewall if needed"
    echo
fi
echo -e "${YELLOW}ℹ️  If you added yourself to the docker group, please log out and back in.${NC}"
echo