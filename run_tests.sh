#!/bin/bash

# Shopify Order Management System - Test Runner
# This script runs comprehensive tests for both backend and frontend

set -e

echo "🧪 Starting Shopify Order Management System Tests..."
echo "=================================================="

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

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check if containers are running
print_status "Checking Docker containers status..."
if ! docker-compose ps | grep -q "Up"; then
    print_warning "Containers are not running. Starting them..."
    docker-compose up -d
    print_status "Waiting for containers to be ready..."
    sleep 10
fi

# Backend Tests
echo ""
echo "🔧 Running Backend Tests"
echo "========================"

print_status "Setting up backend test environment..."

# Create test database and run migrations if needed
docker-compose exec -T api python -c "
from database import engine, Base
from sqlalchemy import create_engine
import os

# Create test database
test_engine = create_engine('sqlite:///./test.db', connect_args={'check_same_thread': False})
Base.metadata.create_all(bind=test_engine)
print('Test database created')
"

# Run backend tests
print_status "Running backend unit tests..."
if docker-compose exec -T api python -m pytest tests/ -v --tb=short; then
    print_success "Backend tests passed!"
    BACKEND_TESTS_PASSED=true
else
    print_error "Backend tests failed!"
    BACKEND_TESTS_PASSED=false
fi

# Frontend Tests
echo ""
echo "🎨 Running Frontend Tests"
echo "========================="

print_status "Installing frontend test dependencies..."
cd frontend

# Install dependencies if node_modules doesn't exist or package.json changed
if [ ! -d "node_modules" ] || [ package.json -nt node_modules ]; then
    print_status "Installing dependencies..."
    npm install
fi

# Run frontend tests
print_status "Running frontend unit tests..."
if npm run test -- --run; then
    print_success "Frontend tests passed!"
    FRONTEND_TESTS_PASSED=true
else
    print_error "Frontend tests failed!"
    FRONTEND_TESTS_PASSED=false
fi

# Generate test coverage report
print_status "Generating test coverage report..."
npm run test:coverage -- --run --reporter=verbose > /dev/null 2>&1 || true

cd ..

# Integration Tests
echo ""
echo "🔄 Running Integration Tests"
echo "============================"

print_status "Testing API endpoints..."

# Test health endpoint
if curl -f -s http://localhost:8000/health > /dev/null; then
    print_success "API health check passed"
    API_HEALTH=true
else
    print_error "API health check failed"
    API_HEALTH=false
fi

# Test frontend is accessible
if curl -f -s http://localhost:3000 > /dev/null; then
    print_success "Frontend accessibility check passed"
    FRONTEND_HEALTH=true
else
    print_error "Frontend accessibility check failed"
    FRONTEND_HEALTH=false
fi

# Test database connection
print_status "Testing database connection..."
if docker-compose exec -T api python -c "
from database import SessionLocal
from sqlalchemy import text
try:
    db = SessionLocal()
    db.execute(text('SELECT 1'))
    db.close()
    print('Database connection successful')
except Exception as e:
    print(f'Database connection failed: {e}')
    exit(1)
"; then
    print_success "Database connection test passed"
    DB_CONNECTION=true
else
    print_error "Database connection test failed"
    DB_CONNECTION=false
fi

# Test Redis connection
print_status "Testing Redis connection..."
if docker-compose exec -T redis redis-cli ping | grep -q "PONG"; then
    print_success "Redis connection test passed"
    REDIS_CONNECTION=true
else
    print_error "Redis connection test failed"
    REDIS_CONNECTION=false
fi

# Test Celery worker
print_status "Testing Celery worker..."
if docker-compose exec -T worker celery -A tasks.celery inspect ping | grep -q "pong"; then
    print_success "Celery worker test passed"
    CELERY_WORKER=true
else
    print_error "Celery worker test failed"
    CELERY_WORKER=false
fi

# Summary
echo ""
echo "📊 Test Results Summary"
echo "======================="

if [ "$BACKEND_TESTS_PASSED" = true ]; then
    print_success "✅ Backend Tests: PASSED"
else
    print_error "❌ Backend Tests: FAILED"
fi

if [ "$FRONTEND_TESTS_PASSED" = true ]; then
    print_success "✅ Frontend Tests: PASSED"
else
    print_error "❌ Frontend Tests: FAILED"
fi

if [ "$API_HEALTH" = true ]; then
    print_success "✅ API Health: PASSED"
else
    print_error "❌ API Health: FAILED"
fi

if [ "$FRONTEND_HEALTH" = true ]; then
    print_success "✅ Frontend Health: PASSED"
else
    print_error "❌ Frontend Health: FAILED"
fi

if [ "$DB_CONNECTION" = true ]; then
    print_success "✅ Database Connection: PASSED"
else
    print_error "❌ Database Connection: FAILED"
fi

if [ "$REDIS_CONNECTION" = true ]; then
    print_success "✅ Redis Connection: PASSED"
else
    print_error "❌ Redis Connection: FAILED"
fi

if [ "$CELERY_WORKER" = true ]; then
    print_success "✅ Celery Worker: PASSED"
else
    print_error "❌ Celery Worker: FAILED"
fi

# Overall result
if [ "$BACKEND_TESTS_PASSED" = true ] && [ "$FRONTEND_TESTS_PASSED" = true ] && 
   [ "$API_HEALTH" = true ] && [ "$FRONTEND_HEALTH" = true ] && 
   [ "$DB_CONNECTION" = true ] && [ "$REDIS_CONNECTION" = true ] && 
   [ "$CELERY_WORKER" = true ]; then
    echo ""
    print_success "🎉 ALL TESTS PASSED! The application is ready for production."
    echo ""
    echo "📋 Next Steps:"
    echo "  • Access the application at: http://localhost:3000"
    echo "  • API documentation at: http://localhost:8000/docs"
    echo "  • Monitor logs with: docker-compose logs -f"
    echo ""
    exit 0
else
    echo ""
    print_error "💥 SOME TESTS FAILED! Please review the errors above."
    echo ""
    echo "🔍 Troubleshooting:"
    echo "  • Check container logs: docker-compose logs [service-name]"
    echo "  • Restart services: docker-compose restart"
    echo "  • Rebuild containers: docker-compose up --build"
    echo ""
    exit 1
fi