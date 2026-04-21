import httpx
import json
import asyncio
import os
from typing import Dict, List, Optional, Any

from logging_config import get_logger, debug_log, DEBUG_LOGGING

logger = get_logger(__name__)

class ShopifyClient:
    def __init__(self, shop_domain: str, access_token: str):
        self.shop_domain = shop_domain
        self.access_token = access_token
        api_version = os.getenv("SHOPIFY_API_VERSION", "2025-04")
        self.base_url = f"https://{shop_domain}/admin/api/{api_version}"
        self.headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json"
        }
        # GraphQL cost tracking
        self._last_query_cost = None
        self._total_query_cost = 0
        self._query_count = 0
        self._high_cost_query_count = 0
        self._auto_optimization_enabled = True
        self._current_optimization_level = "balanced"
    
    async def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, retry_count: int = 3) -> Dict:
        """Make authenticated request to Shopify API with retry logic"""
        # Configure timeout: 60 seconds for connection/read, 120 seconds total
        timeout = httpx.Timeout(connect=60.0, read=60.0, write=60.0, pool=120.0)
        
        last_exception = None
        for attempt in range(retry_count):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    url = f"{self.base_url}/{endpoint}"
                    
                    if method.upper() == "GET":
                        response = await client.get(url, headers=self.headers, params=data)
                    elif method.upper() == "POST":
                        response = await client.post(url, headers=self.headers, json=data)
                    else:
                        raise ValueError(f"Unsupported HTTP method: {method}")
                    
                    response.raise_for_status()
                    return response.json()
                    
            except httpx.HTTPStatusError as e:
                logger.error(f"Shopify API error: {e.response.status_code} - {e.response.text}")
                # Don't retry on HTTP errors (4xx, 5xx) except for 429 (rate limit) and 5xx errors
                if e.response.status_code == 429 or e.response.status_code >= 500:
                    last_exception = Exception(f"Shopify API error: {e.response.status_code}")
                    if attempt < retry_count - 1:
                        wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                        logger.info(f"Retrying after {wait_time} seconds (attempt {attempt + 1}/{retry_count})")
                        await asyncio.sleep(wait_time)
                        continue
                raise Exception(f"Shopify API error: {e.response.status_code}")
            except httpx.ReadTimeout as e:
                logger.error(f"Shopify API timeout after 60 seconds: {str(e)}")
                last_exception = Exception(f"Shopify API timeout: Request took too long to complete")
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.info(f"Retrying after timeout, waiting {wait_time} seconds (attempt {attempt + 1}/{retry_count})")
                    await asyncio.sleep(wait_time)
                    continue
            except Exception as e:
                logger.error(f"Request failed: {str(e)}")
                last_exception = e
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.info(f"Retrying after error, waiting {wait_time} seconds (attempt {attempt + 1}/{retry_count})")
                    await asyncio.sleep(wait_time)
                    continue
        
        # If we've exhausted all retries, raise the last exception
        if last_exception:
            raise last_exception
        raise Exception("Request failed after all retry attempts")
    
    async def _make_graphql_request(self, query: str, variables: Optional[Dict] = None, retry_count: int = 3) -> Dict:
        """Make GraphQL request to Shopify Admin API with cost tracking and retry logic"""
        # Configure timeout: 60 seconds for connection/read, 120 seconds total
        timeout = httpx.Timeout(connect=60.0, read=60.0, write=60.0, pool=120.0)
        
        last_exception = None
        for attempt in range(retry_count):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    url = f"{self.base_url}/graphql.json"
                    
                    payload = {
                        "query": query,
                        "variables": variables or {}
                    }
                    
                    response = await client.post(url, headers=self.headers, json=payload)
                    response.raise_for_status()
                    result = response.json()
                    
                    # Track GraphQL query costs
                    if "extensions" in result and "cost" in result["extensions"]:
                        cost_data = result["extensions"]["cost"]
                        actual_cost = cost_data.get("actualQueryCost", 0)
                        requested_cost = cost_data.get("requestedQueryCost", 0)
                        throttle_status = cost_data.get("throttleStatus", {})
                        
                        self._last_query_cost = actual_cost
                        self._total_query_cost += actual_cost
                        self._query_count += 1
                        
                        # Log cost information
                        logger.info(f"GraphQL Query Cost: {actual_cost}/{requested_cost} "
                                   f"(Available: {throttle_status.get('currentlyAvailable', 'N/A')}/{throttle_status.get('maximumAvailable', 'N/A')})")
                        
                        # Warn if approaching rate limit
                        if throttle_status.get("currentlyAvailable", float('inf')) < 500:
                            logger.warning(f"Low GraphQL quota remaining: {throttle_status.get('currentlyAvailable')} points")
                        
                        # Log high-cost queries for optimization
                        if actual_cost > 500:
                            logger.warning(f"High-cost GraphQL query detected: {actual_cost} points. Consider optimizing query structure.")
                            self._high_cost_query_count += 1
                            
                            # Auto-adjust optimization level if enabled
                            if self._auto_optimization_enabled and self._high_cost_query_count > 3:
                                if self._current_optimization_level == "full":
                                    self._current_optimization_level = "balanced"
                                    logger.info("Auto-adjusting optimization level from 'full' to 'balanced' due to high query costs")
                                elif self._current_optimization_level == "balanced":
                                    self._current_optimization_level = "minimal"
                                    logger.info("Auto-adjusting optimization level from 'balanced' to 'minimal' due to high query costs")
                    
                    if "errors" in result:
                        logger.error(f"GraphQL errors: {result['errors']}")
                        raise Exception(f"GraphQL errors: {result['errors']}")
                    
                    return result
                    
            except httpx.HTTPStatusError as e:
                logger.error(f"Shopify GraphQL error: {e.response.status_code} - {e.response.text}")
                # Don't retry on HTTP errors (4xx) except for 429 (rate limit) and 5xx errors
                if e.response.status_code == 429 or e.response.status_code >= 500:
                    last_exception = Exception(f"Shopify GraphQL error: {e.response.status_code}")
                    if attempt < retry_count - 1:
                        wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                        logger.info(f"Retrying GraphQL request after {wait_time} seconds (attempt {attempt + 1}/{retry_count})")
                        await asyncio.sleep(wait_time)
                        continue
                raise Exception(f"Shopify GraphQL error: {e.response.status_code}")
            except httpx.ReadTimeout as e:
                logger.error(f"Shopify GraphQL timeout after 60 seconds: {str(e)}")
                last_exception = Exception(f"Shopify GraphQL timeout: Request took too long to complete")
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.info(f"Retrying GraphQL request after timeout, waiting {wait_time} seconds (attempt {attempt + 1}/{retry_count})")
                    await asyncio.sleep(wait_time)
                    continue
            except Exception as e:
                logger.error(f"GraphQL request failed: {str(e)}")
                last_exception = e
                if attempt < retry_count - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.info(f"Retrying GraphQL request after error, waiting {wait_time} seconds (attempt {attempt + 1}/{retry_count})")
                    await asyncio.sleep(wait_time)
                    continue
        
        # If we've exhausted all retries, raise the last exception
        if last_exception:
            raise last_exception
        raise Exception("GraphQL request failed after all retry attempts")
    
    def get_query_cost_stats(self) -> Dict[str, Any]:
        """Get GraphQL query cost statistics"""
        return {
            "last_query_cost": self._last_query_cost,
            "total_query_cost": self._total_query_cost,
            "query_count": self._query_count,
            "average_query_cost": self._total_query_cost / self._query_count if self._query_count > 0 else 0,
            "high_cost_query_count": self._high_cost_query_count,
            "current_optimization_level": self._current_optimization_level,
            "auto_optimization_enabled": self._auto_optimization_enabled
        }
    
    def set_auto_optimization(self, enabled: bool):
        """Enable or disable automatic query optimization"""
        self._auto_optimization_enabled = enabled
        logger.info(f"Auto-optimization {'enabled' if enabled else 'disabled'}")
    
    def reset_cost_stats(self):
        """Reset query cost statistics"""
        self._total_query_cost = 0
        self._query_count = 0
        self._high_cost_query_count = 0
        self._current_optimization_level = "balanced"
        logger.info("Query cost statistics reset")
    
    async def get_shop_info(self) -> Dict:
        """Get shop information"""
        query = """
        query {
            shop {
                id
                name
                email
                myshopifyDomain
                plan {
                    displayName
                }
            }
        }
        """
        
        result = await self._make_graphql_request(query)
        return result["data"]["shop"]
    
    async def get_orders(
        self, 
        limit: int = 50, 
        created_at_min: Optional[str] = None,
        cursor: Optional[str] = None,
        include_fraud_data: bool = False
    ) -> Dict:
        """Get orders with pagination and optional fraud data"""
        if include_fraud_data:
            query = """
            query getOrdersWithFraudData($first: Int, $after: String, $query: String) {
                orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
                            updatedAt
                            totalPriceSet {
                                shopMoney {
                                    amount
                                    currencyCode
                                }
                            }
                            currentTotalWeight
                            tags
                            displayFulfillmentStatus
                            displayFinancialStatus
                            note
                            email
                            phone
                            customer {
                                id
                                firstName
                                lastName
                                email
                                phone
                                numberOfOrders
                                createdAt
                                amountSpent {
                                    amount
                                    currencyCode
                                }
                                orders(first: 2, sortKey: CREATED_AT, reverse: true) {
                                    edges {
                                        node {
                                            id
                                            name
                                            createdAt
                                            totalPriceSet {
                                                shopMoney {
                                                    amount
                                                }
                                            }
                                            fulfillments(first: 5) {
                                                id
                                                status
                                                displayStatus
                                                deliveredAt
                                                events(first: 10, sortKey: HAPPENED_AT, reverse: true) {
                                                    edges {
                                                        node {
                                                            status
                                                            happenedAt
                                                            message
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            billingAddress {
                                firstName
                                lastName
                                address1
                                address2
                                city
                                province
                                country
                                zip
                                phone
                            }
                            shippingAddress {
                                firstName
                                lastName
                                address1
                                address2
                                city
                                province
                                country
                                zip
                                phone
                            }
                            shippingLines(first: 10) {
                                edges {
                                    node {
                                        title
                                        code
                                    }
                                }
                            }
                            lineItems(first: 20) {
                                edges {
                                    node {
                                        id
                                        title
                                        quantity
                                        product {
                                            id
                                            productType
                                            vendor
                                            tags
                                        }
                                        variant {
                                            id
                                            title
                                            sku
                                            inventoryItem {
                                                measurement {
                                                    weight {
                                                        value
                                                        unit
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            fulfillmentOrders(first: 5) {
                                edges {
                                    node {
                                        id
                                        status
                                        assignedLocation {
                                            location {
                                                id
                                                name
                                            }
                                        }
                                        lineItems(first: 20) {
                                            edges {
                                                node {
                                                    id
                                                    totalQuantity
                                                    remainingQuantity
                                                    variant {
                                                        id
                                                        sku
                                                        product {
                                                            id
                                                            title
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            transactions(first: 20) {
                                id
                                status
                                kind
                                amountSet {
                                    shopMoney {
                                        amount
                                        currencyCode
                                    }
                                }
                                createdAt
                                gateway
                                test
                                errorCode
                                parentTransaction {
                                    id
                                }
                            }
                            risk {
                                assessments {
                                    riskLevel
                                    facts {
                                        description
                                        sentiment
                                    }
                                    provider {
                                        id
                                    }
                                }
                                recommendation
                            }
                            customAttributes {
                                key
                                value
                            }
                            metafields(first: 50) {
                                edges {
                                    node {
                                        namespace
                                        key
                                        value
                                        type
                                    }
                                }
                            }
                        }
                    }
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                }
            }
            """
        else:
            query = """
            query getOrders($first: Int, $after: String, $query: String) {
                orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
                    edges {
                        node {
                            id
                            name
                            createdAt
                            updatedAt
                            totalPriceSet {
                                shopMoney {
                                    amount
                                    currencyCode
                                }
                            }
                            currentTotalWeight
                            tags
                            displayFulfillmentStatus
                            customer {
                                id
                                firstName
                                lastName
                                email
                            }
                            shippingAddress {
                                province
                                country
                                city
                                zip
                            }
                            shippingLines(first: 10) {
                                edges {
                                    node {
                                        title
                                        code
                                    }
                                }
                            }
                            lineItems(first: 20) {
                                edges {
                                    node {
                                        id
                                        title
                                        quantity
                                        product {
                                            id
                                            productType
                                            vendor
                                            tags
                                        }
                                        variant {
                                            id
                                            title
                                            sku
                                            inventoryItem {
                                                measurement {
                                                    weight {
                                                        value
                                                        unit
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            fulfillmentOrders(first: 5) {
                                edges {
                                    node {
                                        id
                                        status
                                        assignedLocation {
                                            location {
                                                id
                                                name
                                            }
                                        }
                                        lineItems(first: 20) {
                                            edges {
                                                node {
                                                    id
                                                    totalQuantity
                                                    remainingQuantity
                                                    variant {
                                                        id
                                                        sku
                                                        product {
                                                            id
                                                            title
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                }
            }
            """
        
        variables = {
            "first": limit,
            "after": cursor
        }
        
        # Add date filter if provided
        if created_at_min:
            variables["query"] = f"created_at:>={created_at_min}"
        
        result = await self._make_graphql_request(query, variables)
        return result["data"]["orders"]
    
    async def get_orders_optimized(
        self, 
        limit: int = 10, 
        created_at_min: Optional[str] = None,
        cursor: Optional[str] = None,
        include_fraud_data: bool = False,
        optimization_level: str = "balanced"
    ) -> Dict:
        """Get orders with optimized GraphQL queries based on cost constraints
        
        Args:
            limit: Number of orders to fetch (adjusted based on optimization level)
            created_at_min: Minimum creation date filter
            cursor: Pagination cursor
            include_fraud_data: Whether to include fraud analysis data
            optimization_level: "minimal", "balanced", or "full"
        """
        # Adjust limits based on optimization level
        if optimization_level == "minimal":
            # Minimal query - only essential data
            order_limit = min(limit, 50)
            line_item_limit = 10
            fulfillment_limit = 3
            transaction_limit = 5
            include_metafields = False
            include_customer_orders = False
        elif optimization_level == "balanced":
            # Balanced query - good trade-off between data and cost
            order_limit = min(limit, 25)
            line_item_limit = 15
            fulfillment_limit = 5
            transaction_limit = 10
            include_metafields = True
            include_customer_orders = include_fraud_data
        else:  # full
            # Full query - all data but smaller page size
            order_limit = min(limit, 10)
            line_item_limit = 20
            fulfillment_limit = 5
            transaction_limit = 20
            include_metafields = True
            include_customer_orders = include_fraud_data
        
        # Build optimized query
        if include_fraud_data and optimization_level != "minimal":
            query = f"""
            query getOrdersOptimized($first: Int, $after: String, $query: String) {{
                orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {{
                    edges {{
                        node {{
                            id
                            name
                            createdAt
                            updatedAt
                            totalPriceSet {{
                                shopMoney {{
                                    amount
                                    currencyCode
                                }}
                            }}
                            currentTotalWeight
                            tags
                            displayFulfillmentStatus
                            displayFinancialStatus
                            note
                            email
                            phone
                            customer {{
                                id
                                firstName
                                lastName
                                email
                                phone
                                numberOfOrders
                                createdAt
                                {'''amountSpent {
                                    amount
                                    currencyCode
                                }
                                orders(first: 2, sortKey: CREATED_AT, reverse: true) {
                                    edges {
                                        node {
                                            id
                                            name
                                            createdAt
                                            totalPriceSet {
                                                shopMoney {
                                                    amount
                                                }
                                            }
                                            fulfillments(first: 5) {
                                                id
                                                status
                                                displayStatus
                                                deliveredAt
                                            }
                                        }
                                    }
                                }''' if include_customer_orders else ''}
                            }}
                            billingAddress {{
                                firstName
                                lastName
                                address1
                                city
                                province
                                country
                                zip
                            }}
                            shippingAddress {{
                                firstName
                                lastName
                                address1
                                city
                                province
                                country
                                zip
                            }}
                            shippingLines(first: 10) {{
                                edges {{
                                    node {{
                                        title
                                        code
                                    }}
                                }}
                            }}
                            lineItems(first: {line_item_limit}) {{
                                edges {{
                                    node {{
                                        id
                                        title
                                        quantity
                                        product {{
                                            id
                                            productType
                                            vendor
                                            tags
                                        }}
                                        variant {{
                                            id
                                            title
                                            sku
                                            inventoryItem {{
                                                measurement {{
                                                    weight {{
                                                        value
                                                        unit
                                                    }}
                                                }}
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                            fulfillmentOrders(first: {fulfillment_limit}) {{
                                edges {{
                                    node {{
                                        id
                                        status
                                        assignedLocation {{
                                            location {{
                                                id
                                                name
                                            }}
                                        }}
                                        lineItems(first: {line_item_limit}) {{
                                            edges {{
                                                node {{
                                                    id
                                                    totalQuantity
                                                    remainingQuantity
                                                    variant {{
                                                        id
                                                        sku
                                                    }}
                                                }}
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                            transactions(first: {transaction_limit}) {{
                                id
                                status
                                kind
                                amountSet {{
                                    shopMoney {{
                                        amount
                                        currencyCode
                                    }}
                                }}
                                createdAt
                                gateway
                                test
                                errorCode
                            }}
                            risk {{
                                assessments {{
                                    riskLevel
                                    facts {{
                                        description
                                        sentiment
                                    }}
                                }}
                                recommendation
                            }}
                            customAttributes {{
                                key
                                value
                            }}
                            {'''metafields(first: 20) {
                                edges {
                                    node {
                                        namespace
                                        key
                                        value
                                        type
                                    }
                                }
                            }''' if include_metafields else ''}
                        }}
                    }}
                    pageInfo {{
                        hasNextPage
                        endCursor
                    }}
                }}
            }}
            """
        else:
            # Minimal query for regular order processing
            query = f"""
            query getOrdersMinimal($first: Int, $after: String, $query: String) {{
                orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {{
                    edges {{
                        node {{
                            id
                            name
                            createdAt
                            updatedAt
                            totalPriceSet {{
                                shopMoney {{
                                    amount
                                    currencyCode
                                }}
                            }}
                            currentTotalWeight
                            tags
                            displayFulfillmentStatus
                            customer {{
                                id
                                firstName
                                lastName
                                email
                            }}
                            shippingAddress {{
                                province
                                country
                                city
                                zip
                            }}
                            shippingLines(first: 10) {{
                                edges {{
                                    node {{
                                        title
                                        code
                                    }}
                                }}
                            }}
                            lineItems(first: {line_item_limit}) {{
                                edges {{
                                    node {{
                                        id
                                        title
                                        quantity
                                        product {{
                                            id
                                            productType
                                            vendor
                                            tags
                                        }}
                                        variant {{
                                            id
                                            title
                                            sku
                                            inventoryItem {{
                                                measurement {{
                                                    weight {{
                                                        value
                                                        unit
                                                    }}
                                                }}
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                            fulfillmentOrders(first: {fulfillment_limit}) {{
                                edges {{
                                    node {{
                                        id
                                        status
                                        assignedLocation {{
                                            location {{
                                                id
                                                name
                                            }}
                                        }}
                                        lineItems(first: {line_item_limit}) {{
                                            edges {{
                                                node {{
                                                    id
                                                    totalQuantity
                                                    remainingQuantity
                                                    variant {{
                                                        id
                                                        sku
                                                    }}
                                                }}
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                    pageInfo {{
                        hasNextPage
                        endCursor
                    }}
                }}
            }}
            """
        
        variables = {
            "first": order_limit,
            "after": cursor
        }
        
        # Add date filter if provided
        if created_at_min:
            variables["query"] = f"created_at:>={created_at_min}"
        
        result = await self._make_graphql_request(query, variables)
        
        # Log optimization info
        if self._last_query_cost:
            logger.info(f"Query optimization level: {optimization_level}, Cost: {self._last_query_cost}, Orders fetched: {order_limit}")
        
        return result["data"]["orders"]
    
    async def get_orders_adaptive(
        self, 
        limit: int = 25, 
        created_at_min: Optional[str] = None,
        cursor: Optional[str] = None,
        include_fraud_data: bool = False
    ) -> Dict:
        """Get orders with automatic optimization based on query costs
        
        This method automatically adjusts the optimization level based on
        recent query costs to maintain a balance between data completeness
        and API quota usage.
        """
        # Use the current optimization level which is automatically adjusted
        optimization_level = self._current_optimization_level if self._auto_optimization_enabled else "balanced"
        
        logger.debug(f"Using adaptive optimization level: {optimization_level}")
        
        return await self.get_orders_optimized(
            limit=limit,
            created_at_min=created_at_min,
            cursor=cursor,
            include_fraud_data=include_fraud_data,
            optimization_level=optimization_level
        )
    
    async def add_tags_to_order(self, order_id: str, tags: List[str]) -> bool:
        """Add tags to an order"""
        mutation = """
        mutation tagsAdd($id: ID!, $tags: [String!]!) {
            tagsAdd(id: $id, tags: $tags) {
                node {
                    id
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "id": order_id,
            "tags": tags
        }
        
        try:
            result = await self._make_graphql_request(mutation, variables)
            if result["data"]["tagsAdd"]["userErrors"]:
                logger.error(f"Error adding tags: {result['data']['tagsAdd']['userErrors']}")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to add tags to order {order_id}: {str(e)}")
            return False
    
    async def remove_tags_from_order(self, order_id: str, tags: List[str]) -> bool:
        """Remove tags from an order"""
        mutation = """
        mutation tagsRemove($id: ID!, $tags: [String!]!) {
            tagsRemove(id: $id, tags: $tags) {
                node {
                    id
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "id": order_id,
            "tags": tags
        }
        
        try:
            result = await self._make_graphql_request(mutation, variables)
            if result["data"]["tagsRemove"]["userErrors"]:
                logger.error(f"Error removing tags: {result['data']['tagsRemove']['userErrors']}")
                return False
            return True
        except Exception as e:
            logger.error(f"Failed to remove tags from order {order_id}: {str(e)}")
            return False
    
    async def move_fulfillment_order(
        self, 
        fulfillment_order_id: str, 
        new_location_id: str,
        line_items: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """Move fulfillment order to new location"""
        mutation = """
        mutation fulfillmentOrderMove($id: ID!, $newLocationId: ID!, $fulfillmentOrderLineItems: [FulfillmentOrderLineItemInput!]) {
            fulfillmentOrderMove(
                id: $id, 
                newLocationId: $newLocationId,
                fulfillmentOrderLineItems: $fulfillmentOrderLineItems
            ) {
                movedFulfillmentOrder {
                    id
                    assignedLocation {
                        location {
                            id
                            name
                        }
                    }
                    lineItems(first: 50) {
                        edges {
                            node {
                                id
                                totalQuantity
                                remainingQuantity
                                variant {
                                    id
                                    sku
                                    product {
                                        id
                                        title
                                    }
                                }
                            }
                        }
                    }
                }
                remainingFulfillmentOrder {
                    id
                    lineItems(first: 50) {
                        edges {
                            node {
                                id
                                totalQuantity
                                remainingQuantity
                                variant {
                                    id
                                    sku
                                    product {
                                        id
                                        title
                                    }
                                }
                            }
                        }
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "id": fulfillment_order_id,
            "newLocationId": new_location_id
        }
        
        if line_items:
            variables["fulfillmentOrderLineItems"] = line_items
        
        try:
            result = await self._make_graphql_request(mutation, variables)
            
            move_result = result["data"]["fulfillmentOrderMove"]
            
            if move_result["userErrors"]:
                logger.error(f"Error moving fulfillment order: {move_result['userErrors']}")
                return {
                    "success": False,
                    "errors": move_result["userErrors"],
                    "moved_items": [],
                    "failed_items": []
                }
            
            # Analyze what was moved vs what remained
            moved_items = []
            failed_items = []
            
            # Items that were successfully moved
            if move_result["movedFulfillmentOrder"]:
                moved_fo = move_result["movedFulfillmentOrder"]
                for item_edge in moved_fo.get("lineItems", {}).get("edges", []):
                    item = item_edge["node"]
                    moved_items.append({
                        "line_item_id": item["id"],
                        "product_id": item["variant"]["product"]["id"],
                        "variant_id": item["variant"]["id"], 
                        "product_title": item["variant"]["product"]["title"],
                        "sku": item["variant"]["sku"],
                        "moved_quantity": item["totalQuantity"],
                        "remaining_quantity": item["remainingQuantity"]
                    })
            
            # Items that couldn't be moved (remaining in original location)
            if move_result["remainingFulfillmentOrder"]:
                remaining_fo = move_result["remainingFulfillmentOrder"]
                for item_edge in remaining_fo.get("lineItems", {}).get("edges", []):
                    item = item_edge["node"]
                    failed_items.append({
                        "line_item_id": item["id"],
                        "product_id": item["variant"]["product"]["id"],
                        "variant_id": item["variant"]["id"],
                        "product_title": item["variant"]["product"]["title"], 
                        "sku": item["variant"]["sku"],
                        "failed_quantity": item["remainingQuantity"]
                    })
            
            # Determine overall success
            has_failures = len(failed_items) > 0
            has_successes = len(moved_items) > 0
            
            if has_failures:
                logger.warning(f"Partial fulfillment move - {len(moved_items)} items moved, {len(failed_items)} items failed")
            
            return {
                "success": not has_failures,  # Only true if everything moved
                "partial_success": has_successes and has_failures,
                "moved_items": moved_items,
                "failed_items": failed_items,
                "errors": []
            }
            
        except Exception as e:
            logger.error(f"Failed to move fulfillment order {fulfillment_order_id}: {str(e)}")
            return {
                "success": False,
                "errors": [{"message": str(e)}],
                "moved_items": [],
                "failed_items": []
            }
    
    async def get_locations(self) -> List[Dict]:
        """Get available fulfillment locations"""
        query = """
        query {
            locations(first: 50) {
                edges {
                    node {
                        id
                        name
                        address {
                            province
                            country
                            city
                        }
                        fulfillsOnlineOrders
                        isActive
                    }
                }
            }
        }
        """
        
        result = await self._make_graphql_request(query)
        locations = []
        all_locations = result["data"]["locations"]["edges"]
        
        logger.info(f"Found {len(all_locations)} total locations")
        
        for edge in all_locations:
            location = edge["node"]
            logger.info(f"Location: {location['name']} - fulfillsOnlineOrders: {location['fulfillsOnlineOrders']}, isActive: {location['isActive']}")
            
            # Include all active locations, not just those that fulfill online orders
            # Some fulfillment locations might not have fulfillsOnlineOrders=True but can still be used for fulfillment
            if location["isActive"]:
                locations.append(location)
        
        logger.info(f"Returning {len(locations)} active locations")
        return locations
    
    async def get_order_by_id(self, order_id: str, include_fraud_data: bool = False) -> Dict | None:
        """Get a specific order by ID for retry processing"""
        if include_fraud_data:
            query = """
            query getOrderByIdWithFraudData($id: ID!) {
                order(id: $id) {
                    id
                    name
                    createdAt
                    updatedAt
                    totalPriceSet {
                        shopMoney {
                            amount
                            currencyCode
                        }
                    }
                    currentTotalWeight
                    tags
                    displayFulfillmentStatus
                    displayFinancialStatus
                    note
                    email
                    phone
                    customer {
                        id
                        firstName
                        lastName
                        email
                        phone
                        numberOfOrders
                        createdAt
                        amountSpent {
                            amount
                            currencyCode
                        }
                        orders(first: 10, sortKey: CREATED_AT, reverse: true) {
                            edges {
                                node {
                                    id
                                    name
                                    createdAt
                                }
                            }
                        }
                    }
                    billingAddress {
                        firstName
                        lastName
                        address1
                        address2
                        city
                        province
                        country
                        zip
                        phone
                    }
                    shippingAddress {
                        firstName
                        lastName
                        address1
                        address2
                        city
                        province
                        country
                        zip
                        phone
                    }
                    shippingLines(first: 10) {
                        edges {
                            node {
                                title
                                code
                            }
                        }
                    }
                    lineItems(first: 100) {
                        edges {
                            node {
                                id
                                title
                                quantity
                                product {
                                    id
                                    productType
                                    vendor
                                    tags
                                }
                                variant {
                                    id
                                    title
                                    sku
                                    inventoryItem {
                                        measurement {
                                            weight {
                                                value
                                                unit
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    fulfillmentOrders(first: 5) {
                        edges {
                            node {
                                id
                                status
                                assignedLocation {
                                    location {
                                        id
                                        name
                                    }
                                }
                                lineItems(first: 20) {
                                    edges {
                                        node {
                                            id
                                            totalQuantity
                                            remainingQuantity
                                            variant {
                                                id
                                                sku
                                                product {
                                                    id
                                                    title
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    transactions(first: 20) {
                        id
                        status
                        kind
                        amountSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }
                        createdAt
                        gateway
                        test
                        errorCode
                        parentTransaction {
                            id
                        }
                    }
                    risk {
                        assessments {
                            riskLevel
                            facts {
                                description
                                sentiment
                            }
                            provider {
                                id
                            }
                        }
                        recommendation
                    }
                    customAttributes {
                        key
                        value
                    }
                    metafields(first: 50) {
                        edges {
                            node {
                                namespace
                                key
                                value
                                type
                            }
                        }
                    }
                }
            }
            """
        else:
            query = """
            query getOrderById($id: ID!) {
                order(id: $id) {
                    id
                    name
                    createdAt
                    updatedAt
                    totalPriceSet {
                        shopMoney {
                            amount
                            currencyCode
                        }
                    }
                    currentTotalWeight
                    tags
                    displayFulfillmentStatus
                    customer {
                        id
                        firstName
                        lastName
                        email
                    }
                    shippingAddress {
                        province
                        country
                        city
                        zip
                    }
                    shippingLines(first: 10) {
                        edges {
                            node {
                                title
                                code
                            }
                        }
                    }
                    lineItems(first: 100) {
                        edges {
                            node {
                                id
                                title
                                quantity
                                product {
                                    id
                                    productType
                                    vendor
                                    tags
                                }
                                variant {
                                    id
                                    title
                                    sku
                                    inventoryItem {
                                        measurement {
                                            weight {
                                                value
                                                unit
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    fulfillmentOrders(first: 5) {
                        edges {
                            node {
                                id
                                status
                                assignedLocation {
                                    location {
                                        id
                                        name
                                    }
                                }
                                lineItems(first: 20) {
                                    edges {
                                        node {
                                            id
                                            totalQuantity
                                            remainingQuantity
                                            variant {
                                                id
                                                sku
                                                product {
                                                    id
                                                    title
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            """
        
        variables = {"id": order_id}
        
        try:
            result = await self._make_graphql_request(query, variables)
            order = result.get("data", {}).get("order")
            
            if not order:
                logger.warning(f"Order {order_id} not found in Shopify")
                return None
                
            return order
            
        except Exception as e:
            logger.error(f"Failed to fetch order {order_id}: {str(e)}")
            return None
    
    async def check_inventory_at_location(self, variant_id: str, location_id: str) -> int:
        """Check available inventory for a variant at a specific location"""
        query = """
        query($variantId: ID!, $locationId: ID!) {
            productVariant(id: $variantId) {
                id
                inventoryItem {
                    id
                    inventoryLevel(locationId: $locationId) {
                        id
                        location {
                            id
                        }
                        quantities(names: ["available"]) {
                            name
                            quantity
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            "variantId": variant_id,
            "locationId": location_id
        }
        
        try:
            result = await self._make_graphql_request(query, variables)
            
            product_variant = result["data"]["productVariant"]
            if not product_variant or not product_variant.get("inventoryItem"):
                logger.warning(f"No inventory item found for variant {variant_id}")
                return 0
            
            inventory_level = product_variant["inventoryItem"]["inventoryLevel"]
            
            if not inventory_level:
                logger.warning(f"No inventory level found for variant {variant_id} at location {location_id}")
                return 0
            
            # Look for the "available" quantity
            quantities = inventory_level.get("quantities", [])
            for quantity_obj in quantities:
                if quantity_obj.get("name") == "available":
                    available = quantity_obj.get("quantity", 0)
                    logger.debug(f"Inventory for variant {variant_id} at location {location_id}: {available}")
                    return available or 0
            
            # If no "available" quantity found, assume 0
            logger.warning(f"No 'available' quantity found for variant {variant_id} at location {location_id}")
            return 0
            
        except Exception as e:
            logger.error(f"Failed to check inventory for variant {variant_id} at location {location_id}: {str(e)}")
            return 0
    
    async def get_fulfillment_orders_for_order(self, order_id: str) -> List[Dict]:
        """Get ALL fulfillment orders for a given order ID, paginating through
        every page so callers (e.g. the fraud Hold action) can act on every
        fulfillment location on the order without silently dropping the tail."""
        query = """
        query getFulfillmentOrders($orderId: ID!, $cursor: String) {
            order(id: $orderId) {
                id
                name
                fulfillmentOrders(first: 50, after: $cursor) {
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                    edges {
                        node {
                            id
                            status
                            requestStatus
                            supportedActions {
                                action
                            }
                            assignedLocation {
                                location {
                                    id
                                    name
                                }
                            }
                            lineItems(first: 50) {
                                edges {
                                    node {
                                        id
                                        totalQuantity
                                        variant {
                                            id
                                            title
                                            sku
                                        }
                                    }
                                }
                            }
                            fulfillmentHolds {
                                id
                                reason
                                reasonNotes
                                displayReason
                                handle
                                heldByApp {
                                    id
                                    title
                                }
                                heldByRequestingApp
                            }
                        }
                    }
                }
            }
        }
        """

        fulfillment_orders: List[Dict] = []
        cursor: Optional[str] = None

        try:
            while True:
                result = await self._make_graphql_request(query, {"orderId": order_id, "cursor": cursor})
                order = result.get("data", {}).get("order") or {}

                if not order:
                    logger.warning(f"Order {order_id} not found")
                    return fulfillment_orders

                fo_conn = order.get("fulfillmentOrders") or {}
                for edge in fo_conn.get("edges", []):
                    fulfillment_orders.append(edge["node"])

                page_info = fo_conn.get("pageInfo") or {}
                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")
                if not cursor:
                    break

            logger.debug(
                f"Fetched {len(fulfillment_orders)} fulfillment order(s) for order {order_id}"
            )
            return fulfillment_orders

        except Exception as e:
            logger.error(f"Failed to get fulfillment orders for order {order_id}: {str(e)}")
            return fulfillment_orders
    
    async def apply_fulfillment_hold(self, fulfillment_order_id: str, reason: str, reason_notes: str = "", notify_merchant: bool = True) -> Dict:
        """Apply a hold to a fulfillment order"""
        mutation = """
        mutation fulfillmentOrderHold($id: ID!, $fulfillmentHold: FulfillmentOrderHoldInput!) {
            fulfillmentOrderHold(id: $id, fulfillmentHold: $fulfillmentHold) {
                fulfillmentOrder {
                    id
                    status
                    fulfillmentHolds {
                        id
                        reason
                        reasonNotes
                        displayReason
                        handle
                        heldByApp {
                            id
                            title
                        }
                        heldByRequestingApp
                    }
                }
                fulfillmentHold {
                    id
                    reason
                    reasonNotes
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "id": fulfillment_order_id,
            "fulfillmentHold": {
                "reason": reason,
                "reasonNotes": reason_notes,
                "notifyMerchant": notify_merchant
            }
        }
        
        try:
            result = await self._make_graphql_request(mutation, variables)
            
            hold_result = result["data"]["fulfillmentOrderHold"]
            
            if hold_result["userErrors"]:
                logger.error(f"Error applying fulfillment hold: {hold_result['userErrors']}")
                return {
                    "success": False,
                    "errors": hold_result["userErrors"],
                    "fulfillment_order": None,
                    "hold": None
                }
            
            return {
                "success": True,
                "errors": [],
                "fulfillment_order": hold_result["fulfillmentOrder"],
                "hold": hold_result["fulfillmentHold"]
            }
            
        except Exception as e:
            logger.error(f"Failed to apply fulfillment hold to {fulfillment_order_id}: {str(e)}")
            return {
                "success": False,
                "errors": [{"message": str(e)}],
                "fulfillment_order": None,
                "hold": None
            }
    
    async def release_fulfillment_hold(self, fulfillment_order_id: str, hold_ids: List[str] = None) -> Dict:
        """Release a hold from a fulfillment order"""
        mutation = """
        mutation fulfillmentOrderReleaseHold($id: ID!, $holdIds: [ID!]) {
            fulfillmentOrderReleaseHold(id: $id, holdIds: $holdIds) {
                fulfillmentOrder {
                    id
                    status
                    fulfillmentHolds {
                        id
                        reason
                        reasonNotes
                        displayReason
                        handle
                        heldByApp {
                            id
                            title
                        }
                        heldByRequestingApp
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "id": fulfillment_order_id
        }
        
        if hold_ids:
            variables["holdIds"] = hold_ids
        
        try:
            result = await self._make_graphql_request(mutation, variables)
            
            release_result = result["data"]["fulfillmentOrderReleaseHold"]
            
            if release_result["userErrors"]:
                logger.error(f"Error releasing fulfillment hold: {release_result['userErrors']}")
                return {
                    "success": False,
                    "errors": release_result["userErrors"],
                    "fulfillment_order": None
                }
            
            return {
                "success": True,
                "errors": [],
                "fulfillment_order": release_result["fulfillmentOrder"]
            }
            
        except Exception as e:
            logger.error(f"Failed to release fulfillment hold from {fulfillment_order_id}: {str(e)}")
            return {
                "success": False,
                "errors": [{"message": str(e)}],
                "fulfillment_order": None
            }
    
    async def get_order_fraud_data(self, order_name: str) -> Dict[str, Any] | None:
        """Get comprehensive fraud detection data for an order - MINIMAL WORKING VERSION"""
        query = """
        query getOrderFraudData($query: String!) {
            orders(first: 1, query: $query) {
                edges {
                    node {
                        id
                        name
                        createdAt
                        totalPriceSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }
                        note
                        email
                        displayFinancialStatus
                        displayFulfillmentStatus
                        cancelledAt
                        
                        billingAddress {
                            firstName
                            lastName
                            address1
                            address2
                            city
                            province
                            country
                            zip
                            phone
                        }
                        shippingAddress {
                            firstName
                            lastName
                            address1
                            address2
                            city
                            province
                            country
                            zip
                            phone
                        }
                        
                        transactions(first: 20) {
                            id
                            status
                            kind
                            amountSet {
                                shopMoney {
                                    amount
                                    currencyCode
                                }
                            }
                            createdAt
                            gateway
                            test
                        }
                        
                        customer {
                            id
                            email
                            firstName
                            lastName
                            numberOfOrders
                            createdAt
                            amountSpent {
                                amount
                                currencyCode
                            }
                            orders(first: 10, sortKey: CREATED_AT, reverse: true) {
                                edges {
                                    node {
                                        id
                                        name
                                        createdAt
                                        totalPriceSet {
                                            shopMoney {
                                                amount
                                                currencyCode
                                            }
                                        }
                                        displayFulfillmentStatus
                                        fulfillments(first: 5) {
                                            id
                                            status
                                            displayStatus
                                            deliveredAt
                                            inTransitAt
                                            estimatedDeliveryAt
                                            createdAt
                                            updatedAt
                                            trackingInfo(first: 3) {
                                                company
                                                number
                                                url
                                            }
                                            events(first: 20, reverse: true, sortKey: HAPPENED_AT) {
                                                edges {
                                                    node {
                                                        id
                                                        status
                                                        happenedAt
                                                        message
                                                        address1
                                                        city
                                                        province
                                                        country
                                                        zip
                                                        latitude
                                                        longitude
                                                        estimatedDeliveryAt
                                                        createdAt
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        
                        lineItems(first: 20) {
                            edges {
                                node {
                                    id
                                    title
                                    quantity
                                    product {
                                        id
                                        title
                                        productType
                                        vendor
                                        tags
                                    }
                                    variant {
                                        id
                                        title
                                        sku
                                    }
                                }
                            }
                        }
                        
                        fulfillments(first: 10) {
                            id
                            status
                            displayStatus
                            deliveredAt
                            inTransitAt
                            estimatedDeliveryAt
                            createdAt
                            updatedAt
                            trackingInfo(first: 5) {
                                company
                                number
                                url
                            }
                            events(first: 30, reverse: true, sortKey: HAPPENED_AT) {
                                edges {
                                    node {
                                        id
                                        status
                                        happenedAt
                                        message
                                        address1
                                        city
                                        province
                                        country
                                        zip
                                        latitude
                                        longitude
                                        estimatedDeliveryAt
                                        createdAt
                                    }
                                }
                            }
                        }
                        
                        risk {
                            assessments {
                                riskLevel
                                facts {
                                    description
                                    sentiment
                                }
                                provider {
                                    id
                                }
                            }
                            recommendation
                        }
                        
                        customAttributes {
                            key
                            value
                        }
                        metafields(first: 50) {
                            edges {
                                node {
                                    namespace
                                    key
                                    value
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {"query": f"name:{order_name}"}
        
        try:
            result = await self._make_graphql_request(query, variables)
            
            if not result.get("data", {}).get("orders", {}).get("edges"):
                logger.warning(f"No order found with name {order_name}")
                return None
                
            order_data = result["data"]["orders"]["edges"][0]["node"]
            
            # Structure fraud data for service consumption
            fraud_data = {
                "order_info": {
                    "id": order_data.get("id"),
                    "name": order_data.get("name"),
                    "created_at": order_data.get("createdAt"),
                    "total_price": order_data.get("totalPriceSet", {}).get("shopMoney", {}).get("amount"),
                    "currency": order_data.get("totalPriceSet", {}).get("shopMoney", {}).get("currencyCode"),
                    "email": order_data.get("email"),
                    "note": order_data.get("note"),
                    "financial_status": order_data.get("displayFinancialStatus"),
                    "fulfillment_status": order_data.get("displayFulfillmentStatus")
                },
                "billing_address": order_data.get("billingAddress"),
                "shipping_address": order_data.get("shippingAddress"),
                "transactions": order_data.get("transactions", []),
                "customer": order_data.get("customer"),
                "line_items": [item["node"] for item in order_data.get("lineItems", {}).get("edges", [])],
                "fulfillments": order_data.get("fulfillments", []),
                "custom_attributes": order_data.get("customAttributes", []),
                "metafields": [field["node"] for field in order_data.get("metafields", {}).get("edges", [])],
                "risk": order_data.get("risk"),
                # Include raw order data for backwards compatibility and additional fields
                "raw_order_data": order_data,
                # Also include these fields at root level for easier access
                "displayFulfillmentStatus": order_data.get("displayFulfillmentStatus"),
                "displayFinancialStatus": order_data.get("displayFinancialStatus"),
                "cancelledAt": order_data.get("cancelledAt")
            }
            
            logger.info(f"Successfully retrieved minimal fraud data for order {order_name}")
            return fraud_data
            
        except Exception as e:
            logger.error(f"Failed to fetch fraud data for order {order_name}: {str(e)}")
            return None
    
    async def search_duplicate_orders(
        self, 
        email: str = None, 
        billing_address: Dict = None, 
        shipping_address: Dict = None,
        phone: str = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search for potential duplicate orders by email and address patterns"""
        
        # Build query based on available parameters
        query_parts = []
        
        if email:
            query_parts.append(f"email:{email}")
        
        if phone:
            # Clean phone number for search
            clean_phone = ''.join(filter(str.isdigit, phone))
            if len(clean_phone) >= 10:
                query_parts.append(f"phone:*{clean_phone[-10:]}*")
        
        # If we have address information, we'll search by customer and then filter
        if not query_parts:
            logger.warning("No search criteria provided for duplicate order search")
            return []
        
        search_query = " OR ".join(query_parts)
        
        query = """
        query searchDuplicateOrders($query: String!, $first: Int!) {
            orders(first: $first, query: $query, sortKey: CREATED_AT, reverse: true) {
                edges {
                    node {
                        id
                        name
                        createdAt
                        totalPriceSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }
                        email
                        phone
                        displayFinancialStatus
                        displayFulfillmentStatus
                        tags
                        billingAddress {
                            firstName
                            lastName
                            address1
                            address2
                            city
                            province
                            country
                            zip
                            phone
                        }
                        shippingAddress {
                            firstName
                            lastName
                            address1
                            address2
                            city
                            province
                            country
                            zip
                            phone
                        }
                        customer {
                            id
                            firstName
                            lastName
                            email
                            phone
                            numberOfOrders
                            amountSpent {
                                amount
                                currencyCode
                            }
                            addresses {
                                id
                                firstName
                                lastName
                                company
                                address1
                                address2
                                city
                                province
                                country
                                zip
                                phone
                            }
                        }
                        lineItems(first: 20) {
                            edges {
                                node {
                                    title
                                    quantity
                                    variant {
                                        sku
                                        product {
                                            title
                                            productType
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            "query": search_query,
            "first": limit
        }
        
        try:
            result = await self._make_graphql_request(query, variables)
            
            orders = result.get("data", {}).get("orders", {}).get("edges", [])
            
            # Process and structure the results
            duplicate_candidates = []
            
            for order_edge in orders:
                order = order_edge["node"]
                
                # Calculate similarity scores based on address matching
                similarity_score = 0.0
                matched_criteria = []
                
                if email and order.get("email") == email:
                    similarity_score += 30
                    matched_criteria.append("email")
                
                if phone and order.get("phone"):
                    order_phone_clean = ''.join(filter(str.isdigit, order["phone"]))
                    input_phone_clean = ''.join(filter(str.isdigit, phone))
                    if order_phone_clean and input_phone_clean and order_phone_clean[-10:] == input_phone_clean[-10:]:
                        similarity_score += 25
                        matched_criteria.append("phone")
                
                # Address similarity checking
                if billing_address and order.get("billingAddress"):
                    addr_score = self._calculate_address_similarity(billing_address, order["billingAddress"])
                    similarity_score += addr_score * 25
                    if addr_score > 0.7:
                        matched_criteria.append("billing_address")
                
                if shipping_address and order.get("shippingAddress"):
                    addr_score = self._calculate_address_similarity(shipping_address, order["shippingAddress"])
                    similarity_score += addr_score * 20
                    if addr_score > 0.7:
                        matched_criteria.append("shipping_address")
                
                duplicate_candidates.append({
                    "order": {
                        "id": order["id"],
                        "name": order["name"],
                        "created_at": order["createdAt"],
                        "total_price": float(order["totalPriceSet"]["shopMoney"]["amount"]),
                        "currency": order["totalPriceSet"]["shopMoney"]["currencyCode"],
                        "email": order.get("email"),
                        "phone": order.get("phone"),
                        "financial_status": order.get("displayFinancialStatus"),
                        "fulfillment_status": order.get("displayFulfillmentStatus"),
                        "tags": order.get("tags", [])
                    },
                    "customer": order.get("customer"),
                    "billing_address": order.get("billingAddress"),
                    "shipping_address": order.get("shippingAddress"),
                    "line_items": [item["node"] for item in order.get("lineItems", {}).get("edges", [])],
                    "similarity_score": similarity_score,
                    "matched_criteria": matched_criteria
                })
            
            # Sort by similarity score (highest first)
            duplicate_candidates.sort(key=lambda x: x["similarity_score"], reverse=True)
            
            logger.info(f"Found {len(duplicate_candidates)} potential duplicate orders")
            return duplicate_candidates
            
        except Exception as e:
            logger.error(f"Failed to search for duplicate orders: {str(e)}")
            return []
    
    def _calculate_address_similarity(self, addr1: Dict, addr2: Dict) -> float:
        """Calculate similarity score between two addresses (0.0 to 1.0)"""
        if not addr1 or not addr2:
            return 0.0
        
        score = 0.0
        total_fields = 0
        
        # Compare key address fields
        fields_to_compare = [
            ("address1", 0.3),
            ("city", 0.2),
            ("province", 0.15),
            ("country", 0.15),
            ("zip", 0.2)
        ]
        
        for field, weight in fields_to_compare:
            val1 = addr1.get(field, "").lower().strip()
            val2 = addr2.get(field, "").lower().strip()
            
            if val1 and val2:
                if val1 == val2:
                    score += weight
                elif field == "zip":
                    # For ZIP codes, check if they start the same (postal code areas)
                    if len(val1) >= 3 and len(val2) >= 3 and val1[:3] == val2[:3]:
                        score += weight * 0.7
                elif field == "address1":
                    # For street addresses, check for partial matches
                    if val1 in val2 or val2 in val1:
                        score += weight * 0.8
            
            total_fields += weight
        
        return score / total_fields if total_fields > 0 else 0.0
    
    # ========================================
    # NULL-SAFE FRAUD DATA EXTRACTION METHODS
    # ========================================
    
    def extract_fraud_risk_level(self, order_data: Dict[str, Any]) -> Optional[str]:
        """Extract Shopify's fraud risk level with null-safe handling.
        
        Args:
            order_data: Order data from Shopify GraphQL response
            
        Returns:
            Risk level (LOW, MEDIUM, HIGH) or None if not available
        """
        try:
            risk_data = order_data.get('risk')
            if not risk_data or not isinstance(risk_data, dict):
                logger.debug("No risk data found in order")
                return None
            
            assessments = risk_data.get('assessments', [])
            if not assessments or not isinstance(assessments, list):
                logger.debug("No risk assessments found")
                return None
            
            # Get the first assessment (primary fraud assessment)
            assessment = assessments[0]
            if not isinstance(assessment, dict):
                logger.warning("Invalid assessment format")
                return None
            
            risk_level = assessment.get('riskLevel')
            if not risk_level:
                logger.debug("No risk level in assessment")
                return None
            
            # Normalize and validate risk level
            risk_level = str(risk_level).upper().strip()
            valid_levels = ['LOW', 'MEDIUM', 'HIGH']
            
            if risk_level in valid_levels:
                logger.info(f"Extracted fraud risk level: {risk_level}")
                return risk_level
            else:
                logger.warning(f"Unknown risk level: {risk_level}")
                return risk_level  # Return as-is in case Shopify adds new levels
                
        except Exception as e:
            logger.error(f"Error extracting fraud risk level: {str(e)}")
            return None
    
    def extract_fraud_facts(self, order_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Extract fraud assessment facts with null-safe handling.
        
        Args:
            order_data: Order data from Shopify GraphQL response
            
        Returns:
            List of fraud facts with description and sentiment
        """
        try:
            risk_data = order_data.get('risk')
            if not risk_data or not isinstance(risk_data, dict):
                return []
            
            assessments = risk_data.get('assessments', [])
            if not assessments or not isinstance(assessments, list):
                return []
            
            all_facts = []
            for assessment in assessments:
                if not isinstance(assessment, dict):
                    continue
                
                facts = assessment.get('facts', [])
                if not isinstance(facts, list):
                    continue
                
                for fact in facts:
                    if not isinstance(fact, dict):
                        continue
                    
                    description = fact.get('description')
                    sentiment = fact.get('sentiment')
                    
                    if description:  # Only include facts with descriptions
                        all_facts.append({
                            'description': str(description).strip(),
                            'sentiment': str(sentiment).strip() if sentiment else None
                        })
            
            logger.debug(f"Extracted {len(all_facts)} fraud facts")
            return all_facts
            
        except Exception as e:
            logger.error(f"Error extracting fraud facts: {str(e)}")
            return []
    
    def extract_fraud_recommendation(self, order_data: Dict[str, Any]) -> Optional[str]:
        """Extract Shopify's fraud recommendation with null-safe handling.
        
        Args:
            order_data: Order data from Shopify GraphQL response
            
        Returns:
            Fraud recommendation string or None if not available
        """
        try:
            risk_data = order_data.get('risk')
            if not risk_data or not isinstance(risk_data, dict):
                return None
            
            recommendation = risk_data.get('recommendation')
            if not recommendation:
                return None
            
            return str(recommendation).strip()
            
        except Exception as e:
            logger.error(f"Error extracting fraud recommendation: {str(e)}")
            return None
    
    def extract_transaction_analysis(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract transaction analysis data with null-safe handling.
        
        Args:
            order_data: Order data from Shopify GraphQL response
            
        Returns:
            Dictionary with transaction analysis data
        """
        try:
            transactions = order_data.get('transactions', [])
            if not isinstance(transactions, list):
                transactions = []
            
            analysis = {
                'total_attempts': len(transactions),
                'failed_attempts': 0,
                'test_transactions': 0,
                'unique_gateways': set(),
                'transaction_types': set(),
                'error_codes': [],
                'has_refunds': False,
                'has_chargebacks': False
            }
            
            for transaction in transactions:
                if not isinstance(transaction, dict):
                    continue
                
                # Count transaction types
                kind = transaction.get('kind', '').upper()
                if kind:
                    analysis['transaction_types'].add(kind)
                
                # Check for failed transactions
                status = transaction.get('status', '').upper()
                if status in ['FAILURE', 'ERROR', 'PENDING']:
                    analysis['failed_attempts'] += 1
                
                # Check for test transactions
                if transaction.get('test') is True:
                    analysis['test_transactions'] += 1
                
                # Track gateways
                gateway = transaction.get('gateway')
                if gateway:
                    analysis['unique_gateways'].add(str(gateway))
                
                # Track error codes
                error_code = transaction.get('errorCode')
                if error_code:
                    analysis['error_codes'].append(str(error_code))
                
                # Check for refunds and chargebacks
                if kind == 'REFUND':
                    analysis['has_refunds'] = True
                elif kind == 'CHARGEBACK':
                    analysis['has_chargebacks'] = True
            
            # Convert sets to lists for JSON serialization
            analysis['unique_gateways'] = list(analysis['unique_gateways'])
            analysis['transaction_types'] = list(analysis['transaction_types'])
            
            logger.debug(f"Transaction analysis: {analysis['total_attempts']} attempts, {analysis['failed_attempts']} failed")
            return analysis
            
        except Exception as e:
            logger.error(f"Error extracting transaction analysis: {str(e)}")
            return {
                'total_attempts': 0,
                'failed_attempts': 0,
                'test_transactions': 0,
                'unique_gateways': [],
                'transaction_types': [],
                'error_codes': [],
                'has_refunds': False,
                'has_chargebacks': False
            }
    
    def extract_customer_fraud_indicators(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract customer-based fraud indicators with null-safe handling.
        
        Args:
            order_data: Order data from Shopify GraphQL response
            
        Returns:
            Dictionary with customer fraud indicators
        """
        try:
            customer = order_data.get('customer', {})
            if not isinstance(customer, dict):
                customer = {}
            
            indicators = {
                'is_first_time_customer': True,
                'total_orders': 0,
                'customer_lifetime_value': 0.0,
                'account_age_days': None,
                'email_domain': None,
                'phone_country_code': None,
                'has_phone': False,
                'name_mismatch_with_address': False
            }
            
            # Check if first-time customer
            number_of_orders = customer.get('numberOfOrders', 0)
            if isinstance(number_of_orders, str):
                try:
                    number_of_orders = int(number_of_orders)
                except ValueError:
                    number_of_orders = 0
            
            indicators['total_orders'] = number_of_orders
            indicators['is_first_time_customer'] = number_of_orders <= 1
            
            # Calculate customer lifetime value
            amount_spent = customer.get('amountSpent', {})
            if isinstance(amount_spent, dict):
                amount = amount_spent.get('amount')
                if amount:
                    try:
                        indicators['customer_lifetime_value'] = float(amount)
                    except (ValueError, TypeError):
                        pass
            
            # Calculate account age
            created_at = customer.get('createdAt')
            if created_at:
                try:
                    from datetime import datetime, timezone
                    customer_created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    account_age = datetime.now(timezone.utc) - customer_created
                    indicators['account_age_days'] = account_age.days
                except Exception:
                    pass
            
            # Extract email domain
            email = customer.get('email') or order_data.get('email')
            if email and '@' in str(email):
                try:
                    domain = str(email).split('@')[1].lower()
                    indicators['email_domain'] = domain
                except IndexError:
                    pass
            
            # Check phone presence and extract country code
            phone = customer.get('phone') or order_data.get('phone')
            if phone:
                phone_str = str(phone).strip()
                indicators['has_phone'] = bool(phone_str)
                
                # Simple country code extraction for common formats
                if phone_str.startswith('+'):
                    # Extract first 1-3 digits after +
                    digits = ''.join(filter(str.isdigit, phone_str))
                    if len(digits) >= 1:
                        indicators['phone_country_code'] = digits[:3]
            
            # Check for name mismatches between customer and billing address
            customer_first = customer.get('firstName', '').strip().lower()
            customer_last = customer.get('lastName', '').strip().lower()
            
            billing_address = order_data.get('billingAddress', {})
            if isinstance(billing_address, dict):
                billing_first = billing_address.get('firstName', '').strip().lower()
                billing_last = billing_address.get('lastName', '').strip().lower()
                
                if customer_first and billing_first and customer_first != billing_first:
                    indicators['name_mismatch_with_address'] = True
                elif customer_last and billing_last and customer_last != billing_last:
                    indicators['name_mismatch_with_address'] = True
            
            logger.debug(f"Customer fraud indicators: first_time={indicators['is_first_time_customer']}, "
                        f"orders={indicators['total_orders']}, clv=${indicators['customer_lifetime_value']}")
            return indicators
            
        except Exception as e:
            logger.error(f"Error extracting customer fraud indicators: {str(e)}")
            return {
                'is_first_time_customer': True,
                'total_orders': 0,
                'customer_lifetime_value': 0.0,
                'account_age_days': None,
                'email_domain': None,
                'phone_country_code': None,
                'has_phone': False,
                'name_mismatch_with_address': False
            }
    
    def extract_address_fraud_indicators(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract address-based fraud indicators with null-safe handling.
        
        Args:
            order_data: Order data from Shopify GraphQL response
            
        Returns:
            Dictionary with address fraud indicators
        """
        try:
            billing_address = order_data.get('billingAddress', {})
            shipping_address = order_data.get('shippingAddress', {})
            
            if not isinstance(billing_address, dict):
                billing_address = {}
            if not isinstance(shipping_address, dict):
                shipping_address = {}
            
            indicators = {
                'billing_shipping_match': False,
                'billing_outside_us': False,
                'shipping_outside_us': False,
                'po_box_delivery': False,
                'international_shipping': False,
                'billing_country': None,
                'shipping_country': None,
                'address_completeness_score': 0.0
            }
            
            # Check billing/shipping address match
            if billing_address and shipping_address:
                match_score = self._calculate_address_similarity(billing_address, shipping_address)
                indicators['billing_shipping_match'] = match_score > 0.8
            
            # Check countries
            billing_country = billing_address.get('country', '').upper()
            shipping_country = shipping_address.get('country', '').upper()
            
            indicators['billing_country'] = billing_country if billing_country else None
            indicators['shipping_country'] = shipping_country if shipping_country else None
            
            # Check if addresses are outside US
            us_indicators = ['US', 'USA', 'UNITED STATES', 'UNITED STATES OF AMERICA']
            indicators['billing_outside_us'] = billing_country not in us_indicators if billing_country else False
            indicators['shipping_outside_us'] = shipping_country not in us_indicators if shipping_country else False
            indicators['international_shipping'] = indicators['shipping_outside_us']
            
            # Check for PO Box delivery
            shipping_address1 = shipping_address.get('address1', '').upper()
            po_box_indicators = ['P.O. BOX', 'PO BOX', 'P O BOX', 'POST OFFICE BOX']
            indicators['po_box_delivery'] = any(indicator in shipping_address1 for indicator in po_box_indicators)
            
            # Calculate address completeness score
            required_fields = ['address1', 'city', 'province', 'country', 'zip']
            complete_fields = sum(1 for field in required_fields if shipping_address.get(field, '').strip())
            indicators['address_completeness_score'] = complete_fields / len(required_fields)
            
            logger.debug(f"Address fraud indicators: billing_outside_us={indicators['billing_outside_us']}, "
                        f"shipping_outside_us={indicators['shipping_outside_us']}, po_box={indicators['po_box_delivery']}")
            return indicators
            
        except Exception as e:
            logger.error(f"Error extracting address fraud indicators: {str(e)}")
            return {
                'billing_shipping_match': False,
                'billing_outside_us': False,
                'shipping_outside_us': False,
                'po_box_delivery': False,
                'international_shipping': False,
                'billing_country': None,
                'shipping_country': None,
                'address_completeness_score': 0.0
            }
    
    def extract_order_fraud_indicators(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract order-specific fraud indicators with null-safe handling.
        
        Args:
            order_data: Order data from Shopify GraphQL response
            
        Returns:
            Dictionary with order fraud indicators
        """
        try:
            indicators = {
                'order_total': 0.0,
                'currency': None,
                'unusually_high_value': False,
                'has_notes': False,
                'suspicious_notes': False,
                'rush_order': False,
                'weekend_order': False,
                'late_night_order': False,
                'financial_status': None,
                'fulfillment_status': None
            }
            
            # Extract order total
            total_price_set = order_data.get('totalPriceSet', {})
            if isinstance(total_price_set, dict):
                shop_money = total_price_set.get('shopMoney', {})
                if isinstance(shop_money, dict):
                    amount = shop_money.get('amount')
                    currency = shop_money.get('currencyCode')
                    
                    if amount:
                        try:
                            indicators['order_total'] = float(amount)
                        except (ValueError, TypeError):
                            pass
                    
                    if currency:
                        indicators['currency'] = str(currency)
            
            # Check for unusually high order value (threshold can be configurable)
            if indicators['order_total'] > 1000.0:  # $1000+ orders
                indicators['unusually_high_value'] = True
            
            # Check for notes and suspicious content
            note = order_data.get('note', '')
            if note and str(note).strip():
                indicators['has_notes'] = True
                
                # Check for suspicious note patterns
                note_lower = str(note).lower()
                suspicious_keywords = [
                    'urgent', 'rush', 'asap', 'emergency', 'fast', 'quick',
                    'gift card', 'bitcoin', 'cryptocurrency', 'wire transfer',
                    'test', 'fake', 'sample'
                ]
                indicators['suspicious_notes'] = any(keyword in note_lower for keyword in suspicious_keywords)
                indicators['rush_order'] = any(keyword in note_lower for keyword in ['urgent', 'rush', 'asap', 'emergency'])
            
            # Check order timing
            created_at = order_data.get('createdAt')
            if created_at:
                try:
                    from datetime import datetime
                    order_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    
                    # Check if weekend order (Saturday=5, Sunday=6)
                    indicators['weekend_order'] = order_time.weekday() in [5, 6]
                    
                    # Check if late night order (between 10 PM and 6 AM)
                    hour = order_time.hour
                    indicators['late_night_order'] = hour >= 22 or hour < 6
                    
                except Exception:
                    pass
            
            # Extract status fields
            indicators['financial_status'] = order_data.get('displayFinancialStatus')
            indicators['fulfillment_status'] = order_data.get('displayFulfillmentStatus')
            
            logger.debug(f"Order fraud indicators: total=${indicators['order_total']}, "
                        f"high_value={indicators['unusually_high_value']}, weekend={indicators['weekend_order']}")
            return indicators
            
        except Exception as e:
            logger.error(f"Error extracting order fraud indicators: {str(e)}")
            return {
                'order_total': 0.0,
                'currency': None,
                'unusually_high_value': False,
                'has_notes': False,
                'suspicious_notes': False,
                'rush_order': False,
                'weekend_order': False,
                'late_night_order': False,
                'financial_status': None,
                'fulfillment_status': None
            }
    
    def extract_comprehensive_fraud_data(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract all fraud-related data with comprehensive null-safe handling.
        
        This is the main method that combines all fraud indicators into a single
        comprehensive analysis. It ensures that if any individual extraction fails,
        the overall process continues with default values.
        
        Args:
            order_data: Order data from Shopify GraphQL response
            
        Returns:
            Dictionary with comprehensive fraud analysis data
        """
        try:
            logger.info("Starting comprehensive fraud data extraction")
            
            fraud_data = {
                'extraction_timestamp': None,
                'extraction_success': True,
                'extraction_errors': []
            }
            
            # Add timestamp
            try:
                from datetime import datetime, timezone
                fraud_data['extraction_timestamp'] = datetime.now(timezone.utc).isoformat()
            except Exception as e:
                fraud_data['extraction_errors'].append(f"Timestamp error: {str(e)}")
            
            # Extract Shopify fraud assessment
            try:
                fraud_data['shopify_risk_level'] = self.extract_fraud_risk_level(order_data)
                fraud_data['fraud_facts'] = self.extract_fraud_facts(order_data)
                fraud_data['fraud_recommendation'] = self.extract_fraud_recommendation(order_data)
            except Exception as e:
                logger.error(f"Error extracting Shopify fraud assessment: {str(e)}")
                fraud_data['extraction_errors'].append(f"Shopify assessment error: {str(e)}")
                fraud_data['shopify_risk_level'] = None
                fraud_data['fraud_facts'] = []
                fraud_data['fraud_recommendation'] = None
            
            # Extract transaction analysis
            try:
                fraud_data['transaction_analysis'] = self.extract_transaction_analysis(order_data)
            except Exception as e:
                logger.error(f"Error extracting transaction analysis: {str(e)}")
                fraud_data['extraction_errors'].append(f"Transaction analysis error: {str(e)}")
                fraud_data['transaction_analysis'] = {}
            
            # Extract customer indicators
            try:
                fraud_data['customer_indicators'] = self.extract_customer_fraud_indicators(order_data)
            except Exception as e:
                logger.error(f"Error extracting customer indicators: {str(e)}")
                fraud_data['extraction_errors'].append(f"Customer indicators error: {str(e)}")
                fraud_data['customer_indicators'] = {}
            
            # Extract address indicators
            try:
                fraud_data['address_indicators'] = self.extract_address_fraud_indicators(order_data)
            except Exception as e:
                logger.error(f"Error extracting address indicators: {str(e)}")
                fraud_data['extraction_errors'].append(f"Address indicators error: {str(e)}")
                fraud_data['address_indicators'] = {}
            
            # Extract order indicators
            try:
                fraud_data['order_indicators'] = self.extract_order_fraud_indicators(order_data)
            except Exception as e:
                logger.error(f"Error extracting order indicators: {str(e)}")
                fraud_data['extraction_errors'].append(f"Order indicators error: {str(e)}")
                fraud_data['order_indicators'] = {}
            
            # Set overall success status
            fraud_data['extraction_success'] = len(fraud_data['extraction_errors']) == 0
            
            logger.info(f"Fraud data extraction completed. Success: {fraud_data['extraction_success']}, "
                       f"Errors: {len(fraud_data['extraction_errors'])}")
            
            return fraud_data
            
        except Exception as e:
            logger.error(f"Critical error in comprehensive fraud data extraction: {str(e)}")
            return {
                'extraction_timestamp': None,
                'extraction_success': False,
                'extraction_errors': [f"Critical error: {str(e)}"],
                'shopify_risk_level': None,
                'fraud_facts': [],
                'fraud_recommendation': None,
                'transaction_analysis': {},
                'customer_indicators': {},
                'address_indicators': {},
                'order_indicators': {}
            }
    
    async def get_order_fraud_data_enhanced(self, order_name: str) -> Dict[str, Any] | None:
        """Get comprehensive fraud detection data for an order using enhanced extraction methods.
        
        This method replaces the original get_order_fraud_data with improved null-safe
        extraction and comprehensive fraud analysis capabilities.
        
        Args:
            order_name: Name of the order to analyze
            
        Returns:
            Dictionary with comprehensive fraud data or None if order not found
        """
        try:
            logger.info(f"Starting enhanced fraud data extraction for order {order_name}")
            
            # Use the enhanced get_orders method to fetch fraud data
            result = await self.get_orders(limit=1, include_fraud_data=True)
            
            # Find the specific order by name
            orders = result.get("edges", [])
            target_order = None
            
            for order_edge in orders:
                order = order_edge["node"]
                if order.get("name") == order_name:
                    target_order = order
                    break
            
            if not target_order:
                # Fallback: search using the existing method
                logger.info(f"Order {order_name} not found in recent orders, using direct search")
                original_result = await self.get_order_fraud_data(order_name)
                if original_result:
                    target_order = original_result
                else:
                    logger.warning(f"Order {order_name} not found")
                    return None
            
            # Extract comprehensive fraud data using new methods
            fraud_data = self.extract_comprehensive_fraud_data(target_order)
            
            # Add original order data for compatibility
            fraud_data['raw_order_data'] = target_order
            
            # Structure for compatibility with existing fraud service
            fraud_data['order_info'] = {
                "id": target_order.get("id"),
                "name": target_order.get("name"),
                "created_at": target_order.get("createdAt"),
                "total_price": target_order.get("totalPriceSet", {}).get("shopMoney", {}).get("amount"),
                "currency": target_order.get("totalPriceSet", {}).get("shopMoney", {}).get("currencyCode"),
                "email": target_order.get("email"),
                "note": target_order.get("note"),
                "financial_status": target_order.get("displayFinancialStatus"),
                "fulfillment_status": target_order.get("displayFulfillmentStatus")
            }
            
            fraud_data['billing_address'] = target_order.get("billingAddress")
            fraud_data['shipping_address'] = target_order.get("shippingAddress")
            fraud_data['transactions'] = target_order.get("transactions", [])
            fraud_data['customer'] = target_order.get("customer")
            fraud_data['line_items'] = [item["node"] for item in target_order.get("lineItems", {}).get("edges", [])]
            fraud_data['custom_attributes'] = target_order.get("customAttributes", [])
            fraud_data['metafields'] = [field["node"] for field in target_order.get("metafields", {}).get("edges", [])]
            fraud_data['risk'] = target_order.get("risk")
            
            logger.info(f"Enhanced fraud data extraction completed for order {order_name}")
            return fraud_data
            
        except Exception as e:
            logger.error(f"Failed to extract enhanced fraud data for order {order_name}: {str(e)}")
            return None
    
    def validate_fraud_data_completeness(self, fraud_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate completeness of extracted fraud data and provide a quality score.
        
        Args:
            fraud_data: Fraud data dictionary from extract_comprehensive_fraud_data
            
        Returns:
            Dictionary with validation results and quality metrics
        """
        try:
            validation = {
                'overall_quality_score': 0.0,
                'completeness_score': 0.0,
                'data_quality_issues': [],
                'missing_fields': [],
                'field_scores': {}
            }
            
            # Define critical fields and their weights
            critical_fields = {
                'shopify_risk_level': 20,  # Shopify's assessment is critical
                'customer_indicators': 15,
                'transaction_analysis': 15,
                'address_indicators': 15,
                'order_indicators': 10,
                'fraud_facts': 10,
                'fraud_recommendation': 5,
                'extraction_success': 10
            }
            
            total_possible_score = sum(critical_fields.values())
            actual_score = 0
            
            # Score each field
            for field, weight in critical_fields.items():
                field_value = fraud_data.get(field)
                field_score = 0
                
                if field == 'extraction_success':
                    field_score = weight if fraud_data.get('extraction_success', False) else 0
                elif field == 'shopify_risk_level':
                    field_score = weight if field_value else 0
                elif field == 'fraud_facts':
                    # Score based on number of facts
                    facts_count = len(field_value) if isinstance(field_value, list) else 0
                    field_score = min(weight, facts_count * 2)  # Up to 5 facts = full score
                elif field in ['customer_indicators', 'transaction_analysis', 'address_indicators', 'order_indicators']:
                    # Score based on completeness of nested data
                    if isinstance(field_value, dict) and field_value:
                        non_null_fields = sum(1 for v in field_value.values() if v is not None)
                        total_fields = len(field_value)
                        if total_fields > 0:
                            field_score = (non_null_fields / total_fields) * weight
                    else:
                        validation['missing_fields'].append(field)
                else:
                    field_score = weight if field_value else 0
                
                validation['field_scores'][field] = {
                    'score': field_score,
                    'max_score': weight,
                    'percentage': (field_score / weight * 100) if weight > 0 else 0
                }
                actual_score += field_score
                
                if field_score == 0:
                    validation['missing_fields'].append(field)
            
            # Calculate overall scores
            validation['completeness_score'] = (actual_score / total_possible_score * 100) if total_possible_score > 0 else 0
            
            # Check for data quality issues
            extraction_errors = fraud_data.get('extraction_errors', [])
            if extraction_errors:
                validation['data_quality_issues'].extend([f"Extraction error: {error}" for error in extraction_errors])
            
            # Adjust quality score based on issues
            quality_penalty = len(validation['data_quality_issues']) * 5  # 5% penalty per issue
            validation['overall_quality_score'] = max(0, validation['completeness_score'] - quality_penalty)
            
            # Categorize quality
            if validation['overall_quality_score'] >= 80:
                validation['quality_category'] = 'HIGH'
            elif validation['overall_quality_score'] >= 60:
                validation['quality_category'] = 'MEDIUM'
            else:
                validation['quality_category'] = 'LOW'
            
            logger.debug(f"Fraud data validation: {validation['overall_quality_score']:.1f}% quality, "
                        f"{len(validation['missing_fields'])} missing fields")
            
            return validation
            
        except Exception as e:
            logger.error(f"Error validating fraud data completeness: {str(e)}")
            return {
                'overall_quality_score': 0.0,
                'completeness_score': 0.0,
                'data_quality_issues': [f"Validation error: {str(e)}"],
                'missing_fields': [],
                'field_scores': {},
                'quality_category': 'ERROR'
            }

    async def get_product_by_barcode(self, barcode: str) -> List[Dict[str, Any]]:
        """Search for product variants by barcode across the store - OPTIMIZED VERSION"""
        query = """
        query($query: String!) {
            productVariants(first: 10, query: $query) {
                edges {
                    node {
                        id
                        title
                        sku
                        barcode
                        product {
                            id
                            title
                            handle
                        }
                        inventoryItem {
                            id
                            inventoryLevels(first: 50) {
                                edges {
                                    node {
                                        id
                                        location {
                                            id
                                            name
                                        }
                                        quantities(names: ["available", "on_hand", "committed"]) {
                                            name
                                            quantity
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {
            "query": f"barcode:{barcode}"
        }
        
        try:
            result = await self._make_graphql_request(query, variables)
            
            variants = []
            edges = result.get("data", {}).get("productVariants", {}).get("edges", [])
            
            for edge in edges:
                variant = edge.get("node", {})
                if variant:
                    # Extract inventory levels for immediate use
                    inventory_item = variant.get("inventoryItem", {})
                    if inventory_item:
                        inventory_levels = {}
                        inv_edges = inventory_item.get("inventoryLevels", {}).get("edges", [])
                        for inv_edge in inv_edges:
                            inv_node = inv_edge.get("node", {})
                            location_id = inv_node.get("location", {}).get("id")
                            if location_id:
                                quantities = {}
                                for q in inv_node.get("quantities", []):
                                    quantities[q.get("name")] = q.get("quantity", 0)
                                
                                inventory_levels[location_id] = {
                                    "location_id": location_id,
                                    "location_name": inv_node.get("location", {}).get("name"),
                                    "inventory_level_id": inv_node.get("id"),
                                    "quantities": quantities
                                }
                        
                        # Store inventory levels in the variant for later use
                        variant["_inventory_levels"] = inventory_levels
                    
                    variants.append(variant)
            
            return variants
            
        except Exception as e:
            logger.error(f"Failed to search products by barcode {barcode}: {str(e)}")
            raise
    
    async def get_inventory_across_locations(self, variant_id: str, location_ids: List[str]) -> Dict[str, Any]:
        """Get inventory levels for a variant across multiple locations"""
        # First get the inventory item ID from the variant
        variant_query = """
        query($variantId: ID!) {
            productVariant(id: $variantId) {
                id
                inventoryItem {
                    id
                }
            }
        }
        """
        
        try:
            variant_result = await self._make_graphql_request(
                variant_query, 
                {"variantId": variant_id}
            )
            
            inventory_item_id = variant_result.get("data", {}).get("productVariant", {}).get("inventoryItem", {}).get("id")
            
            if not inventory_item_id:
                logger.error(f"No inventory item found for variant {variant_id}")
                return {}
            
            # Now get inventory levels for all locations
            inventory_query = """
            query($inventoryItemId: ID!) {
                inventoryItem(id: $inventoryItemId) {
                    id
                    inventoryLevels(first: 50) {
                        edges {
                            node {
                                id
                                location {
                                    id
                                    name
                                }
                                quantities(names: ["available", "on_hand", "committed"]) {
                                    name
                                    quantity
                                }
                            }
                        }
                    }
                }
            }
            """
            
            inventory_result = await self._make_graphql_request(
                inventory_query,
                {"inventoryItemId": inventory_item_id}
            )
            
            # Filter results to only requested locations
            inventory_levels = {}
            edges = inventory_result.get("data", {}).get("inventoryItem", {}).get("inventoryLevels", {}).get("edges", [])
            
            for edge in edges:
                node = edge.get("node", {})
                location_id = node.get("location", {}).get("id")
                
                if location_id in location_ids:
                    quantities = {}
                    for q in node.get("quantities", []):
                        quantities[q.get("name")] = q.get("quantity", 0)
                    
                    inventory_levels[location_id] = {
                        "location_id": location_id,
                        "location_name": node.get("location", {}).get("name"),
                        "inventory_level_id": node.get("id"),
                        "quantities": quantities
                    }
            
            return {
                "variant_id": variant_id,
                "inventory_item_id": inventory_item_id,
                "inventory_levels": inventory_levels
            }
            
        except Exception as e:
            logger.error(f"Failed to get inventory levels for variant {variant_id}: {str(e)}")
            raise
    
    async def get_unfulfilled_orders_for_verification(
        self, 
        barcode: str,
        days_back: int = 4,
        excluded_tag: Optional[str] = None,
        location_id: Optional[str] = None
    ) -> Dict[str, int]:
        """
        DEDICATED METHOD FOR INVENTORY VERIFICATION ONLY
        Does not affect any existing order processing
        
        Fetches unfulfilled orders from the past N days and counts quantities 
        for products matching the given barcode, optionally filtered by fulfillment location.
        
        Args:
            barcode: Product barcode to search for
            days_back: Number of days to look back (default 4)
            excluded_tag: Optional tag to exclude orders containing this tag
            location_id: Optional Shopify location ID to filter by (e.g., "gid://shopify/Location/123")
            
        Returns:
            Dict with total quantity found in unfulfilled orders
        """
        from datetime import datetime, timedelta, timezone
        import time

        try:
            start_time = time.time()
            max_execution_time = 30  # Maximum 30 seconds

            # Calculate date range
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
            
            # Build query filter
            query_parts = [
                f"created_at:>={cutoff_date}",
                "(fulfillment_status:unshipped OR fulfillment_status:partial)",
                "NOT status:cancelled",
                f'sku:"{barcode}"'  # Add SKU filter to reduce result set
            ]
            
            # Add tag exclusion if specified
            if excluded_tag:
                query_parts.append(f"tag_not:{excluded_tag}")
            
            query_filter = " AND ".join(query_parts)
            
            # Query for orders - optimized for lower cost
            # When location filtering is enabled, we need fulfillment data
            # Otherwise, we can use a simpler query
            if location_id:
                orders_query = """
                query getUnfulfilledOrdersForVerification($query: String!, $first: Int!, $after: String) {
                    orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
                        edges {
                            node {
                                id
                                name
                                createdAt
                                displayFulfillmentStatus
                                tags
                                fulfillmentOrders(first: 5) {
                                    edges {
                                        node {
                                            id
                                            status
                                            assignedLocation {
                                                location {
                                                    id
                                                }
                                            }
                                            lineItems(first: 50) {
                                                edges {
                                                    node {
                                                        id
                                                        remainingQuantity
                                                        lineItem {
                                                            variant {
                                                                barcode
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        pageInfo {
                            hasNextPage
                            endCursor
                        }
                    }
                }
                """
            else:
                # Simpler query when no location filtering is needed
                orders_query = """
                query getUnfulfilledOrdersForVerification($query: String!, $first: Int!, $after: String) {
                    orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
                        edges {
                            node {
                                id
                                name
                                createdAt
                                displayFulfillmentStatus
                                tags
                                lineItems(first: 50) {
                                    edges {
                                        node {
                                            quantity
                                            variant {
                                                barcode
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        pageInfo {
                            hasNextPage
                            endCursor
                        }
                    }
                }
                """
            
            total_quantity = 0
            cursor = None
            has_next_page = True
            processed_orders = 0
            pages_fetched = 0
            hit_time_limit = False
            
            # Paginate through orders
            while has_next_page:
                # Check time limit
                elapsed_time = time.time() - start_time
                if elapsed_time >= max_execution_time:
                    logger.warning(f"Inventory verification hit time limit of {max_execution_time}s")
                    hit_time_limit = True
                    break
                
                # Check page limit (safety measure)
                if pages_fetched >= 50:
                    logger.warning("Inventory verification hit page limit of 50")
                    break
                
                variables = {
                    "query": query_filter,
                    "first": 20,  # Reduced to avoid cost limit
                    "after": cursor
                }
                
                result = await self._make_graphql_request(orders_query, variables)
                pages_fetched += 1
                
                orders_data = result.get("data", {}).get("orders", {})
                edges = orders_data.get("edges", [])
                page_info = orders_data.get("pageInfo", {})
                
                # Process each order
                for edge in edges:
                    order = edge.get("node", {})
                    
                    # If location filtering is enabled, use fulfillment order data
                    if location_id:
                        fulfillment_orders = order.get("fulfillmentOrders", {}).get("edges", [])
                        
                        for fo_edge in fulfillment_orders:
                            fo = fo_edge.get("node", {})
                            # Check if this fulfillment order is assigned to the target location
                            assigned_location = fo.get("assignedLocation", {}).get("location", {})
                            if assigned_location.get("id") == location_id:
                                # Process line items from this fulfillment order
                                fo_line_items = fo.get("lineItems", {}).get("edges", [])
                                for fo_line_edge in fo_line_items:
                                    fo_line = fo_line_edge.get("node", {})
                                    line_variant = fo_line.get("lineItem", {}).get("variant", {})
                                    
                                    # Check if barcode matches
                                    if line_variant and line_variant.get("barcode") == barcode:
                                        # Use remaining quantity (unfulfilled quantity)
                                        remaining_qty = fo_line.get("remainingQuantity", 0)
                                        total_quantity += remaining_qty
                                        logger.debug(f"Found {remaining_qty} units in order {order.get('name')} for location {assigned_location.get('name')}")
                    else:
                        # No location filtering - use original logic
                        line_items = order.get("lineItems", {}).get("edges", [])
                        
                        # Check each line item for barcode match
                        for line_item_edge in line_items:
                            line_item = line_item_edge.get("node", {})
                            variant = line_item.get("variant", {})
                            
                            # Check if barcode matches
                            if variant and variant.get("barcode") == barcode:
                                quantity = line_item.get("quantity", 0)
                                total_quantity += quantity
                                logger.debug(f"Found {quantity} units in order {order.get('name')}")
                    
                    processed_orders += 1
                
                # Check for next page
                has_next_page = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")
            
            execution_time = time.time() - start_time
            
            logger.info(f"Inventory verification complete: processed {processed_orders} orders in {pages_fetched} pages, " + 
                       f"found {total_quantity} units in {execution_time:.2f}s" + 
                       (f" for location {location_id}" if location_id else ""))
            
            return {
                "total_quantity": total_quantity,
                "orders_processed": processed_orders,
                "pages_fetched": pages_fetched,
                "execution_time": round(execution_time, 2),
                "hit_time_limit": hit_time_limit,
                "days_back": days_back,
                "excluded_tag": excluded_tag,
                "cutoff_date": cutoff_date,
                "location_id": location_id
            }
            
        except Exception as e:
            logger.error(f"Failed to get unfulfilled orders for verification: {str(e)}")
            # Return zero quantity on error to not break the main flow
            return {
                "total_quantity": 0,
                "orders_processed": 0,
                "pages_fetched": 0,
                "execution_time": 0,
                "hit_time_limit": False,
                "days_back": days_back,
                "excluded_tag": excluded_tag,
                "location_id": location_id,
                "error": str(e)
            }
    
    async def update_inventory_quantities(self, updates: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Update inventory quantities at specific locations
        
        Args:
            updates: List of dicts with:
                - inventory_item_id: str
                - location_id: str
                - available: int (optional)
                - on_hand: int (optional)
        
        Returns:
            Dict with results of each update
        """
        mutation = """
        mutation($input: InventorySetQuantitiesInput!) {
            inventorySetQuantities(input: $input) {
                inventoryAdjustmentGroup {
                    id
                    reason
                    changes {
                        name
                        delta
                        quantityAfterChange
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        results = []
        
        # Group updates by quantity type (available or on_hand)
        available_updates = []
        on_hand_updates = []
        
        for update in updates:
            if "available" in update:
                available_updates.append({
                    "inventoryItemId": update["inventory_item_id"],
                    "locationId": update["location_id"],
                    "quantity": update["available"]
                })
            
            if "on_hand" in update:
                on_hand_updates.append({
                    "inventoryItemId": update["inventory_item_id"],
                    "locationId": update["location_id"],
                    "quantity": update["on_hand"]
                })
        
        # Process available quantity updates
        if available_updates:
            variables = {
                "input": {
                    "reason": "correction",
                    "name": "available",
                    "quantities": available_updates,
                    "ignoreCompareQuantity": True
                }
            }
            
            try:
                result = await self._make_graphql_request(mutation, variables)
                
                inventory_result = result.get("data", {}).get("inventorySetQuantities", {})
                user_errors = inventory_result.get("userErrors", [])
                
                if user_errors:
                    logger.error(f"Inventory update errors for available quantities: {user_errors}")
                    for qty_update in available_updates:
                        results.append({
                            "success": False,
                            "location_id": qty_update["locationId"],
                            "inventory_item_id": qty_update["inventoryItemId"],
                            "quantity_type": "available",
                            "errors": user_errors
                        })
                else:
                    for qty_update in available_updates:
                        results.append({
                            "success": True,
                            "location_id": qty_update["locationId"],
                            "inventory_item_id": qty_update["inventoryItemId"],
                            "quantity_type": "available",
                            "adjustment_group": inventory_result.get("inventoryAdjustmentGroup")
                        })
                    
            except Exception as e:
                logger.error(f"Failed to update available inventory: {str(e)}")
                for qty_update in available_updates:
                    results.append({
                        "success": False,
                        "location_id": qty_update["locationId"],
                        "inventory_item_id": qty_update["inventoryItemId"],
                        "quantity_type": "available",
                        "error": str(e)
                    })
        
        # Process on_hand quantity updates
        if on_hand_updates:
            variables = {
                "input": {
                    "reason": "correction",
                    "name": "on_hand",
                    "quantities": on_hand_updates,
                    "ignoreCompareQuantity": True
                }
            }
            
            try:
                result = await self._make_graphql_request(mutation, variables)
                
                inventory_result = result.get("data", {}).get("inventorySetQuantities", {})
                user_errors = inventory_result.get("userErrors", [])
                
                if user_errors:
                    logger.error(f"Inventory update errors for on_hand quantities: {user_errors}")
                    for qty_update in on_hand_updates:
                        results.append({
                            "success": False,
                            "location_id": qty_update["locationId"],
                            "inventory_item_id": qty_update["inventoryItemId"],
                            "quantity_type": "on_hand",
                            "errors": user_errors
                        })
                else:
                    for qty_update in on_hand_updates:
                        results.append({
                            "success": True,
                            "location_id": qty_update["locationId"],
                            "inventory_item_id": qty_update["inventoryItemId"],
                            "quantity_type": "on_hand",
                            "adjustment_group": inventory_result.get("inventoryAdjustmentGroup")
                        })
                    
            except Exception as e:
                logger.error(f"Failed to update on_hand inventory: {str(e)}")
                for qty_update in on_hand_updates:
                    results.append({
                        "success": False,
                        "location_id": qty_update["locationId"],
                        "inventory_item_id": qty_update["inventoryItemId"],
                        "quantity_type": "on_hand",
                        "error": str(e)
                    })
        
        return {
            "results": results,
            "total": len(updates),
            "successful": len([r for r in results if r.get("success", False)])
        }
