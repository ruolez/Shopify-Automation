import pytest
from tasks import _combine_product_and_variant_title


@pytest.mark.unit
class TestCombineProductAndVariantTitle:
    """Test cases for the _combine_product_and_variant_title helper function"""

    def test_product_title_only(self):
        """Test with product title only (no variant title)"""
        product_title = "iPhone 14"
        variant_title = ""
        
        result = _combine_product_and_variant_title(product_title, variant_title)
        
        assert result == "iPhone 14"

    def test_product_title_with_variant_title(self):
        """Test with both product title and variant title"""
        product_title = "iPhone 14"
        variant_title = "128GB Blue"
        
        result = _combine_product_and_variant_title(product_title, variant_title)
        
        assert result == "iPhone 14 128GB Blue"

    def test_empty_product_title_with_variant_title(self):
        """Test with empty product title but variant title present"""
        product_title = ""
        variant_title = "128GB Blue"
        
        result = _combine_product_and_variant_title(product_title, variant_title)
        
        assert result == "Unknown Product 128GB Blue"

    def test_both_empty(self):
        """Test with both product title and variant title empty"""
        product_title = ""
        variant_title = ""
        
        result = _combine_product_and_variant_title(product_title, variant_title)
        
        assert result == "Unknown Product"

    def test_whitespace_only_variant_title(self):
        """Test with variant title containing only whitespace"""
        product_title = "iPhone 14"
        variant_title = "   "
        
        result = _combine_product_and_variant_title(product_title, variant_title)
        
        assert result == "iPhone 14"

    def test_none_variant_title(self):
        """Test with None variant title"""
        product_title = "iPhone 14"
        variant_title = None
        
        result = _combine_product_and_variant_title(product_title, variant_title)
        
        assert result == "iPhone 14"

    def test_none_product_title(self):
        """Test with None product title"""
        product_title = None
        variant_title = "128GB Blue"
        
        result = _combine_product_and_variant_title(product_title, variant_title)
        
        assert result == "Unknown Product 128GB Blue"

    def test_both_none(self):
        """Test with both titles as None"""
        product_title = None
        variant_title = None
        
        result = _combine_product_and_variant_title(product_title, variant_title)
        
        assert result == "Unknown Product"