#!/bin/bash

# Production deployment script
echo "Starting deployment..."

# Migrate database
flask db upgrade

# Collect static files (if any)
# ...

# Start services
docker-compose up -d

echo "Deployment completed!"