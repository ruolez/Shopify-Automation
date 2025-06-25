#!/bin/bash

# Quick API connectivity fix script
# Run this on your server to immediately fix the API connection issue

set -e

echo "🔧 Fixing API connectivity..."

# Get server IP
SERVER_IP="192.168.1.112"

echo "📝 Creating frontend .env file with server IP: $SERVER_IP"
cat > frontend/.env << EOF
VITE_API_URL=http://$SERVER_IP:8000
EOF

echo "🌐 Updating CORS configuration in backend..."
sed -i "s|allow_origins=\[.*\]|allow_origins=[\"http://$SERVER_IP:3000\", \"http://$SERVER_IP\", \"http://localhost:3000\", \"http://localhost\"]|" backend/main.py

echo "🔄 Restarting services..."
docker-compose down
docker-compose up -d

echo "⏳ Waiting for services to start..."
sleep 15

echo "🏥 Testing API connectivity..."
if curl -s -o /dev/null -w "%{http_code}" http://$SERVER_IP:8000/health | grep -q "200"; then
    echo "✅ API is now accessible at http://$SERVER_IP:8000"
    echo "✅ Frontend should now work at http://$SERVER_IP"
else
    echo "❌ API still not accessible, checking logs..."
    docker-compose logs api --tail=10
fi

echo ""
echo "🎉 API fix completed!"
echo "🌐 Access your app at: http://$SERVER_IP"