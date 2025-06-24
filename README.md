# Shopify Multi-Store Order Management System

A comprehensive automated order processing and tagging system for managing multiple Shopify stores with advanced rule-based automation, real-time order synchronization, and detailed reporting capabilities.

## Features

- **Multi-Store Management**: Connect and manage multiple Shopify stores from a single dashboard
- **Advanced Rule Engine**: Create complex automation rules with 15+ operators and conditions
- **Real-Time Processing**: Automated order synchronization and rule execution via background tasks
- **Fulfillment Management**: Intelligent fulfillment location assignment with inventory validation
- **Out-of-Stock Tracking**: Comprehensive OOS incident reporting and product analysis
- **User Authentication**: Secure JWT-based authentication with user isolation
- **Modern UI**: React-based frontend with responsive design and real-time updates
- **Production Ready**: Docker-based deployment with Nginx reverse proxy and Redis task queue

## Architecture

### Core Components

- **Backend**: FastAPI + SQLAlchemy + Celery for REST API and background processing
- **Frontend**: React + TypeScript + Tailwind CSS for modern user interface
- **Database**: SQLite with volume persistence for production data
- **Task Queue**: Redis + Celery for background order processing
- **Reverse Proxy**: Nginx with rate limiting and security headers
- **Containerization**: 6 Docker services for complete application stack

### Key Technologies

- **Backend**: Python 3.11, FastAPI, SQLAlchemy, Celery, Redis
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS
- **Infrastructure**: Docker, Nginx, SQLite, Redis
- **API Integration**: Shopify Admin API 2025-04 with GraphQL

### Method 1: Windows with Docker

#### Prerequisites

1. **Install Docker Desktop for Windows**
   - Download from: https://docs.docker.com/desktop/install/windows-install/
   - Ensure WSL 2 backend is enabled
   - Verify installation: `docker --version` and `docker-compose --version`

2. **Install Git for Windows**
   - Download from: https://git-scm.com/download/win
   - Use Git Bash for command line operations

#### Setup Steps

1. **Clone the Repository**
   ```bash
   git clone <your-repository-url>
   cd "Shopify Automation"
   ```

2. **Configure Environment Variables**
   
   **Note**: This application does not use .env files. Environment variables are set directly in docker-compose.yml.
   
   Edit the docker-compose.yml file to configure your production settings:
   ```bash
   notepad docker-compose.yml
   ```

   **Required Environment Variables in docker-compose.yml:**
   ```yaml
   # Update these sections in docker-compose.yml:
   services:
     api:
       environment:
         - DATABASE_URL=sqlite:///app/data/app.db
         - REDIS_URL=redis://redis:6379/0
         - SECRET_KEY=your-super-secure-secret-key-change-this
         - JWT_SECRET_KEY=another-secure-jwt-secret-key
         - ENVIRONMENT=production
         - SHOPIFY_WEBHOOK_SECRET=your-webhook-secret
     
     worker:
       environment:
         # Same variables as api service
     
     scheduler:
       environment:
         # Same variables as api service
     
     frontend:
       environment:
         - VITE_API_URL=http://localhost
   ```

3. **Build and Start Services**
   ```bash
   # Build all services
   docker-compose build
   
   # Start all services in detached mode
   docker-compose up -d
   
   # Verify all services are running
   docker-compose ps
   ```

4. **Initialize Database**
   ```bash
   # Create database tables
   docker exec shopify_api python -c "from database import Base, engine; Base.metadata.create_all(bind=engine); print('Database initialized')"
   ```

5. **Access the Application**
   - Frontend: http://localhost
   - API Documentation: http://localhost/api/docs
   - Health Check: http://localhost/health

#### Windows-Specific Notes

- Use PowerShell or Git Bash for commands
- Ensure Docker Desktop is running before starting services
- Windows Defender may require exceptions for Docker ports
- Use `docker-compose logs -f` to monitor application logs

### Method 2: Linux with Docker

#### Prerequisites

1. **Install Docker and Docker Compose**
   ```bash
   # Ubuntu/Debian
   sudo apt update
   sudo apt install -y docker.io docker-compose
   
   # CentOS/RHEL
   sudo yum install -y docker docker-compose
   
   # Enable and start Docker service
   sudo systemctl enable docker
   sudo systemctl start docker
   
   # Add user to docker group (logout/login required)
   sudo usermod -aG docker $USER
   ```

2. **Verify Installation**
   ```bash
   docker --version
   docker-compose --version
   ```

#### Setup Steps

1. **Clone and Configure**
   ```bash
   git clone <your-repository-url>
   cd "Shopify Automation"
   
   # Configure environment variables in docker-compose.yml
   nano docker-compose.yml  # Edit with your production settings
   ```

2. **Set Proper Permissions**
   ```bash
   # Ensure proper ownership
   sudo chown -R $USER:$USER .
   
   # Set execute permissions
   chmod +x scripts/*.sh  # if you have any shell scripts
   ```

3. **Production Configuration**
   ```bash
   # Create production override file
   cat > docker-compose.prod.yml << EOF
   version: '3.8'
   services:
     api:
       environment:
         - ENVIRONMENT=production
       command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
     
     frontend:
       build:
         context: ./frontend
         dockerfile: Dockerfile.prod
         args:
           - VITE_API_URL=https://yourdomain.com
   EOF
   ```

4. **SSL Certificate Setup (Production)**
   ```bash
   # Create SSL directory
   mkdir -p nginx/ssl
   
   # For Let's Encrypt (recommended)
   sudo apt install certbot
   sudo certbot certonly --standalone -d yourdomain.com
   
   # Copy certificates
   sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem nginx/ssl/cert.pem
   sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem nginx/ssl/key.pem
   sudo chown $USER:$USER nginx/ssl/*.pem
   ```

5. **Start Production Services**
   ```bash
   # Build and start with production overrides
   docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
   
   # Initialize database
   docker exec shopify_api python -c "from database import Base, engine; Base.metadata.create_all(bind=engine)"
   
   # Verify services
   docker-compose ps
   ```

6. **Configure Firewall**
   ```bash
   # Ubuntu/Debian
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   
   # CentOS/RHEL
   sudo firewall-cmd --permanent --add-port=80/tcp
   sudo firewall-cmd --permanent --add-port=443/tcp
   sudo firewall-cmd --reload
   ```

#### Linux Docker Monitoring

```bash
# Monitor logs
docker-compose logs -f

# Check resource usage
docker stats

# Backup database
docker exec shopify_api cp /app/data/app.db /app/logs/backup-$(date +%Y%m%d).db

# Update application
git pull
docker-compose down
docker-compose up -d --build
```

### Method 3: Linux Native (No Docker)

#### Prerequisites

1. **System Requirements**
   ```bash
   # Ubuntu/Debian
   sudo apt update
   sudo apt install -y python3.11 python3.11-venv python3-pip nodejs npm redis-server nginx git
   
   # CentOS/RHEL
   sudo yum install -y python3.11 python3-pip nodejs npm redis nginx git
   sudo yum groupinstall -y "Development Tools"
   ```

2. **Install Node.js 18+ (if not available)**
   ```bash
   # Using NodeSource repository
   curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
   sudo apt-get install -y nodejs
   ```

#### Setup Steps

1. **Clone Repository**
   ```bash
   git clone <your-repository-url>
   cd "Shopify Automation"
   ```

2. **Backend Setup**
   ```bash
   # Create Python virtual environment
   python3.11 -m venv venv
   source venv/bin/activate
   
   # Install backend dependencies
   cd backend
   pip install --upgrade pip
   pip install -r requirements.txt
   cd ..
   ```

3. **Frontend Setup**
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```

4. **Database Setup**
   ```bash
   # Create data directory
   mkdir -p data logs
   
   # Initialize database
   cd backend
   source ../venv/bin/activate
   python -c "from database import Base, engine; Base.metadata.create_all(bind=engine); print('Database created')"
   cd ..
   ```

5. **Redis Configuration**
   ```bash
   # Configure Redis
   sudo nano /etc/redis/redis.conf
   # Ensure these settings:
   # bind 127.0.0.1
   # port 6379
   # daemonize yes
   
   # Start Redis
   sudo systemctl enable redis-server
   sudo systemctl start redis-server
   ```

6. **Environment Configuration**
   ```bash
   # Set environment variables for the current session
   export DATABASE_URL="sqlite:///$(pwd)/data/app.db"
   export REDIS_URL="redis://localhost:6379/0"
   export SECRET_KEY="$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")"
   export JWT_SECRET_KEY="$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")"
   export JWT_ALGORITHM="HS256"
   export ACCESS_TOKEN_EXPIRE_MINUTES="30"
   export ENVIRONMENT="production"
   export SHOPIFY_WEBHOOK_SECRET="your-webhook-secret"
   
   # For permanent configuration, add these to your shell profile:
   echo 'export DATABASE_URL="sqlite:///$(pwd)/data/app.db"' >> ~/.bashrc
   echo 'export REDIS_URL="redis://localhost:6379/0"' >> ~/.bashrc
   echo 'export SECRET_KEY="your-generated-secret-key"' >> ~/.bashrc
   echo 'export JWT_SECRET_KEY="your-generated-jwt-secret"' >> ~/.bashrc
   echo 'export ENVIRONMENT="production"' >> ~/.bashrc
   source ~/.bashrc
   ```

7. **Nginx Configuration**
   ```bash
   # Create Nginx site configuration
   sudo nano /etc/nginx/sites-available/shopify-automation
   ```

   **Nginx Configuration Content:**
   ```nginx
   server {
       listen 80;
       server_name yourdomain.com;

       # API routes
       location /api/ {
           rewrite ^/api/(.*) /$1 break;
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection 'upgrade';
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_cache_bypass $http_upgrade;

           # Rate limiting
           limit_req zone=api burst=20 nodelay;
       }

       # Frontend routes
       location / {
           root /path/to/Shopify Automation/frontend/dist;
           try_files $uri $uri/ /index.html;
           
           # Cache static assets
           location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
               expires 1y;
               add_header Cache-Control "public, immutable";
           }
       }

       # Security headers
       add_header X-Frame-Options "SAMEORIGIN" always;
       add_header X-XSS-Protection "1; mode=block" always;
       add_header X-Content-Type-Options "nosniff" always;
       add_header Referrer-Policy "no-referrer-when-downgrade" always;
   }
   ```

   ```bash
   # Enable site and restart Nginx
   sudo ln -s /etc/nginx/sites-available/shopify-automation /etc/nginx/sites-enabled/
   sudo nginx -t
   sudo systemctl restart nginx
   ```

8. **Create Systemd Services**

   **API Service:**
   ```bash
   sudo nano /etc/systemd/system/shopify-api.service
   ```

   ```ini
   [Unit]
   Description=Shopify Automation API
   After=network.target redis.service

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/path/to/Shopify Automation/backend
   Environment=PATH=/path/to/Shopify Automation/venv/bin
   Environment=DATABASE_URL=sqlite:////path/to/Shopify Automation/data/app.db
   Environment=REDIS_URL=redis://localhost:6379/0
   Environment=SECRET_KEY=your-generated-secret-key
   Environment=JWT_SECRET_KEY=your-generated-jwt-secret
   Environment=ENVIRONMENT=production
   ExecStart=/path/to/Shopify Automation/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   ```

   **Celery Worker Service:**
   ```bash
   sudo nano /etc/systemd/system/shopify-worker.service
   ```

   ```ini
   [Unit]
   Description=Shopify Automation Celery Worker
   After=network.target redis.service

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/path/to/Shopify Automation/backend
   Environment=PATH=/path/to/Shopify Automation/venv/bin
   Environment=DATABASE_URL=sqlite:////path/to/Shopify Automation/data/app.db
   Environment=REDIS_URL=redis://localhost:6379/0
   Environment=SECRET_KEY=your-generated-secret-key
   Environment=JWT_SECRET_KEY=your-generated-jwt-secret
   Environment=ENVIRONMENT=production
   ExecStart=/path/to/Shopify Automation/venv/bin/celery -A tasks.celery worker --loglevel=info --concurrency=4
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   ```

   **Celery Beat Service:**
   ```bash
   sudo nano /etc/systemd/system/shopify-scheduler.service
   ```

   ```ini
   [Unit]
   Description=Shopify Automation Celery Scheduler
   After=network.target redis.service

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/path/to/Shopify Automation/backend
   Environment=PATH=/path/to/Shopify Automation/venv/bin
   Environment=DATABASE_URL=sqlite:////path/to/Shopify Automation/data/app.db
   Environment=REDIS_URL=redis://localhost:6379/0
   Environment=SECRET_KEY=your-generated-secret-key
   Environment=JWT_SECRET_KEY=your-generated-jwt-secret
   Environment=ENVIRONMENT=production
   ExecStart=/path/to/Shopify Automation/venv/bin/celery -A tasks.celery beat --loglevel=info
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   ```

9. **Start Services**
   ```bash
   # Set proper permissions
   sudo chown -R www-data:www-data /path/to/Shopify Automation
   
   # Enable and start services
   sudo systemctl daemon-reload
   sudo systemctl enable shopify-api shopify-worker shopify-scheduler
   sudo systemctl start shopify-api shopify-worker shopify-scheduler
   
   # Check service status
   sudo systemctl status shopify-api shopify-worker shopify-scheduler
   ```

#### Native Linux Management

```bash
# View logs
sudo journalctl -u shopify-api -f
sudo journalctl -u shopify-worker -f
sudo journalctl -u shopify-scheduler -f

# Restart services
sudo systemctl restart shopify-api shopify-worker shopify-scheduler

# Update application
cd /path/to/Shopify Automation
git pull
source venv/bin/activate
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && npm run build && cd ..
sudo systemctl restart shopify-api shopify-worker shopify-scheduler
```

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABASE_URL` | SQLite database path | Yes | `sqlite:///app/data/app.db` |
| `REDIS_URL` | Redis connection URL | Yes | `redis://redis:6379/0` |
| `SECRET_KEY` | Application secret key | Yes | - |
| `JWT_SECRET_KEY` | JWT signing key | Yes | - |
| `JWT_ALGORITHM` | JWT algorithm | No | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token expiration | No | `30` |
| `ENVIRONMENT` | Environment mode | No | `development` |
| `SHOPIFY_WEBHOOK_SECRET` | Webhook verification | No | - |
| `VITE_API_URL` | Frontend API URL | Yes | `http://localhost:8000` |

### Database Migrations

The application automatically creates database tables on startup. For manual database operations:

```bash
# Docker environment
docker exec shopify_api python -c "from database import Base, engine; Base.metadata.create_all(bind=engine)"

# Native environment (ensure environment variables are set first)
cd backend
source ../venv/bin/activate
python -c "from database import Base, engine; Base.metadata.create_all(bind=engine)"
```

### Environment Variable Configuration

**Important**: This application does not use .env files. Environment variables are configured as follows:

- **Docker Deployment**: Set directly in `docker-compose.yml`
- **Native Deployment**: Set as system environment variables or in systemd service files
- **Development**: Can be exported in your shell session

## Shopify Integration

### Admin API Access Token

To connect a Shopify store:

1. Go to your Shopify admin panel
2. Navigate to Apps > App and sales channel settings
3. Click "Develop apps for your store"
4. Create a new app
5. Configure Admin API access scopes:
   - `read_orders`
   - `write_orders` 
   - `read_locations`
   - `read_fulfillments`
   - `write_fulfillments`
6. Install the app and copy the Admin API access token

### Required Permissions

The system needs these Shopify permissions:
- **Orders**: Read and write access for tagging and processing
- **Locations**: Read access for fulfillment location management
- **Fulfillments**: Read and write access for location assignments

## Monitoring and Maintenance

### Health Checks

- Application health: `http://yourdomain.com/health`
- API documentation: `http://yourdomain.com/api/docs`
- Redis: `redis-cli ping`

### Log Locations

**Docker Environment:**
- Application logs: `docker-compose logs -f`
- Nginx logs: Inside nginx container at `/var/log/nginx/`

**Native Environment:**
- API logs: `journalctl -u shopify-api`
- Worker logs: `journalctl -u shopify-worker`
- Scheduler logs: `journalctl -u shopify-scheduler`
- Nginx logs: `/var/log/nginx/access.log` and `/var/log/nginx/error.log`

### Backup and Recovery

```bash
# Database backup (Docker)
docker exec shopify_api cp /app/data/app.db /app/logs/backup-$(date +%Y%m%d_%H%M%S).db

# Database backup (Native)
cp data/app.db backups/backup-$(date +%Y%m%d_%H%M%S).db

# Redis backup
redis-cli BGSAVE
```

### Performance Tuning

1. **Database Optimization**
   - Regular VACUUM operations for SQLite
   - Monitor database file size growth

2. **Redis Configuration**
   - Set appropriate memory limits
   - Configure persistence settings

3. **Nginx Optimization**
   - Enable gzip compression
   - Configure appropriate buffer sizes
   - Set up proper caching headers

4. **Application Scaling**
   - Increase Celery worker concurrency
   - Add multiple API workers
   - Implement database connection pooling

## Security Considerations

### Production Security Checklist

- [ ] Change all default passwords and secrets
- [ ] Enable HTTPS with valid SSL certificates
- [ ] Configure proper firewall rules
- [ ] Set up rate limiting in Nginx
- [ ] Enable security headers
- [ ] Regular security updates
- [ ] Monitor logs for suspicious activity
- [ ] Implement backup and disaster recovery
- [ ] Use environment variables for sensitive data
- [ ] Regular dependency updates

### Shopify Integration Security

- [ ] Secure webhook endpoints
- [ ] Validate Shopify webhook signatures
- [ ] Use HTTPS for all Shopify communications
- [ ] Regularly rotate API keys
- [ ] Implement proper error handling to avoid data leaks

## Troubleshooting

### Common Issues

1. **Services Won't Start**
   - Check Docker daemon status
   - Verify port availability
   - Review environment variables
   - Check file permissions

2. **Database Connection Errors**
   - Verify database file permissions
   - Check SQLite file corruption
   - Ensure data directory exists

3. **Redis Connection Issues**
   - Verify Redis service status
   - Check Redis configuration
   - Confirm network connectivity

4. **Frontend Build Errors**
   - Clear npm cache: `npm cache clean --force`
   - Delete node_modules and reinstall
   - Check Node.js version compatibility

5. **API Authentication Issues**
   - Verify JWT secret keys
   - Check token expiration settings
   - Review CORS configuration

### Performance Issues

1. **Slow Order Processing**
   - Increase Celery worker concurrency
   - Optimize database queries
   - Check Redis memory usage

2. **High Memory Usage**
   - Monitor Docker container resources
   - Optimize database queries
   - Implement proper pagination

3. **Network Timeouts**
   - Increase Nginx timeout settings
   - Optimize Shopify API calls
   - Implement proper retry logic

## Support and Documentation

### Development Commands

For development and testing, refer to the `CLAUDE.md` file in the project root for detailed development workflows, testing procedures, and debugging commands.

### API Documentation

Once the application is running, access the interactive API documentation at:
- Swagger UI: `http://yourdomain.com/api/docs`
- ReDoc: `http://yourdomain.com/api/redoc`

### Contributing

This is a private project. For development setup and contribution guidelines, consult the project maintainer.

## License

Private proprietary software. All rights reserved.

---

**Note**: Replace `<your-repository-url>`, `yourdomain.com`, and file paths with your actual values before deployment.