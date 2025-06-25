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

print_status "Starting installation process..."

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
        
        # Add Docker's official GPG key
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
        
        # Add Docker repository
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
          $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
        
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
    sudo systemctl start docker
    sudo systemctl enable docker
    
    print_success "Docker installed successfully!"
    print_warning "You need to log out and back in for group changes to take effect."
    
    # Try to activate group without logout (may not work on all systems)
    newgrp docker || true
else
    print_success "Docker is already installed."
fi

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

# Step 3: Setup environment file
print_status "Setting up environment configuration..."
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        
        # Generate a secure secret key
        SECRET_KEY=$(openssl rand -hex 32)
        
        # Update the secret key in .env
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            sed -i '' "s/your-secret-key-change-this-in-production-use-at-least-32-chars/$SECRET_KEY/" .env
        else
            # Linux
            sed -i "s/your-secret-key-change-this-in-production-use-at-least-32-chars/$SECRET_KEY/" .env
        fi
        
        print_success "Environment file created with secure secret key."
        print_warning "Please edit .env file to add your Shopify API credentials if needed."
    else
        print_error ".env.example file not found!"
        exit 1
    fi
else
    print_warning ".env file already exists. Skipping..."
fi

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

# Check API health
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health | grep -q "200"; then
    print_success "API is healthy!"
else
    print_warning "API health check failed. It may still be starting up."
fi

# Final summary
echo
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}       Installation completed successfully!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo
echo -e "${BLUE}Access your application at:${NC}"
echo -e "  • Frontend: ${GREEN}http://localhost:3000${NC}"
echo -e "  • API Docs: ${GREEN}http://localhost:8000/docs${NC}"
echo
echo -e "${BLUE}Next steps:${NC}"
echo -e "  1. Register a new user at ${GREEN}http://localhost:3000/register${NC}"
echo -e "  2. Add your Shopify stores in Settings → Stores"
echo -e "  3. Create processing rules in the Rules section"
echo -e "  4. Configure sync settings in Settings → Order Processing"
echo
echo -e "${YELLOW}Important:${NC}"
echo -e "  • To view logs: ${GREEN}docker compose logs -f${NC}"
echo -e "  • To stop services: ${GREEN}docker compose stop${NC}"
echo -e "  • To update: ${GREEN}./update.sh${NC}"
echo
echo -e "${YELLOW}If you added yourself to the docker group, please log out and back in.${NC}"
echo