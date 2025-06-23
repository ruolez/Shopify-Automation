# Shopify Multi-Store Order Management System

A comprehensive automated order processing and tagging system for multiple Shopify stores with modern UI and background processing capabilities.

## Features

- **Multi-Store Support**: Connect and manage multiple Shopify stores
- **Automated Processing**: Background workers process orders continuously
- **Rule Engine**: Create complex rules with visual wizard
- **Real-time Dashboard**: Monitor system status and recent activity
- **Modern UI**: Responsive design with Tailwind CSS and Framer Motion
- **Secure Authentication**: JWT-based user authentication
- **Docker Ready**: Full containerization for easy deployment

## Tech Stack

### Backend
- **FastAPI**: Modern Python web framework
- **SQLite**: Lightweight database
- **Celery**: Distributed task queue
- **Redis**: Message broker
- **SQLAlchemy**: ORM for database operations

### Frontend
- **React 18**: Modern React with hooks
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Utility-first CSS framework
- **Framer Motion**: Smooth animations
- **React Query**: Data fetching and caching
- **React Hook Form**: Form management

### Infrastructure
- **Docker**: Containerization
- **Nginx**: Reverse proxy and load balancing
- **Redis**: Caching and task queue

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Git

### Installation

1. **Clone the repository**
```bash
git clone <repository-url>
cd shopify-automation
```

2. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. **Start the application**
```bash
docker-compose up -d
```

4. **Access the application**
- Frontend: http://localhost:3000
- API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

### First Time Setup

1. **Create an account** at http://localhost:3000/register
2. **Connect your Shopify store**:
   - Go to your Shopify admin
   - Create a private app with Admin API access
   - Copy the access token
   - Add store in the application
3. **Create automation rules**:
   - Use the rule builder to create conditions
   - Set actions (tags, fulfillment locations)
   - Activate rules

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

## Rule Engine

### Available Conditions

- **Order Total**: Monetary value comparisons
- **Order Weight**: Weight-based filtering
- **Shipping Location**: Province, country, city matching
- **Shipping Method**: Delivery method filtering
- **Customer Data**: Email, customer type filtering
- **Product Data**: SKU, type, vendor filtering
- **Order Tags**: Existing tag conditions
- **Dates**: Order creation time filtering

### Available Actions

- **Add Tags**: Automatically tag orders
- **Remove Tags**: Remove specific tags
- **Set Fulfillment Location**: Assign orders to specific warehouses

### Rule Priority

Rules are processed by priority (higher numbers first). This allows you to:
- Create general rules with low priority
- Override with specific high-priority rules
- Handle edge cases with maximum priority

## Background Processing

The system runs continuous background tasks:

- **Order Sync**: Every 10 minutes, fetch new orders from all stores
- **Rule Processing**: Apply active rules to new orders
- **Error Handling**: Retry failed operations with exponential backoff
- **Cleanup**: Remove old logs and task records

### Monitoring

- View processing status in the dashboard
- Check recent activity for order processing results
- Monitor store connection health
- Track rule execution success/failure rates

## Development

### Backend Development

```bash
# Start only backend services
docker-compose up redis api worker scheduler

# Run backend locally
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend Development

```bash
# Start backend services
docker-compose up redis api worker scheduler

# Run frontend locally
cd frontend
npm install
npm run dev
```

### Testing

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

## Deployment

### Production Configuration

1. **Update environment variables**:
```bash
SECRET_KEY=<strong-production-secret>
ENVIRONMENT=production
DATABASE_URL=<production-database-url>
```

2. **Configure SSL** (update nginx/nginx.conf):
```nginx
server {
    listen 443 ssl http2;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    # ... rest of configuration
}
```

3. **Scale workers**:
```bash
docker-compose up --scale worker=3
```

### Health Checks

- **API Health**: GET /health
- **Database**: Connection test via API
- **Redis**: Task queue connectivity
- **Shopify Stores**: Connection validation

## API Documentation

Interactive API documentation is available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Key Endpoints

- **Authentication**: `/auth/login`, `/auth/register`
- **Stores**: `/stores` (CRUD operations)
- **Rules**: `/rules` (CRUD operations)
- **Dashboard**: `/dashboard/stats`

## Troubleshooting

### Common Issues

1. **Store Connection Failed**
   - Verify access token is correct
   - Check API permissions are granted
   - Ensure store domain format is correct

2. **Rules Not Processing**
   - Check if rules are active
   - Verify background workers are running
   - Review recent activity for error messages

3. **Performance Issues**
   - Scale worker containers
   - Increase Redis memory allocation
   - Optimize rule conditions

### Logs

```bash
# View application logs
docker-compose logs -f api

# View worker logs
docker-compose logs -f worker

# View all logs
docker-compose logs -f
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support and questions:
- Create an issue in the repository
- Check the troubleshooting section
- Review the API documentation