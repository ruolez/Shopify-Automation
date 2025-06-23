import pytest
from unittest.mock import AsyncMock, patch
import httpx
from shopify_client import ShopifyClient

class TestShopifyClient:
    def setup_method(self):
        """Set up test fixtures"""
        self.client = ShopifyClient("test-store.myshopify.com", "test_token")

    @patch('httpx.AsyncClient.post')
    async def test_execute_query_success(self, mock_post):
        """Test successful GraphQL query execution"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "shop": {
                    "name": "Test Store"
                }
            }
        }
        mock_post.return_value = mock_response

        query = "query { shop { name } }"
        result = await self.client.execute_query(query)
        
        assert result["shop"]["name"] == "Test Store"
        mock_post.assert_called_once()

    @patch('httpx.AsyncClient.post')
    async def test_execute_query_error(self, mock_post):
        """Test GraphQL query execution with error"""
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "errors": [
                {
                    "message": "Field 'invalid' doesn't exist on type 'Shop'"
                }
            ]
        }
        mock_post.return_value = mock_response

        query = "query { shop { invalid } }"
        
        with pytest.raises(Exception, match="GraphQL error"):
            await self.client.execute_query(query)

    @patch('httpx.AsyncClient.post')
    async def test_execute_query_http_error(self, mock_post):
        """Test GraphQL query execution with HTTP error"""
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=None, response=mock_response
        )
        mock_post.return_value = mock_response

        query = "query { shop { name } }"
        
        with pytest.raises(Exception, match="HTTP error"):
            await self.client.execute_query(query)

    @patch.object(ShopifyClient, 'execute_query')
    async def test_test_connection_success(self, mock_execute):
        """Test successful connection test"""
        mock_execute.return_value = {
            "shop": {
                "name": "Test Store"
            }
        }

        result = await self.client.test_connection()
        assert result is True

    @patch.object(ShopifyClient, 'execute_query')
    async def test_test_connection_failure(self, mock_execute):
        """Test failed connection test"""
        mock_execute.side_effect = Exception("Connection failed")

        result = await self.client.test_connection()
        assert result is False

    @patch.object(ShopifyClient, 'execute_query')
    async def test_get_shop_info_success(self, mock_execute):
        """Test getting shop information successfully"""
        mock_execute.return_value = {
            "shop": {
                "name": "Test Store",
                "myshopifyDomain": "test-store.myshopify.com",
                "email": "test@example.com"
            }
        }

        result = await self.client.get_shop_info()
        expected = {
            "name": "Test Store",
            "domain": "test-store.myshopify.com",
            "email": "test@example.com"
        }
        assert result == expected

    @patch.object(ShopifyClient, 'execute_query')
    async def test_get_orders_success(self, mock_execute):
        """Test getting orders successfully"""
        mock_execute.return_value = {
            "orders": {
                "edges": [
                    {
                        "node": {
                            "id": "gid://shopify/Order/12345",
                            "name": "#1001",
                            "totalPriceSet": {
                                "shopMoney": {
                                    "amount": "150.00",
                                    "currencyCode": "USD"
                                }
                            }
                        }
                    }
                ]
            }
        }

        result = await self.client.get_orders()
        assert len(result) == 1
        assert result[0]["name"] == "#1001"

    @patch.object(ShopifyClient, 'execute_query')
    async def test_add_tags_to_order_success(self, mock_execute):
        """Test adding tags to order successfully"""
        mock_execute.return_value = {
            "tagsAdd": {
                "node": {
                    "id": "gid://shopify/Order/12345"
                },
                "userErrors": []
            }
        }

        result = await self.client.add_tags_to_order("gid://shopify/Order/12345", ["test-tag"])
        assert result is True

    @patch.object(ShopifyClient, 'execute_query')
    async def test_add_tags_to_order_failure(self, mock_execute):
        """Test adding tags to order with errors"""
        mock_execute.return_value = {
            "tagsAdd": {
                "node": None,
                "userErrors": [
                    {
                        "field": ["id"],
                        "message": "Order not found"
                    }
                ]
            }
        }

        result = await self.client.add_tags_to_order("gid://shopify/Order/invalid", ["test-tag"])
        assert result is False

    @patch.object(ShopifyClient, 'execute_query')
    async def test_get_locations_success(self, mock_execute):
        """Test getting locations successfully"""
        mock_execute.return_value = {
            "locations": {
                "edges": [
                    {
                        "node": {
                            "id": "gid://shopify/Location/1",
                            "name": "Main Warehouse"
                        }
                    }
                ]
            }
        }

        result = await self.client.get_locations()
        assert len(result) == 1
        assert result[0]["name"] == "Main Warehouse"

    @patch.object(ShopifyClient, 'execute_query')
    async def test_move_fulfillment_order_success(self, mock_execute):
        """Test moving fulfillment order successfully"""
        mock_execute.return_value = {
            "fulfillmentOrderMove": {
                "movedFulfillmentOrder": {
                    "id": "gid://shopify/FulfillmentOrder/1"
                },
                "userErrors": []
            }
        }

        result = await self.client.move_fulfillment_order(
            "gid://shopify/FulfillmentOrder/1",
            "gid://shopify/Location/1"
        )
        assert result is True

    @patch.object(ShopifyClient, 'execute_query')
    async def test_move_fulfillment_order_failure(self, mock_execute):
        """Test moving fulfillment order with errors"""
        mock_execute.return_value = {
            "fulfillmentOrderMove": {
                "movedFulfillmentOrder": None,
                "userErrors": [
                    {
                        "field": ["fulfillmentOrderId"],
                        "message": "Fulfillment order not found"
                    }
                ]
            }
        }

        result = await self.client.move_fulfillment_order(
            "gid://shopify/FulfillmentOrder/invalid",
            "gid://shopify/Location/1"
        )
        assert result is False