# Manual vs Auto Fraud Analysis Data Comparison

## Visual Summary

```
MANUAL ANALYSIS                          AUTO/BULK PROCESSING
     │                                          │
     ▼                                          ▼
get_order_fraud_data()                    get_orders(include_fraud_data=True)
     │                                          │
     ▼                                          ▼
┌─────────────────────┐                 ┌─────────────────────┐
│ Data Structure:     │                 │ Data Structure:     │
│ • Nested format     │                 │ • Direct GraphQL    │
│ • snake_case fields │                 │ • camelCase fields  │
│ • Has order_info    │                 │ • No wrapper        │
└─────────────────────┘                 └─────────────────────┘
     │                                          │
     ▼                                          ▼
┌─────────────────────┐                 ┌─────────────────────┐
│ Customer Data:      │                 │ Customer Data:      │
│ ✅ Has order history│                 │ ❌ NO order history │
│ ✅ Has fulfillments │                 │ ❌ NO fulfillments  │
│ ✅ Can check dupes  │                 │ ❌ Can't check dupes│
└─────────────────────┘                 └─────────────────────┘
     │                                          │
     ▼                                          ▼
┌─────────────────────┐                 ┌─────────────────────┐
│ Custom Attributes:  │                 │ Custom Attributes:  │
│ • custom_attributes │                 │ • customAttributes  │
│ ✅ Age checker works│                 │ ✅ NOW FIXED!       │
└─────────────────────┘                 └─────────────────────┘
```

## Manual Analysis Flow (Single Order)

### 1. API Endpoint: `/fraud-detection/analyze/{store_id}`
```python
# In main.py
order_data = await client.get_order_fraud_data(order_name)
```

### 2. Data Fetching: `get_order_fraud_data()` in shopify_client.py
- **Query**: Uses order name search: `query: f"name:{order_name}"`
- **Data Structure**: Returns NESTED format with `order_info` wrapper
- **Custom Attributes**: Fetched as `customAttributes` (camelCase)
- **Data Transformation**: Converts GraphQL response to snake_case structure

**Key Fields Fetched**:
```graphql
{
  id, name, createdAt, totalPriceSet, note, email
  billingAddress { firstName, lastName, address1, address2, city, province, country, zip, phone }
  shippingAddress { firstName, lastName, address1, address2, city, province, country, zip, phone }
  transactions(first: 20) { id, status, kind, amountSet, createdAt, gateway, test }
  customer {
    id, email, firstName, lastName, numberOfOrders, createdAt, amountSpent
    orders(first: 10) {
      # Includes fulfillment data for previous orders
      fulfillments { deliveredAt, inTransitAt, events }
    }
  }
  lineItems(first: 20) { id, title, quantity, product, variant }
  fulfillments(first: 10) { deliveredAt, inTransitAt, events }
  risk { assessments { riskLevel, facts }, recommendation }
  customAttributes { key, value }  # ✅ INCLUDED
  metafields(first: 50) { namespace, key, value }
}
```

**Data Structure Returned**:
```python
{
    "order_info": {  # ⚠️ NESTED WRAPPER
        "id": order_data.get("id"),
        "name": order_data.get("name"),
        "created_at": order_data.get("createdAt"),
        "total_price": order_data.get("totalPriceSet", {}).get("shopMoney", {}).get("amount"),
        "note": order_data.get("note"),
        # etc...
    },
    "billing_address": order_data.get("billingAddress"),  # ⚠️ SNAKE_CASE
    "shipping_address": order_data.get("shippingAddress"),  # ⚠️ SNAKE_CASE
    "transactions": order_data.get("transactions", []),
    "customer": order_data.get("customer"),
    "line_items": [item["node"] for item in order_data.get("lineItems", {}).get("edges", [])],
    "fulfillments": order_data.get("fulfillments", []),
    "custom_attributes": order_data.get("customAttributes", []),  # ⚠️ SNAKE_CASE
    "risk": order_data.get("risk"),
}
```

## Auto/Bulk Processing Flow (Multiple Orders)

### 1. Celery Task: `trigger_fraud_analysis_all_recent()` in tasks.py
```python
# In tasks.py
orders_response = loop.run_until_complete(
    client.get_orders(
        limit=20,
        created_at_min=since_date.isoformat(),
        include_fraud_data=True  # ✅ This flag is critical!
    )
)
```

### 2. Data Fetching: `get_orders()` in shopify_client.py
- **Query**: Uses date range search with `include_fraud_data=True`
- **Data Structure**: Returns DIRECT GraphQL format (no wrapper)
- **Custom Attributes**: Fetched as `customAttributes` (camelCase)
- **Data Transformation**: NO transformation - raw GraphQL response

**Key Fields Fetched (with include_fraud_data=True)**:
```graphql
{
  id, name, createdAt, updatedAt, totalPriceSet, currentTotalWeight, tags
  displayFulfillmentStatus, displayFinancialStatus, note, email, phone
  customer { id, firstName, lastName, email, phone, numberOfOrders, createdAt, amountSpent }
  billingAddress { firstName, lastName, address1, address2, city, province, country, zip, phone }
  shippingAddress { firstName, lastName, address1, address2, city, province, country, zip, phone }
  shippingLines(first: 10) { title, code }
  lineItems(first: 20) { id, title, quantity, product, variant }
  fulfillmentOrders(first: 5) { id, status, assignedLocation, lineItems }
  transactions(first: 20) { id, status, kind, amountSet, createdAt, gateway, test, errorCode }
  risk { assessments { riskLevel, facts }, recommendation }
  customAttributes { key, value }  # ✅ INCLUDED
  metafields(first: 50) { namespace, key, value }
}
```

**Data Structure Passed to Fraud Service**:
```python
# Direct GraphQL response - NO TRANSFORMATION
{
    "id": "gid://shopify/Order/123",
    "name": "PW110527",
    "createdAt": "2025-01-01T10:00:00Z",
    "totalPriceSet": { "shopMoney": { "amount": "100.00" } },
    "billingAddress": { ... },  # ⚠️ CAMELCASE
    "shippingAddress": { ... },  # ⚠️ CAMELCASE
    "customAttributes": [ ... ],  # ⚠️ CAMELCASE
    "customer": {
        "orders": {
            "edges": [
                # Note: Customer order history does NOT include fulfillments by default
            ]
        }
    }
    # NO order_info wrapper!
}
```

## Key Differences That Can Cause Issues

### 1. **Data Structure Format**
- **Manual**: Wrapped in `order_info` with snake_case fields
- **Auto**: Direct GraphQL response with camelCase fields

### 2. **Field Naming Conventions**
| Field | Manual Analysis | Auto Processing |
|-------|----------------|-----------------|
| Billing Address | `billing_address` | `billingAddress` |
| Shipping Address | `shipping_address` | `shippingAddress` |
| Custom Attributes | `custom_attributes` | `customAttributes` |
| Total Price | `order_info.total_price` | `totalPriceSet.shopMoney.amount` |
| Created At | `order_info.created_at` | `createdAt` |
| Order Note | `order_info.note` | `note` |

### 3. **Customer Order History**
- **Manual**: Includes full fulfillment data for previous orders
- **Auto**: May NOT include fulfillment data for customer's previous orders

### 4. **Risk Assessment Path**
- **Manual**: `fraud_data['risk']`
- **Auto**: `order_data['risk']`

## Methods That Need Dual Format Handling

### ✅ Already Fixed:
1. `_detect_age_checker()` - Now checks both `custom_attributes` and `customAttributes`
2. `_extract_customer_notes()` - Now checks both formats
3. `_extract_additional_details()` - Now checks both formats

### ✅ Just Fixed:
4. `_check_restricted_state()` - Now checks both `billing_address` and `billingAddress`

### ⚠️ Still Need Checking:
1. `_check_same_billing_shipping()` - Already has fallback to `billingAddress` (GOOD)
2. `_check_billing_address_outside_us()` - Already has fallback to `billingAddress` (GOOD)
3. `_extract_order_total()` - Has logic for both formats but complex
4. `_get_previous_order_data()` - **CRITICAL ISSUE**: Bulk processing doesn't fetch customer order history!

### 🚨 CRITICAL ISSUE: Missing Customer Order History in Bulk Processing

The bulk processing query does NOT include customer order history, which breaks several fraud detection features:

**Manual Analysis Query**:
```graphql
customer {
    id, email, firstName, lastName, numberOfOrders
    orders(first: 10) {  # ✅ INCLUDES ORDER HISTORY
        edges {
            node {
                id, name, createdAt, totalPriceSet
                fulfillments {  # ✅ INCLUDES FULFILLMENT DATA
                    deliveredAt, status, events
                }
            }
        }
    }
}
```

**Bulk Processing Query**:
```graphql
customer {
    id, email, firstName, lastName, numberOfOrders
    # ❌ NO orders FIELD - MISSING ORDER HISTORY!
}
```

**Impact on Fraud Detection**:
1. ❌ `_get_previous_order_delivery_status()` - Returns None (can't check previous delivery)
2. ❌ `_check_duplicate_within_7days()` - Always returns False (no order history to check)
3. ❌ `_get_previous_order_data()` - Returns (None, None) for delivery status and total
4. ❌ Previous order analysis features completely broken in bulk processing

## Recommendations

1. **Standardize Data Format**: Consider transforming all order data to a consistent format before passing to fraud service
2. **Add More Logging**: Add debug logging to show which format is being used
3. **Test Both Paths**: Create unit tests that verify both data formats work correctly
4. **Customer Order History**: Ensure bulk processing includes fulfillment data for customer's previous orders