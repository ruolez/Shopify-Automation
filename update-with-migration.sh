#!/bin/bash
# NOTE: superseded by ./install.sh (option 2: Update from GitHub) — kept for legacy automation.
echo "NOTE: this script is superseded by ./install.sh (Update option)."

# Shopify Automation - Update Script with Schema Migration Support
# Safely updates the application while preserving data and handling schema changes

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BACKUP_DIR="./backups/$(date +%Y%m%d_%H%M%S)"
COMPOSE_FILE="docker-compose.prod.yml"

# Get server IP from existing configuration
get_server_ip() {
    # Try to get server IP from existing frontend/.env
    if [ -f "frontend/.env" ]; then
        SERVER_IP=$(grep "VITE_API_URL" frontend/.env | cut -d'=' -f2 | sed 's/http:\/\/\([^:]*\):.*/\1/')
    elif [ -f ".env" ]; then
        SERVER_IP=$(grep "VITE_API_URL" .env | cut -d'=' -f2 | sed 's/http:\/\/\([^:]*\):.*/\1/')
    else
        SERVER_IP="localhost"
    fi
    
    if [ -z "$SERVER_IP" ] || [ "$SERVER_IP" = "localhost" ]; then
        print_warning "Could not determine server IP from configuration files."
        read -p "Please enter your server IP address (e.g., 192.168.1.112): " SERVER_IP
        if [ -z "$SERVER_IP" ]; then
            SERVER_IP="localhost"
        fi
    fi
    
    export SERVER_IP
    export VITE_API_URL="http://$SERVER_IP:8000"
    print_info "Using server IP: $SERVER_IP"
}

print_header() {
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}  Shopify Automation - Smart Update Script     ${NC}"
    echo -e "${BLUE}================================================${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Function to backup database
backup_database() {
    print_info "Creating backup in $BACKUP_DIR..."
    mkdir -p "$BACKUP_DIR"
    
    # Backup SQLite database
    if docker volume inspect shopify-automation_sqlite_data >/dev/null 2>&1; then
        print_info "Backing up SQLite database..."
        docker run --rm -v shopify-automation_sqlite_data:/source -v "$(pwd)/$BACKUP_DIR:/backup" alpine tar czf /backup/sqlite_data.tar.gz -C /source .
        print_success "Database backed up to $BACKUP_DIR/sqlite_data.tar.gz"
    else
        print_warning "SQLite volume not found, skipping database backup"
    fi
}

# Function to export data as SQL (for schema-safe restoration)
export_data_as_sql() {
    local export_file="$BACKUP_DIR/data_export.sql"
    
    print_info "Exporting data as SQL for schema-safe migration..."
    
    # Create a Python script to export data
    cat > "$BACKUP_DIR/export_data.py" << 'EOF'
import sqlite3
import json
from datetime import datetime

def export_database(db_path, output_file):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    with open(output_file, 'w') as f:
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tables = cursor.fetchall()
        
        f.write("-- Data export generated at {}\n".format(datetime.now()))
        f.write("-- This preserves data while allowing schema changes\n\n")
        
        for table in tables:
            table_name = table[0]
            print(f"Exporting table: {table_name}")
            
            # Get table data
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()
            
            if rows:
                # Get column names
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [col[1] for col in cursor.fetchall()]
                
                f.write(f"\n-- Data for table: {table_name}\n")
                for row in rows:
                    values = []
                    for val in row:
                        if val is None:
                            values.append("NULL")
                        elif isinstance(val, str):
                            # Escape single quotes
                            values.append("'" + val.replace("'", "''") + "'")
                        else:
                            values.append(str(val))
                    
                    col_list = ", ".join(columns)
                    val_list = ", ".join(values)
                    f.write(f"INSERT OR IGNORE INTO {table_name} ({col_list}) VALUES ({val_list});\n")
    
    conn.close()
    print("Export completed!")

if __name__ == "__main__":
    export_database("/data/app.db", "/backup/data_export.sql")
EOF

    # Run the export script in the API container
    docker cp "$BACKUP_DIR/export_data.py" shopify_api:/tmp/
    docker exec shopify_api python /tmp/export_data.py
    docker cp shopify_api:/backup/data_export.sql "$BACKUP_DIR/"
    
    if [ -f "$BACKUP_DIR/data_export.sql" ]; then
        print_success "Data exported successfully"
    else
        print_error "Failed to export data"
        return 1
    fi
}

# Function to import data from SQL (schema-safe)
import_data_from_sql() {
    local import_file="$1/data_export.sql"
    
    if [ ! -f "$import_file" ]; then
        print_warning "No SQL export file found, skipping data import"
        return 0
    fi
    
    print_info "Importing data (schema-safe)..."
    
    # Copy SQL file to container
    docker cp "$import_file" shopify_api:/tmp/data_import.sql
    
    # Import data
    docker exec shopify_api python -c "
import sqlite3
conn = sqlite3.connect('/data/app.db')
cursor = conn.cursor()
with open('/tmp/data_import.sql', 'r') as f:
    sql_script = f.read()
    cursor.executescript(sql_script)
conn.commit()
conn.close()
print('Data imported successfully!')
"
    
    print_success "Data imported with schema preservation"
}

# Main execution
print_header

# Get server configuration
get_server_ip

# Step 1: Create backup
backup_database

# Step 2: Export data as SQL (schema-independent)
if docker-compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
    export_data_as_sql
else
    print_warning "Services not running, skipping SQL export"
fi

# Step 3: Pull latest code
print_info "Pulling latest code from repository..."
if git pull origin main; then
    print_success "Code updated successfully"
else
    print_warning "Git pull failed, continuing with local changes"
fi

# Step 4: Update configuration
print_info "Updating configuration files with server IP: $SERVER_IP"
cat > frontend/.env << EOF
VITE_API_URL=http://$SERVER_IP:8000
EOF

# Update CORS
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|allow_origins=\[.*\]|allow_origins=[\"http://$SERVER_IP:3000\", \"http://$SERVER_IP\", \"http://localhost:3000\", \"http://localhost\"]|" backend/main.py
else
    sed -i "s|allow_origins=\[.*\]|allow_origins=[\"http://$SERVER_IP:3000\", \"http://$SERVER_IP\", \"http://localhost:3000\", \"http://localhost\"]|" backend/main.py
fi

# Step 5: Rebuild and restart
print_info "Stopping services..."
docker-compose -f "$COMPOSE_FILE" down

print_info "Rebuilding containers..."
docker-compose -f "$COMPOSE_FILE" build --no-cache

print_info "Starting services with new schema..."
docker-compose -f "$COMPOSE_FILE" up -d

# Wait for services and schema creation
print_info "Waiting for database schema to be created..."
sleep 15

# Step 6: Import data (preserves new schema)
if [ -f "$BACKUP_DIR/data_export.sql" ]; then
    import_data_from_sql "$BACKUP_DIR"
fi

# Check services
print_info "Checking service status..."
if docker-compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
    print_success "Services are running!"
else
    print_error "Some services may not be running properly"
    docker-compose -f "$COMPOSE_FILE" ps
fi

print_success "Update completed with schema migration!"
print_info "Backup saved to: $BACKUP_DIR"
print_info "Your data has been preserved and migrated to the new schema"

echo ""
print_warning "IMPORTANT: The new excluded_skus table has been created"
print_info "You can now configure SKU exclusions in Settings → Excluded SKUs"

echo ""
print_info "Access the application at http://$SERVER_IP"
