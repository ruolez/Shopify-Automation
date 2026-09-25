"""Encrypted model fields must be settable through the model constructor
(POST /stores builds ShopifyStore(access_token=...)). Pure; run with --noconftest."""
from models import Settings, ShopifyStore

TOKEN = "shpat_admin_token"
REFRESH = "shprt_refresh_token"
SECRET = "shpss_client_secret"
PASSWORD = "shipper-db-password"


def test_store_constructor_encrypts_token_fields():
    store = ShopifyStore(
        user_id=1, shop_domain="tobacco-nation.myshopify.com", shop_name="Tobacco Nation",
        access_token=TOKEN, refresh_token=REFRESH, client_secret=SECRET,
    )
    assert (store.access_token, store.refresh_token, store.client_secret) == (TOKEN, REFRESH, SECRET)
    assert TOKEN not in store._access_token_encrypted
    assert SECRET not in store._client_secret_encrypted


def test_store_optional_secrets_default_to_none():
    store = ShopifyStore(user_id=1, shop_domain="x.myshopify.com", shop_name="x", access_token=TOKEN)
    assert (store.refresh_token, store.client_secret) == (None, None)


def test_settings_constructor_encrypts_shipper_password():
    settings = Settings(user_id=1, shipper_db_password=PASSWORD)
    assert settings.shipper_db_password == PASSWORD
    assert PASSWORD not in settings._shipper_db_password_encrypted
