"""
Enhanced Shopify client with MCP-inspired delivery tracking
"""
import httpx
import json
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

class EnhancedShopifyClient:
    def __init__(self, shop_domain: str, access_token: str):
        self.shop_domain = shop_domain
        self.access_token = access_token
        self.base_url = f"https://{shop_domain}/admin/api/2025-04"
        self.headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json"
        }

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

    async def get_order_with_comprehensive_delivery_data(self, order_name: str) -> Dict[str, Any]:
        """
        Get order with comprehensive delivery tracking data using MCP-optimized GraphQL
        This query is based on Shopify MCP best practices for delivery tracking
        """
        
        # MCP-optimized query for comprehensive delivery tracking
        query = """
        query getOrderWithDeliveryTracking($query: String!) {
            orders(first: 1, query: $query) {
                edges {
                    node {
                        id
                        name
                        createdAt
                        updatedAt
                        processedAt
                        displayFulfillmentStatus
                        displayFinancialStatus
                        totalPriceSet {
                            shopMoney {
                                amount
                                currencyCode
                            }
                        }
                        note
                        email
                        
                        # Customer with comprehensive order history
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
                            orders(first: 15, sortKey: CREATED_AT, reverse: true) {
                                edges {
                                    node {
                                        id
                                        name
                                        createdAt
                                        processedAt
                                        cancelledAt
                                        displayFulfillmentStatus
                                        totalPriceSet {
                                            shopMoney {
                                                amount
                                                currencyCode
                                            }
                                        }
                                        # Comprehensive fulfillment data for each historical order
                                        fulfillments(first: 10) {
                                            id
                                            status
                                            displayStatus
                                            deliveredAt
                                            inTransitAt
                                            estimatedDeliveryAt
                                            createdAt
                                            updatedAt
                                            name
                                            trackingInfo(first: 5) {
                                                company
                                                number
                                                url
                                            }
                                            # Comprehensive fulfillment events with all delivery tracking data
                                            events(first: 50, reverse: true, sortKey: HAPPENED_AT) {
                                                edges {
                                                    node {
                                                        id
                                                        status
                                                        happenedAt
                                                        createdAt
                                                        message
                                                        address1
                                                        city
                                                        province
                                                        country
                                                        zip
                                                        latitude
                                                        longitude
                                                        estimatedDeliveryAt
                                                    }
                                                }
                                            }
                                            location {
                                                id
                                                name
                                                address {
                                                    city
                                                    province
                                                    country
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        
                        # Billing and shipping addresses
                        billingAddress {
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
                        shippingAddress {
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
                        
                        # Transaction data
                        transactions(first: 25) {
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
                            processedAt
                            gateway
                            test
                            errorCode
                            parentTransaction {
                                id
                            }
                        }
                        
                        # Line items
                        lineItems(first: 50) {
                            edges {
                                node {
                                    id
                                    title
                                    quantity
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
                                    product {
                                        id
                                        title
                                        productType
                                        vendor
                                        tags
                                    }
                                }
                            }
                        }
                        
                        # Current order fulfillments with comprehensive tracking
                        fulfillments(first: 10) {
                            id
                            status
                            displayStatus
                            deliveredAt
                            inTransitAt
                            estimatedDeliveryAt
                            createdAt
                            updatedAt
                            name
                            trackingInfo(first: 5) {
                                company
                                number
                                url
                            }
                            # Comprehensive fulfillment events
                            events(first: 50, reverse: true, sortKey: HAPPENED_AT) {
                                edges {
                                    node {
                                        id
                                        status
                                        happenedAt
                                        createdAt
                                        message
                                        address1
                                        city
                                        province
                                        country
                                        zip
                                        latitude
                                        longitude
                                        estimatedDeliveryAt
                                    }
                                }
                            }
                            location {
                                id
                                name
                                address {
                                    city
                                    province
                                    country
                                }
                            }
                        }
                        
                        # Custom attributes and metafields
                        customAttributes {
                            key
                            value
                        }
                        metafields(first: 100) {
                            edges {
                                node {
                                    namespace
                                    key
                                    value
                                    type
                                }
                            }
                        }
                        
                        # Risk assessment (Shopify's fraud assessment)
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
            
            # Structure the data for fraud analysis compatibility
            fraud_data = {
                "order_info": {
                    "id": order_data.get("id"),
                    "name": order_data.get("name"),
                    "created_at": order_data.get("createdAt"),
                    "processed_at": order_data.get("processedAt"),
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
            }
            
            logger.info(f"Successfully retrieved comprehensive delivery data for order {order_name}")
            logger.info(f"Customer order history: {len(order_data.get('customer', {}).get('orders', {}).get('edges', []))} orders")
            logger.info(f"Current order fulfillments: {len(order_data.get('fulfillments', []))}")
            
            return fraud_data
            
        except Exception as e:
            logger.error(f"Failed to fetch comprehensive delivery data for order {order_name}: {str(e)}")
            return None

    async def get_fulfillment_by_id(self, fulfillment_id: str) -> Dict[str, Any]:
        """Get detailed fulfillment information by ID"""
        
        query = """
        query getFulfillmentDetails($id: ID!) {
            fulfillment(id: $id) {
                id
                status
                displayStatus
                deliveredAt
                inTransitAt
                estimatedDeliveryAt
                createdAt
                updatedAt
                name
                totalQuantity
                trackingInfo(first: 10) {
                    company
                    number
                    url
                }
                events(first: 100, reverse: true, sortKey: HAPPENED_AT) {
                    edges {
                        node {
                            id
                            status
                            happenedAt
                            createdAt
                            message
                            address1
                            address2
                            city
                            province
                            country
                            zip
                            latitude
                            longitude
                            estimatedDeliveryAt
                        }
                    }
                }
                location {
                    id
                    name
                    address {
                        address1
                        address2
                        city
                        province
                        country
                        zip
                    }
                }
                order {
                    id
                    name
                    createdAt
                }
            }
        }
        """
        
        variables = {"id": fulfillment_id}
        
        try:
            result = await self._make_graphql_request(query, variables)
            return result.get("data", {}).get("fulfillment")
        except Exception as e:
            logger.error(f"Failed to fetch fulfillment {fulfillment_id}: {str(e)}")
            return None