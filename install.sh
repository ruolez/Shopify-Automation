#!/bin/bash
#
# Shopify Automation — unified installer
#
#   ./install.sh            interactive menu: Install / Update / Backup / Remove
#
# Install : prompts for server address + Shopify OAuth keys, auto-generates all
#           secrets (no manual .env editing), builds and starts the stack.
# Update  : backs up settings (.env) and the PostgreSQL database, pulls the
#           latest code from GitHub, rebuilds, runs pending migrations, and
#           prunes unused Docker images.
# Backup  : settings + database backup only.
# Remove  : stops the stack; optionally deletes volumes (data) and images.
#
set -euo pipefail

REPO_URL="https://github.com/ruolez/Shopify-Automation.git"
COMPOSE_FILE="docker-compose.postgres.prod.yml"
PG_CONTAINER="shopify_postgres_prod"
API_CONTAINER="shopify_api_prod"
PG_USER="shopify_user"
PG_DB="shopify_db"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
info() { echo -e "${BLUE}▸${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
die()  { echo -e "${RED}✗${NC} $1"; exit 1; }

# ---------------------------------------------------------------- helpers ---

require_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker is not installed."
        read -rp "Install Docker now (Ubuntu/Debian, uses get.docker.com)? [y/N] " a
        if [[ "${a,,}" == "y" ]]; then
            curl -fsSL https://get.docker.com | sh
            ok "Docker installed"
        else
            die "Docker is required."
        fi
    fi
    docker compose version >/dev/null 2>&1 || die "Docker Compose v2 plugin is required (apt install docker-compose-plugin)."
    docker info >/dev/null 2>&1 || die "Cannot talk to the Docker daemon (run as root or add user to the docker group)."
}

# Generates a urlsafe secret; $1 = bytes
gen_secret() {
    openssl rand -base64 "${1:-32}" | tr '+/' '-_' | tr -d '\n'
}

# Fernet key: urlsafe base64 of exactly 32 bytes
gen_fernet_key() {
    python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())" 2>/dev/null \
        || openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n'
}

detect_ip() {
    ip route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}' \
        || hostname -I 2>/dev/null | awk '{print $1}' \
        || echo "127.0.0.1"
}

in_repo() { [ -f "$COMPOSE_FILE" ] && [ -d backend ]; }

env_get() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d'=' -f2- || true; }

# Appends KEY=VALUE to .env if the key is absent (used during updates when new
# code introduces new settings)
ensure_env_key() {
    local key="$1" value="$2" comment="${3:-}"
    if ! grep -q "^${key}=" .env; then
        [ -n "$comment" ] && printf '\n# %s\n' "$comment" >> .env
        printf '%s=%s\n' "$key" "$value" >> .env
        ok "Added missing $key to .env"
    fi
}

backup_now() {
    local backup_dir="backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$backup_dir"

    info "Backing up settings and database to $backup_dir ..."
    [ -f .env ] && cp .env "$backup_dir/.env.backup" && ok "Settings (.env) backed up"
    [ -f frontend/.env ] && cp frontend/.env "$backup_dir/frontend.env.backup"

    if docker ps --format '{{.Names}}' | grep -q "^${PG_CONTAINER}$"; then
        docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" | gzip > "$backup_dir/postgres_backup.sql.gz"
        ok "PostgreSQL database backed up ($(du -h "$backup_dir/postgres_backup.sql.gz" | cut -f1))"
    else
        warn "Postgres container not running — skipped database dump"
    fi

    # Keep the 10 most recent backups
    ls -1dt backups/*/ 2>/dev/null | tail -n +11 | xargs -r rm -rf
    LAST_BACKUP_DIR="$backup_dir"
}

wait_for_api() {
    info "Waiting for the API to become healthy..."
    for _ in $(seq 1 60); do
        if docker exec "$API_CONTAINER" python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/health', timeout=10)" >/dev/null 2>&1; then
            ok "API is up"
            return 0
        fi
        sleep 2
    done
    warn "API did not report healthy within 2 minutes — check: docker logs $API_CONTAINER"
    return 1
}

run_migrations() {
    # A database freshly created by create_tables() already has the full schema;
    # its schema_migrations table is empty, and replaying old migrations would
    # fail (some predate PostgreSQL). Mark them applied instead.
    local applied
    applied=$(docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -tAc \
        "SELECT COALESCE((SELECT count(*) FROM schema_migrations), 0)" 2>/dev/null || echo "0")
    applied="${applied//[^0-9]/}"
    if [ "${applied:-0}" -eq 0 ] 2>/dev/null || [ -z "$applied" ]; then
        info "Fresh database detected — marking all migrations as applied"
        docker exec "$API_CONTAINER" python run_all_migrations.py --mark-all
    else
        info "Running pending database migrations..."
        docker exec "$API_CONTAINER" python run_all_migrations.py
    fi
    ok "Database schema is up to date"
}

docker_cleanup() {
    info "Cleaning up unused Docker images and build cache..."
    local before after
    before=$(docker system df --format '{{.Size}}' 2>/dev/null | head -1 || true)
    docker image prune -f >/dev/null
    docker builder prune -f >/dev/null 2>&1 || true
    after=$(docker system df --format '{{.Size}}' 2>/dev/null | head -1 || true)
    ok "Docker cleanup complete (images: ${before:-?} → ${after:-?})"
}

# ---------------------------------------------------------------- install ---

do_install() {
    require_docker

    if ! in_repo; then
        read -rp "Install directory [/opt/shopify-automation]: " dir
        dir="${dir:-/opt/shopify-automation}"
        if [ -d "$dir/.git" ]; then
            info "Existing checkout found at $dir"
        else
            info "Cloning $REPO_URL ..."
            git clone "$REPO_URL" "$dir"
        fi
        cd "$dir"
        in_repo || die "Repository at $dir does not contain $COMPOSE_FILE"
    fi

    echo ""
    echo "── Server configuration ─────────────────────────────────────────"
    local detected_ip; detected_ip=$(detect_ip)
    read -rp "Server address (domain or IP) [$detected_ip]: " server_host
    server_host="${server_host:-$detected_ip}"
    local app_url="http://$server_host"

    echo ""
    echo "── Shopify OAuth (optional) ─────────────────────────────────────"
    echo "   Needed for 'Connect with Shopify' store connections and webhooks."
    echo "   Manual admin-token connections work without these. Get them from"
    echo "   the Shopify Dev Dashboard; set the app redirect URI to:"
    echo "   $app_url/api/shopify/oauth/callback"
    read -rp "Shopify API key (client id) [skip]: " shopify_key
    local shopify_secret=""
    if [ -n "$shopify_key" ]; then
        read -rsp "Shopify API secret (client secret): " shopify_secret; echo ""
        [ -n "$shopify_secret" ] || die "API secret is required when an API key is given."
    fi

    echo ""
    echo "── Admin account ────────────────────────────────────────────────"
    read -rsp "Initial admin password [auto-generate]: " admin_password; echo ""
    local admin_pw_generated=false
    if [ -z "$admin_password" ]; then
        admin_password=$(gen_secret 12)
        admin_pw_generated=true
    fi

    # Secrets: generate fresh, but never silently rotate an existing
    # ENCRYPTION_KEY — stored Shopify tokens would become undecryptable.
    local secret_key admin_secret encryption_key postgres_password
    if [ -f .env ]; then
        warn "An existing .env was found."
        read -rp "Keep existing secrets and database password? [Y/n] " keep
        if [[ "${keep,,}" != "n" ]]; then
            secret_key=$(env_get SECRET_KEY)
            admin_secret=$(env_get ADMIN_SECRET_KEY)
            encryption_key=$(env_get ENCRYPTION_KEY)
            postgres_password=$(env_get POSTGRES_PASSWORD)
            cp .env ".env.pre-install.$(date +%s)" && ok "Existing .env preserved as a local copy"
        fi
    fi
    secret_key="${secret_key:-$(gen_secret 32)}"
    admin_secret="${admin_secret:-$(gen_secret 32)}"
    encryption_key="${encryption_key:-$(gen_fernet_key)}"
    postgres_password="${postgres_password:-$(gen_secret 24)}"

    info "Writing .env ..."
    cat > .env <<EOF
# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ) — do not commit.

# Server
SERVER_IP=$server_host
APP_URL=$app_url
FRONTEND_URL=$app_url
VITE_API_URL=/api
ENVIRONMENT=production

# Database (PostgreSQL)
DATABASE_URL=postgresql://$PG_USER:$postgres_password@postgres:5432/$PG_DB
POSTGRES_PASSWORD=$postgres_password
POSTGRES_DB=$PG_DB
POSTGRES_USER=$PG_USER
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600

# CORS
CORS_ORIGINS=http://$server_host,http://localhost

# Security (auto-generated)
SECRET_KEY=$secret_key
ADMIN_SECRET_KEY=$admin_secret
ENCRYPTION_KEY=$encryption_key
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
ADMIN_INITIAL_PASSWORD=$admin_password

# Shopify
SHOPIFY_API_VERSION=2026-04
SHOPIFY_API_KEY=$shopify_key
SHOPIFY_API_SECRET=$shopify_secret

# Redis
REDIS_URL=redis://redis:6379/0

# Application
LOG_LEVEL=INFO
EOF
    chmod 600 .env
    ok ".env written (permissions 600)"

    printf 'VITE_API_URL=/api\n' > frontend/.env
    ok "frontend/.env written (nginx proxy mode)"

    info "Building images (this can take several minutes)..."
    docker compose -f "$COMPOSE_FILE" build
    info "Starting the stack..."
    docker compose -f "$COMPOSE_FILE" up -d

    wait_for_api || true
    run_migrations
    docker exec "$API_CONTAINER" python init_admin.py || warn "init_admin failed — run manually: docker exec $API_CONTAINER python init_admin.py"

    echo ""
    echo "════════════════════════════════════════════════════════════════"
    ok "Installation complete"
    echo -e "   App:         ${BLUE}$app_url${NC}"
    echo -e "   Admin panel: ${BLUE}$app_url/admin/login${NC}  (user: admin)"
    if $admin_pw_generated; then
        echo -e "   Admin password (shown once, change after login): ${YELLOW}$admin_password${NC}"
    fi
    if [ -z "$shopify_key" ]; then
        echo -e "   ${YELLOW}Shopify OAuth not configured${NC} — stores can still be connected"
        echo    "   with manual admin tokens. Re-run install (keeping secrets) or add"
        echo    "   SHOPIFY_API_KEY/SHOPIFY_API_SECRET to .env later to enable OAuth."
    fi
    echo "════════════════════════════════════════════════════════════════"
}

# ----------------------------------------------------------------- update ---

do_update() {
    require_docker
    in_repo || die "Run this from the application directory (where $COMPOSE_FILE lives)."
    [ -f .env ] || die "No .env found — run Install first."

    backup_now

    info "Pulling latest code from GitHub..."
    git fetch origin
    local branch; branch=$(git rev-parse --abbrev-ref HEAD)
    if ! git pull --ff-only origin "$branch"; then
        die "Fast-forward pull failed (local commits or conflicts). Resolve manually, then re-run. Your backup: $LAST_BACKUP_DIR"
    fi
    ok "Code updated ($(git rev-parse --short HEAD) on $branch)"

    # New settings introduced by code updates
    ensure_env_key ENCRYPTION_KEY "$(gen_fernet_key)" "Fernet key for Shopify token encryption (auto-added)"
    ensure_env_key APP_URL "http://$(env_get SERVER_IP)" "Public base URL (auto-added)"
    ensure_env_key FRONTEND_URL "$(env_get APP_URL)" "Post-OAuth redirect target (auto-added)"
    ensure_env_key SHOPIFY_API_KEY "" "Shopify OAuth client id (auto-added — fill in to enable OAuth)"
    ensure_env_key SHOPIFY_API_SECRET "" "Shopify OAuth client secret (auto-added)"
    ensure_env_key ACCESS_TOKEN_EXPIRE_MINUTES "60"
    ensure_env_key REFRESH_TOKEN_EXPIRE_DAYS "7"
    ensure_env_key SHOPIFY_API_VERSION "2026-04" "Shopify Admin API version (auto-added)"
    # Retired API versions are served a fall-forward schema — pin the current one
    if grep -qE '^SHOPIFY_API_VERSION=202[0-5]-' .env; then
        sed -i.bak 's/^SHOPIFY_API_VERSION=.*/SHOPIFY_API_VERSION=2026-04/' .env && rm -f .env.bak
        ok "SHOPIFY_API_VERSION bumped to 2026-04"
    fi

    info "Rebuilding images..."
    docker compose -f "$COMPOSE_FILE" build --pull
    info "Restarting the stack..."
    docker compose -f "$COMPOSE_FILE" up -d

    wait_for_api || true
    run_migrations
    docker_cleanup

    echo ""
    ok "Update complete — backup saved in $LAST_BACKUP_DIR"
    docker compose -f "$COMPOSE_FILE" ps
}

# ----------------------------------------------------------------- remove ---

do_remove() {
    require_docker
    in_repo || die "Run this from the application directory (where $COMPOSE_FILE lives)."

    warn "This will stop and remove the application containers."
    read -rp "Create a final backup first? [Y/n] " b
    [[ "${b,,}" != "n" ]] && backup_now

    docker compose -f "$COMPOSE_FILE" down --remove-orphans
    ok "Containers stopped and removed"

    read -rp "Also delete data volumes (PostgreSQL + Redis — IRREVERSIBLE)? Type DELETE to confirm: " d
    if [ "$d" == "DELETE" ]; then
        docker compose -f "$COMPOSE_FILE" down -v --remove-orphans
        ok "Data volumes deleted"
    else
        info "Data volumes kept — a reinstall in this directory will reuse them"
    fi

    read -rp "Remove the application's Docker images? [y/N] " i
    if [[ "${i,,}" == "y" ]]; then
        docker compose -f "$COMPOSE_FILE" down --rmi local --remove-orphans 2>/dev/null || true
        docker_cleanup
    fi

    echo ""
    ok "Removal complete. Code, .env, and backups/ remain in $(pwd) — delete the directory manually if desired."
}

# ------------------------------------------------------------------- menu ---

# Support `curl -fsSL .../install.sh | bash`: reattach prompts to the terminal
if [ ! -t 0 ] && [ -e /dev/tty ]; then
    exec < /dev/tty
fi

echo ""
echo "Shopify Multi-Store Order Management — installer"
echo "─────────────────────────────────────────────────"
echo "  1) Install (new installation)"
echo "  2) Update from GitHub (backup → pull → rebuild → migrate → prune)"
echo "  3) Backup settings + database"
echo "  4) Remove application"
echo "  5) Exit"
echo ""
read -rp "Choose an option [1-5]: " choice
case "$choice" in
    1) do_install ;;
    2) do_update ;;
    3) require_docker; in_repo || die "Run from the application directory."; backup_now; ok "Backup saved in $LAST_BACKUP_DIR" ;;
    4) do_remove ;;
    5) exit 0 ;;
    *) die "Invalid option" ;;
esac
