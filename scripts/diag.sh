#!/usr/bin/env bash
# Read-only production diagnostics. Run on the server from the app directory:  bash scripts/diag.sh
PG=shopify_postgres_prod; WK=shopify_worker_prod; RD=shopify_redis_prod
q() { docker exec "$PG" psql -U shopify_user -d shopify_db -Atc "$1"; }
qq() { docker exec "$PG" psql -U shopify_user -d shopify_db -c "$1"; }

echo "== code: $(git rev-parse --short HEAD)   server UTC now: $(date -u '+%F %T')"
echo; echo "== stores"
qq "SELECT id, shop_name, is_active, needs_reauth, last_sync FROM shopify_stores ORDER BY id;"
echo; echo "== settings"
qq "SELECT user_id, auto_sync_enabled, sync_frequency_minutes, sync_window_days, timezone FROM settings;"
echo; echo "== order_logs: distinct orders per ORDER-CREATED day (UTC) — this is what the dashboard shows"
qq "SELECT (created_at AT TIME ZONE 'UTC')::date AS order_day, count(DISTINCT order_id) AS orders, count(*) AS rows
    FROM order_logs WHERE created_at > now() - interval '8 days' GROUP BY 1 ORDER BY 1;"
echo; echo "== processed_orders: orders actually PROCESSED per hour, last 48h — shows when the sync was alive"
qq "SELECT date_trunc('hour', processed_at AT TIME ZONE 'UTC') AS hour_utc, count(*) FROM processed_orders
    WHERE processed_at > now() - interval '48 hours' GROUP BY 1 ORDER BY 1;"
echo; echo "== last 15 order_logs written (by id = insertion order)"
qq "SELECT id, order_number, action, status, created_at FROM order_logs ORDER BY id DESC LIMIT 15;"
echo; echo "== task_status last 24h (failures first)"
qq "SELECT task_name, status, left(error_message,110) AS err, created_at FROM task_status
    WHERE created_at > now() - interval '24 hours' ORDER BY (status='failed') DESC, created_at DESC LIMIT 25;"
echo; echo "== redis store locks (TTL seconds; -2 = none)"
for k in $(docker exec "$RD" redis-cli keys 'store_*_lock:*'); do echo "$k ttl=$(docker exec "$RD" redis-cli ttl "$k")"; done
echo; echo "== worker log: errors/warnings last 3h"
docker logs --since 3h "$WK" 2>&1 | grep -iE "error|warning|throttl|exceeded|skipping this run" | tail -40
