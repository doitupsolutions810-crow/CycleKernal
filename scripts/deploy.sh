#!/bin/bash

# CycleKernel Deployment Script
# This script handles the complete deployment of the CycleKernel-Integrated platform

set -e  # Exit on error

echo "🚀 CycleKernel Deployment Script"
echo "================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ️  $1${NC}"
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi
print_success "Docker is installed"

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi
print_success "Docker Compose is installed"

# Stop existing containers
print_info "Stopping existing containers..."
docker-compose down || true
print_success "Existing containers stopped"

# Remove old images (optional)
read -p "Do you want to remove old images? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    print_info "Removing old images..."
    docker-compose down --rmi all || true
    print_success "Old images removed"
fi

# Build images
print_info "Building Docker images..."
docker-compose build --no-cache
print_success "Docker images built"

# Start services
print_info "Starting services..."
docker-compose up -d
print_success "Services started"

# Wait for services to be healthy
print_info "Waiting for services to be healthy..."
sleep 10

# Check service health
print_info "Checking service health..."

services=("simulation:5000" "monitoring:3000" "mongodb:27017" "redis:6379" "prometheus:9090" "grafana:3001")
for service in "${services[@]}"; do
    IFS=':' read -r name port <<< "$service"
    if docker-compose ps | grep -q "$name"; then
        print_success "$name is running"
    else
        print_error "$name is not running"
    fi
done

# Display access URLs
echo ""
echo "================================="
echo "🎉 Deployment Complete!"
echo "================================="
echo ""
echo "Access the services at:"
echo "  📊 Frontend Dashboard: http://localhost:8080"
echo "  🔬 Simulation API:     http://localhost:5000"
echo "  📡 Monitoring API:     http://localhost:3000"
echo "  📈 Grafana:            http://localhost:3001 (admin/admin)"
echo "  🔍 Prometheus:         http://localhost:9090"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To stop services:"
echo "  docker-compose down"
echo ""
print_success "Happy monitoring! 🚀"
