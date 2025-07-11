import httpx
import json
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

class ShopifyClient:
    def __init__(self, shop_domain: str, access_token: str):
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.base_url = f"https://{shop_domain}/admin/api/2025-04"
        self.headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json"
        }
    
    async def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """Make authenticated request to Shopify API"""
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/{endpoint}"
            
            try:
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
                raise Exception(f"Shopify API error: {e.response.status_code}")
            except Exception as e:
                logger.error(f"Request failed: {str(e)}")
                raise
    
    async def _make_graphql_request(self, query: str, variables: Optional[Dict] = None) -> Dict:
        """Make GraphQL request to Shopify Admin API"""
        async with httpx.AsyncClient() as client:
            url = f"{self.base_url}/graphql.json"
            
            payload = {
                "query": query,
                "variables": variables or {}
            }
            
            try:
                response = await client.post(url, headers=self.headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                if "errors" in result:
                    logger.error(f"GraphQL errors: {result['errors']}")
                    raise Exception(f"GraphQL errors: {result['errors']}")
                
                return result
                
            except httpx.HTTPStatusError as e:
                logger.error(f"Shopify GraphQL error: {e.response.status_code} - {e.response.text}")
                raise Exception(f"Shopify GraphQL error: {e.response.status_code}")
            except Exception as e:
                logger.error(f"GraphQL request failed: {str(e)}")
                raise
    
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
        cursor: Optional[str] = None
    ) -> Dict:
        """Get orders with pagination"""
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
    
    async def get_order_by_id(self, order_id: str) -> Dict | None:
        """Get a specific order by ID for retry processing"""
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