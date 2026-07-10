#!/bin/bash

echo "Monitoring reconcile operations..."
echo "Press Ctrl+C to stop"
echo ""

# Monitor API logs for reconcile endpoint calls
docker logs -f shopify_api 2>&1 | grep --line-buffered -E "fraud-detection/archive|reconcile|Archive|ERROR.*fraud|ERROR.*analysis"