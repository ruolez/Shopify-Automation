# Shopify Automation - Codebase Issues Analysis

**Generated:** January 2026
**Total Issues Identified:** 47
**Codebase:** Shopify Multi-Store Order Management System

---

## Quick Reference

| Priority | Count | Description |
|----------|-------|-------------|
| CRITICAL | 5 | Security vulnerabilities - fix before production |
| HIGH | 8 | Significant bugs/risks - fix within 1-2 weeks |
| MEDIUM | 14 | Code quality issues - address in next sprint |
| LOW | 20 | Improvements - backlog items |

---

## CRITICAL PRIORITY (Fix Immediately)

### CRIT-01: Hardcoded Secret Key
**File:** `backend/auth.py:14`
**Type:** Security Vulnerability

**Current Code:**
```python
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production")
```

**Problem:** Default secret key is used if environment variable is missing. This allows JWT token forgery in production if the env var is not set.

**Impact:** Complete authentication bypass possible.

**Fix:**
```python
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable must be set")
```

---

### CRIT-02: Access Tokens Stored in Plaintext
**File:** `backend/models.py:35`
**Type:** Security Vulnerability

**Current Code:**
```python
access_token = Column(Text, nullable=False)  # Comment says "Encrypted in production" but isn't
```

**Problem:** Shopify access tokens are stored unencrypted in the database. If the database is compromised, all connected stores are compromised.

**Impact:** Full access to all connected Shopify stores if database is breached.

**Fix:**
1. Add encryption utility using `cryptography.fernet`
2. Create `encrypted_access_token` column
3. Migrate existing tokens
4. Add decrypt method to ShopifyStore model

---

### CRIT-03: Database Credentials in Default URL
**File:** `backend/database.py:8`
**Type:** Security Vulnerability

**Current Code:**
```python
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://shopify_user:password@localhost:5432/shopify_db")
```

**Problem:** Default database URL contains hardcoded credentials that could be used in production.

**Impact:** Potential unauthorized database access.

**Fix:**
```python
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable must be set")
```

---

### CRIT-04: Debug Print Statements in Production
**Files:** `backend/main.py:856, 873, 878, 882`
**Type:** Information Disclosure

**Current Code:**
```python
print(f"DEBUG: GET settings for user {current_user.id} - timezone: {settings.timezone}...")
print(f"DEBUG: Updating settings for user {current_user.id}: {update_data}")
```

**Problem:** Debug print statements leak potentially sensitive information to stdout and may be visible in container logs.

**Impact:** Information disclosure, potential credential leakage.

**Fix:** Replace with proper logging:
```python
logger.debug(f"GET settings for user {current_user.id}")
```

---

### CRIT-05: Overly Long JWT Token Expiration
**File:** `backend/auth.py:16`
**Type:** Security Vulnerability

**Current Code:**
```python
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24 * 60  # 30 days
```

**Problem:** 30-day tokens are too long. If a token is compromised, the attacker has a month to abuse it.

**Impact:** Extended window for token abuse if compromised.

**Fix:** Use shorter-lived access tokens (15-60 minutes) with refresh tokens:
```python
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour
REFRESH_TOKEN_EXPIRE_DAYS = 7
```

---

## HIGH PRIORITY (Fix Soon)

### HIGH-01: Monolithic main.py File
**File:** `backend/main.py` (6700+ lines)
**Type:** Code Architecture

**Problem:** Single file contains all API endpoints, making it extremely difficult to:
- Navigate and understand the code
- Test individual components
- Perform code reviews
- Onboard new developers

**Impact:** Reduced maintainability, increased bug risk.

**Fix:** Split into modular routers:
```
backend/
├── routers/
│   ├── auth.py
│   ├── stores.py
│   ├── rules.py
│   ├── fraud.py
│   ├── inventory.py
│   ├── admin.py
│   └── settings.py
├── services/
│   ├── fraud_service.py
│   ├── order_service.py
│   └── sync_service.py
```

---

### HIGH-02: No Rate Limiting on API Endpoints
**File:** `backend/main.py` (entire file)
**Type:** Security Vulnerability

**Problem:** The FastAPI application has no rate limiting, making it vulnerable to:
- Brute force attacks on login
- DoS attacks
- Resource exhaustion
- API abuse

**Impact:** Service availability, security bypass.

**Fix:** Add `slowapi` rate limiting:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/auth/login")
@limiter.limit("5/minute")
async def login(...):
    ...
```

---

### HIGH-03: Race Conditions in Order Processing
**File:** `backend/tasks.py`
**Type:** Concurrency Bug

**Problem:** Multiple Celery workers could process the same order simultaneously. While there's a `ProcessedOrder` check, there's a TOCTOU (time-of-check-time-of-use) race condition between checking and inserting.

**Impact:** Duplicate order processing, inconsistent data.

**Fix:** Use database-level locking:
```python
# Use SELECT FOR UPDATE
existing = db.query(ProcessedOrder).with_for_update(skip_locked=True).filter(
    ProcessedOrder.store_id == store_id,
    ProcessedOrder.order_id == order_id
).first()

# Or use advisory locks for PostgreSQL
from sqlalchemy import text
db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": hash(order_id)})
```

---

### HIGH-04: Session Management Issues in Celery Tasks
**File:** `backend/tasks.py:67-70`
**Type:** Resource Leak

**Current Code:**
```python
def get_db():
    """Note: caller is responsible for closing it."""
    return SessionLocal()
```

**Problem:** Manual session management is error-prone. Several places don't properly close sessions on exceptions, leading to connection pool exhaustion.

**Impact:** Database connection leaks, service degradation.

**Fix:** Use context managers consistently:
```python
from contextlib import contextmanager

@contextmanager
def get_db_session():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Usage:
with get_db_session() as db:
    # do work
```

---

### HIGH-05: No Input Validation on Regex Patterns
**File:** `backend/rule_engine.py:542-550`
**Type:** Security Vulnerability (ReDoS)

**Current Code:**
```python
def _regex_match(self, actual: Any, expected: str) -> bool:
    if actual is None:
        return False
    try:
        pattern = re.compile(expected, re.IGNORECASE)  # User-controlled regex
        return bool(pattern.search(str(actual)))
    except re.error:
        logger.error(f"Invalid regex pattern: {expected}")
        return False
```

**Problem:** User-supplied regex patterns could cause ReDoS (Regular Expression Denial of Service) attacks with pathological patterns like `(a+)+$`.

**Impact:** Service denial, CPU exhaustion.

**Fix:**
```python
import regex  # Use regex library instead of re

def _regex_match(self, actual: Any, expected: str) -> bool:
    if actual is None:
        return False
    try:
        # Limit pattern complexity and add timeout
        if len(expected) > 100:
            logger.warning(f"Regex pattern too long: {len(expected)} chars")
            return False
        pattern = regex.compile(expected, regex.IGNORECASE, timeout=0.1)
        return bool(pattern.search(str(actual)))
    except (regex.error, TimeoutError) as e:
        logger.error(f"Regex error: {e}")
        return False
```

---

### HIGH-06: Missing CSRF Protection
**Files:** All state-changing endpoints
**Type:** Security Vulnerability

**Problem:** While JWT tokens provide some protection, the application doesn't implement CSRF tokens for state-changing operations. Combined with localStorage token storage, this creates XSS->CSRF attack chains.

**Impact:** Cross-site request forgery attacks possible.

**Fix:**
1. Implement CSRF tokens for sensitive operations
2. Or switch to HttpOnly cookies with SameSite attribute

---

### HIGH-07: Excessive Debug Logging in Production
**Files:** Multiple (50+ occurrences)
**Type:** Information Disclosure

**Example locations:**
- `backend/fraud_service.py:195-217`
- `backend/fraud_rule_processor.py:103, 317, 573-601`
- `backend/rule_engine.py:113-125, 175-187`

**Problem:** Extensive DEBUG logging statements that log sensitive data like order names, customer info, and internal state. These are visible in production logs.

**Impact:** Information disclosure, log storage costs.

**Fix:**
1. Gate behind environment variable
2. Remove emoji prefixes from production logs
3. Use structured logging with log levels

```python
if os.getenv("DEBUG_FRAUD", "false").lower() == "true":
    logger.debug(f"Fraud analysis details: {details}")
```

---

### HIGH-08: Deprecated datetime.utcnow()
**Files:** `backend/auth.py:30-32`, `backend/routers/settings.py:156`, `backend/routers/locations.py:403`, multiple others
**Type:** Deprecation Warning

**Current Code:**
```python
expire = datetime.utcnow() + expires_delta
```

**Problem:** `datetime.utcnow()` is deprecated in Python 3.12+ and returns naive datetime objects.

**Impact:** Timezone-related bugs, deprecation warnings.

**Fix:**
```python
from datetime import datetime, timezone

expire = datetime.now(timezone.utc) + expires_delta
```

---

## MEDIUM PRIORITY (Should Fix)

### MED-01: Missing Database Indexes
**File:** `backend/models.py`
**Type:** Performance

**Problem:** Several frequently-queried columns lack indexes:
- `fraud_analyses.shopify_fraud_risk_level`
- `order_logs.status`
- `order_logs.created_at`
- `fraud_analyses.analysis_timestamp`

**Impact:** Slow queries as data grows.

**Fix:** Add indexes in models:
```python
shopify_fraud_risk_level = Column(String, index=True)
```

Or via migration:
```python
op.create_index('ix_fraud_analyses_risk_level', 'fraud_analyses', ['shopify_fraud_risk_level'])
```

---

### MED-02: N+1 Query Issues
**Files:** Multiple endpoints in routers
**Type:** Performance

**Problem:** When fetching entities with relationships, relationships are loaded lazily causing N+1 queries. For example, fetching 100 fraud analyses with stores causes 101 queries.

**Impact:** Slow API responses, database overload.

**Fix:** Use eager loading:
```python
from sqlalchemy.orm import joinedload

analyses = db.query(FraudAnalysis).options(
    joinedload(FraudAnalysis.store),
    joinedload(FraudAnalysis.user)
).all()
```

---

### MED-03: No Connection Pool Monitoring
**File:** `backend/database.py`
**Type:** Observability

**Problem:** Database connections could exhaust silently without monitoring. No visibility into pool status.

**Impact:** Silent failures, difficult debugging.

**Fix:** Add connection pool event listeners:
```python
from sqlalchemy import event

@event.listens_for(engine, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    logger.debug("Connection checked out from pool")

@event.listens_for(engine, "checkin")
def receive_checkin(dbapi_connection, connection_record):
    logger.debug("Connection returned to pool")
```

---

### MED-04: Hardcoded Shopify API Version
**File:** `backend/shopify_client.py:13`
**Type:** Maintainability

**Current Code:**
```python
self.base_url = f"https://{shop_domain}/admin/api/2025-04"
```

**Problem:** API version is hardcoded. When Shopify deprecates it, all clients break simultaneously and require code change.

**Impact:** Forced emergency deployments when Shopify deprecates version.

**Fix:**
```python
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-04")
self.base_url = f"https://{shop_domain}/admin/api/{SHOPIFY_API_VERSION}"
```

---

### MED-05: Error Messages Leak Internal Details
**File:** `backend/shopify_client.py:57`
**Type:** Information Disclosure

**Current Code:**
```python
raise Exception(f"Shopify API error: {e.response.status_code}")
```

**Problem:** Exception messages may leak internal implementation details to API clients.

**Impact:** Information useful to attackers.

**Fix:** Use generic error messages for clients while logging details internally:
```python
logger.error(f"Shopify API error: {e.response.status_code} - {e.response.text}")
raise HTTPException(status_code=502, detail="External service error")
```

---

### MED-06: Frontend Token Storage in localStorage
**File:** `frontend/src/utils/api.ts:16`
**Type:** Security Risk

**Current Code:**
```javascript
const token = localStorage.getItem("token");
```

**Problem:** localStorage is vulnerable to XSS attacks. If any XSS vulnerability exists, tokens can be stolen.

**Impact:** Token theft via XSS.

**Fix Options:**
1. Use HttpOnly cookies (requires backend changes)
2. Use sessionStorage instead (tokens lost on tab close)
3. Implement token refresh with short-lived access tokens

---

### MED-07: Missing Type Hints
**Files:** Multiple throughout codebase
**Type:** Code Quality

**Problem:** Many functions lack proper type hints, making the code harder to maintain and preventing IDE assistance.

**Example:**
```python
# Current
def process_order(order, rules, db):
    ...

# Should be
def process_order(order: Dict[str, Any], rules: List[ProcessingRule], db: Session) -> ProcessingResult:
    ...
```

**Impact:** Reduced maintainability, bug risk.

---

### MED-08: Inconsistent Error Handling Patterns
**Files:** Throughout backend
**Type:** Code Quality

**Problem:** Some functions return `None` on error, others raise exceptions, others return empty dicts. This inconsistency makes error handling unpredictable.

**Examples:**
- `_get_order_field_value` returns `None` on error
- `_make_graphql_request` raises exceptions
- `get_query_cost_stats` returns dict with defaults

**Impact:** Difficult error handling, silent failures.

**Fix:** Establish consistent patterns:
1. Use Result types (success/error)
2. Always raise exceptions for errors
3. Document expected behavior

---

### MED-09: No Health Check Timeout
**File:** Health check endpoints
**Type:** Reliability

**Problem:** Health check endpoints should have timeouts to prevent hanging under high load, which could cause cascading failures in orchestration systems.

**Fix:** Add timeout wrapper:
```python
@app.get("/health")
async def health_check():
    try:
        async with asyncio.timeout(5):
            # Check database
            db.execute(text("SELECT 1"))
            return {"status": "healthy"}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="Health check timeout")
```

---

### MED-10: Missing Retry Logic for Database Operations
**File:** Various database operations
**Type:** Reliability

**Problem:** Database operations can fail due to transient issues (connection drops, deadlocks) but lack retry logic.

**Fix:** Add retry decorator:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def db_operation(db: Session):
    ...
```

---

### MED-11: Celery Tasks Missing Idempotency
**File:** `backend/tasks.py`
**Type:** Reliability

**Problem:** Background tasks could be executed multiple times due to Celery's at-least-once delivery, but aren't designed to be idempotent.

**Impact:** Duplicate processing, inconsistent state.

**Fix:** Design tasks to be idempotent:
1. Check if work already done before proceeding
2. Use unique constraints to prevent duplicates
3. Make operations reversible/repeatable

---

### MED-12: No Request Timeout on Frontend
**File:** `frontend/src/utils/api.ts`
**Type:** Reliability

**Current Code:**
```javascript
export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});
```

**Problem:** Axios requests have no timeout configured, which could cause indefinite hangs.

**Fix:**
```javascript
export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,  // 30 seconds
  headers: {
    "Content-Type": "application/json",
  },
});
```

---

### MED-13: Circular Import Risk
**File:** `backend/rule_engine.py:370`
**Type:** Code Architecture

**Current Code:**
```python
# Import inside function to avoid circular imports
from tasks import resolve_location_alias
```

**Problem:** Import inside function to avoid circular imports is a code smell indicating architectural issues.

**Impact:** Fragile imports, potential runtime errors.

**Fix:** Refactor to break circular dependency:
1. Move shared utilities to separate module
2. Use dependency injection
3. Restructure module hierarchy

---

### MED-14: Magic Numbers Throughout Code
**Files:** Various
**Type:** Code Quality

**Examples:**
```python
wait_time = 0.5 * (attempt + 1)  # What is 0.5?
if throttle_status.get("currentlyAvailable", float('inf')) < 500:  # Why 500?
task_time_limit=30 * 60  # Why 30 minutes?
```

**Fix:** Extract to named constants:
```python
RETRY_BACKOFF_MULTIPLIER = 0.5
GRAPHQL_LOW_QUOTA_THRESHOLD = 500
CELERY_TASK_TIME_LIMIT_SECONDS = 30 * 60
```

---

## LOW PRIORITY (Nice to Have)

### LOW-01: Missing Test Coverage for Critical Paths
**Problem:** While test files exist, critical paths like fraud detection and order processing lack comprehensive tests.

---

### LOW-02: No API Versioning
**Problem:** API endpoints lack versioning (e.g., `/api/v1/`), making backwards-compatible changes difficult.

---

### LOW-03: Inconsistent Logging Formats
**Problem:** Mix of f-strings, emojis, and different log levels makes log aggregation difficult.

---

### LOW-04: No OpenAPI Documentation Enhancement
**Problem:** FastAPI auto-generates OpenAPI docs, but they lack examples and detailed descriptions.

---

### LOW-05: Missing Pagination Limits
**Problem:** Some list endpoints don't enforce maximum pagination limits, allowing clients to request huge result sets.

---

### LOW-06: No Graceful Shutdown Handling
**Problem:** Workers don't implement graceful shutdown, potentially losing in-flight work.

---

### LOW-07: Unused Imports and Variables
**Problem:** Several files have unused imports that should be cleaned up.

---

### LOW-08: Large Frontend Components
**Problem:** Files like `FraudDetection.tsx` (76KB) and `Settings.tsx` (81KB) should be split into smaller components.

---

### LOW-09: No Structured Logging
**Problem:** Plain text logs make aggregation and analysis difficult. Should use structured JSON logging.

---

### LOW-10: Missing Request ID Tracing
**Problem:** Requests lack unique IDs for tracing through logs, making debugging difficult.

---

### LOW-11: No Retry Configuration for Shopify Client
**Problem:** While retry logic exists, it's not configurable via environment variables.

---

### LOW-12: Async/Sync Mixing in Celery Tasks
**Problem:** Creating new event loops per task is inefficient:
```python
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
```

---

### LOW-13: Missing Database Connection Health Check
**Problem:** Database connections could go stale without health checks in the pool.

---

### LOW-14: No Feature Flags
**Problem:** New features can't be gradually rolled out or quickly disabled without deployment.

---

### LOW-15: Hardcoded Pagination Defaults
**Problem:** Pagination defaults like `limit: int = 50` should be configurable via settings.

---

### LOW-16: Missing Audit Trail for Rule Changes
**Problem:** Changes to processing rules and fraud rules aren't logged for audit purposes.

---

### LOW-17: No Backup Verification
**Problem:** Database backup functionality exists but no verification that backups are restorable.

---

### LOW-18: Missing Memory Limits for Workers
**Problem:** Celery workers have no memory limits configured, could cause OOM issues.

---

### LOW-19: No SSL Certificate Verification Configuration
**Problem:** Shopify API calls don't explicitly configure SSL verification options.

---

### LOW-20: Debug Files in Repository
**Problem:** Multiple `debug_*.py` and one-off test files in the backend directory that should be in a separate directory or removed.

---

## How to Use This Document

### Addressing Issues

When working on an issue, reference it by ID (e.g., "CRIT-01" or "HIGH-03"):

```
Claude, let's work on fixing CRIT-01 (Hardcoded Secret Key)
```

### Tracking Progress

Mark issues as fixed by updating this document:

```markdown
### CRIT-01: Hardcoded Secret Key ✅ FIXED
**Fixed in:** commit abc123
**Date:** 2026-01-15
```

### Adding New Issues

Use the next available ID in the appropriate category:
- CRIT-06, CRIT-07, etc.
- HIGH-09, HIGH-10, etc.
- MED-15, MED-16, etc.
- LOW-21, LOW-22, etc.

---

## Recommended Fix Order

1. **Week 1 (Critical):**
   - CRIT-01: Secret key
   - CRIT-02: Token encryption
   - CRIT-03: Database URL
   - CRIT-04: Debug prints
   - CRIT-05: Token expiration

2. **Week 2-3 (High):**
   - HIGH-01: Split main.py
   - HIGH-02: Rate limiting
   - HIGH-03: Race conditions
   - HIGH-04: Session management

3. **Week 4+ (Medium):**
   - Work through medium priority items

4. **Ongoing (Low):**
   - Address as time permits during regular development
