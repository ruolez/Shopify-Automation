#!/bin/bash

# Test script for install-prod.sh improvements
# This script verifies that the installation handles migrations correctly

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Testing Shopify Automation Installation ===${NC}"
echo

# Function to run a test
run_test() {
    local test_name="$1"
    local test_command="$2"
    
    echo -e "${BLUE}Running: ${test_name}${NC}"
    if eval "$test_command"; then
        echo -e "${GREEN}✓ ${test_name} passed${NC}"
    else
        echo -e "${RED}✗ ${test_name} failed${NC}"
        exit 1
    fi
    echo
}

# Test 1: Check if migration scripts exist
run_test "Migration scripts exist" "test -f backend/run_all_migrations.py && test -f backend/check_schema_version.py"

# Test 2: Check if init_admin.py is updated
run_test "init_admin.py updated" "grep -q 'ensure_tables=False' backend/init_admin.py"

# Test 3: Check if install script has migration support
run_test "Install script has migration support" "grep -q 'run_all_migrations.py' install-prod.sh"

# Test 4: Verify migration order is defined
run_test "Migration order defined" "grep -q 'MIGRATION_ORDER' backend/run_all_migrations.py"

# Test 5: Check all migration files exist
echo -e "${BLUE}Checking all migration files...${NC}"
migrations=(
    "add_delay_ms_to_rules"
    "add_timezone_to_settings"
    "add_fraud_sync_enabled"
    "add_fraud_detection_rules"
    "add_duplicate_detection_days_column"
    "add_delivery_analytics_column"
    "add_days_since_last_delivery_column"
    "add_user_id_to_task_status"
)

all_exist=true
for migration in "${migrations[@]}"; do
    if [ -f "backend/migrations/${migration}.py" ]; then
        echo -e "  ${GREEN}✓${NC} ${migration}.py"
    else
        echo -e "  ${RED}✗${NC} ${migration}.py missing"
        all_exist=false
    fi
done

if [ "$all_exist" = true ]; then
    echo -e "${GREEN}✓ All migration files exist${NC}"
else
    echo -e "${RED}✗ Some migration files are missing${NC}"
    exit 1
fi
echo

# Test 6: Syntax check on Python scripts
echo -e "${BLUE}Checking Python syntax...${NC}"
python3 -m py_compile backend/run_all_migrations.py
python3 -m py_compile backend/check_schema_version.py
python3 -m py_compile backend/init_admin.py
echo -e "${GREEN}✓ Python syntax check passed${NC}"
echo

# Summary
echo -e "${GREEN}=== All tests passed! ===${NC}"
echo
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Test fresh installation: ./install-prod.sh --clean"
echo "2. Test update with migrations: ./install-prod.sh --keep-db"
echo "3. Check schema version: docker exec shopify_api python check_schema_version.py"
echo
echo -e "${BLUE}See INSTALL_MIGRATION_GUIDE.md for detailed testing instructions${NC}"