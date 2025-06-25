# Shopify Multi-Store Order Management System

A powerful automated order processing system for managing multiple Shopify stores with custom rules, real-time synchronization, and comprehensive logging.

## 🚀 Quick Start - Linux Docker Installation

### One-Command Installation

```bash
git clone https://github.com/ruolez/Shopify-Automation.git
cd Shopify-Automation
./install.sh
```

The install script will:
- Install Docker and Docker Compose v2 automatically
- Ask for your server IP address
- Configure the application for network access
- Set up all services on port 80
- Create secure environment configuration

### Prerequisites

- Linux-based operating system (Ubuntu 20.04+ recommended)  
- Git
- At least 4GB RAM and 10GB free disk space
- **Note**: Docker and dependencies will be installed automatically

### Step 1: Install Docker (if not already installed)

```bash
# Update package index
sudo apt update

# Install prerequisites
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common

# Add Docker's official GPG key
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Add Docker repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Add your user to docker group (logout/login required after this)
sudo usermod -aG docker $USER

# Verify installation
docker --version
docker compose version
```

### Step 2: Clone the Repository

```bash
# Clone the repository
git clone https://github.com/yourusername/shopify-automation.git
cd shopify-automation

# Create necessary directories
mkdir -p logs
mkdir -p nginx/ssl
```

### Step 3: Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit the .env file with your settings
nano .env
```

**Important: Update these values in your .env file:**
```bash
# Security - MUST CHANGE FOR PRODUCTION
SECRET_KEY=generate-a-secure-random-key-here-at-least-32-chars

# Optional - Change ports if needed
API_PORT=8000
FRONTEND_PORT=3000
NGINX_PORT=80

# Optional - Shopify API (add if you have credentials)
SHOPIFY_API_VERSION=2025-04
SHOPIFY_DEBUG=false
```

To generate a secure secret key:
```bash
# Generate a secure random key
openssl rand -hex 32
```

### Step 4: Build and Start the Application

```bash
# Build all Docker images
docker compose build

# Start all services in detached mode
docker compose up -d

# Wait for services to initialize (about 30 seconds)
sleep 30

# Check service status
docker compose ps

# View logs to ensure everything started correctly
docker compose logs --tail=50
```

### Step 5: Initialize the Database

```bash
# Create database tables
docker exec shopify_api python -c "
from database import Base, engine
from models import *
Base.metadata.create_all(bind=engine)
print('Database initialized successfully!')
"
```

### Step 6: Access the Application

The installation script will ask for your server IP address and configure everything automatically.

Open your web browser and navigate to:
- **Frontend**: http://[YOUR-SERVER-IP] (port 80)
- **API Documentation**: http://[YOUR-SERVER-IP]/api/docs  
- **Health Check**: http://[YOUR-SERVER-IP]/health

For example, if your server IP is 192.168.1.112:
- **Frontend**: http://192.168.1.112
- **API Documentation**: http://192.168.1.112/api/docs

### Step 7: Create Your First User

1. Navigate to http://[YOUR-SERVER-IP]/register (the install script will show you the exact URL)
2. Create an account with your email and password
3. Login with your credentials

## 🛠️ Common Operations

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f frontend
```

### Restart Services

```bash
# Restart all services
docker compose restart

# Restart specific service
docker compose restart api
docker compose restart worker
```

### Stop the Application

```bash
# Stop all services (data persists)
docker compose stop

# Stop and remove containers (data persists in volumes)
docker compose down

# Complete cleanup (WARNING: removes all data)
docker compose down -v
```

### Update the Application

```bash
# Using the update script (recommended)
./update.sh

# Manual update
git pull
docker compose down
docker compose build
docker compose up -d
```

### Clean Reinstall

```bash
# Clean up previous installation and reinstall
./install.sh --clean

# This will:
# - Stop and remove all containers
# - Remove Docker images  
# - Clean up logs and data
# - Ask for server IP again
# - Reinstall everything fresh
```

## 🔧 Troubleshooting

### Port Conflicts

If you get port binding errors:
```bash
# Check what's using the ports
sudo lsof -i :8000
sudo lsof -i :3000
sudo lsof -i :80

# Change ports in .env file:
API_PORT=8001
FRONTEND_PORT=3001
NGINX_PORT:8080
```

### Database Issues

```bash
# Reset database (WARNING: loses all data)
docker compose down -v
docker compose up -d
# Then re-run Step 5 (Initialize Database)
```

### Worker Not Processing Orders

```bash
# Check worker logs
docker compose logs worker --tail=100

# Restart worker
docker compose restart worker

# Check Redis connection
docker exec shopify_api python -c "import redis; r=redis.from_url('redis://redis:6379/0'); print('Redis OK' if r.ping() else 'Redis Error')"
```

### Frontend Changes Not Showing

```bash
# Clear Docker build cache and rebuild
docker compose down
docker system prune -f
docker compose build --no-cache frontend
docker compose up -d
```

### Permission Issues

```bash
# Fix log directory permissions
sudo chown -R $USER:$USER logs/

# Fix volume permissions
docker compose down
sudo rm -rf sqlite_data/
docker compose up -d
```

## 📊 System Requirements

### Minimum Requirements
- **CPU**: 2 cores
- **RAM**: 4GB
- **Storage**: 10GB free space
- **OS**: Ubuntu 20.04+, Debian 11+, CentOS 8+

### Recommended for Production
- **CPU**: 4+ cores
- **RAM**: 8GB+
- **Storage**: 50GB+ SSD
- **OS**: Ubuntu 22.04 LTS

## 🔒 Security Notes

1. **Change the SECRET_KEY**: The default key is insecure. Always generate a new one for production.
2. **Firewall**: Only expose necessary ports (80/443) to the internet.
3. **Updates**: Regularly update Docker images and system packages.
4. **Backups**: The SQLite database is stored in the `sqlite_data` volume. Back it up regularly:
   ```bash
   # Backup database
   docker run --rm -v shopify-automation_sqlite_data:/data -v $(pwd):/backup alpine tar czf /backup/db-backup-$(date +%Y%m%d).tar.gz -C /data .
   ```

## 🚀 Next Steps

1. **Connect Shopify Stores**: Go to Settings → Stores and add your Shopify store credentials
2. **Create Processing Rules**: Navigate to Rules and create your first automation rule
3. **Configure Sync Settings**: Adjust order sync frequency in Settings → Order Processing
4. **Monitor Activity**: Check Order Logs to see processed orders and rule executions

## 📝 Additional Resources

- **API Documentation**: http://localhost:8000/docs
- **Debug Endpoints**: See CLAUDE.md for advanced debugging commands
- **Support**: Create an issue on GitHub for help

## 🐛 Known Issues

1. **Frontend Cache**: Docker may cache frontend builds. Use the provided clear cache command if changes don't appear.
2. **SQLite Locking**: Under heavy load, SQLite may experience locking. Consider PostgreSQL for production.
3. **Rate Limiting**: Shopify API has rate limits. The system handles this automatically but may slow down during bulk operations.

---

For detailed development instructions and advanced configuration, see CLAUDE.md in the project root.