"""
Token encryption utilities using Fernet symmetric encryption.

This module provides secure encryption/decryption for sensitive data like
Shopify access tokens. The encryption key must be set via the ENCRYPTION_KEY
environment variable.

Usage:
    from encryption import encrypt_token, decrypt_token

    encrypted = encrypt_token("my_secret_token")
    original = decrypt_token(encrypted)
"""

import os
import base64
import logging
from functools import lru_cache
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Prefix to identify encrypted tokens (helps with migration)
ENCRYPTED_PREFIX = "enc:v1:"


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""
    pass


class EncryptionKeyMissingError(EncryptionError):
    """Raised when the encryption key is not configured."""
    pass


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    """
    Get a Fernet instance using the encryption key from environment.

    The key is cached after first retrieval for performance.

    Returns:
        Fernet: A configured Fernet encryption instance.

    Raises:
        EncryptionKeyMissingError: If ENCRYPTION_KEY is not set.
        EncryptionError: If the key is invalid.
    """
    encryption_key = os.environ.get("ENCRYPTION_KEY")

    if not encryption_key:
        raise EncryptionKeyMissingError(
            "ENCRYPTION_KEY environment variable is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    # Validate key format
    try:
        # Fernet keys should be 32 url-safe base64-encoded bytes
        key_bytes = encryption_key.encode('utf-8')
        return Fernet(key_bytes)
    except Exception as e:
        raise EncryptionError(
            f"Invalid ENCRYPTION_KEY format. Key must be a valid Fernet key. "
            f"Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\". "
            f"Error: {str(e)}"
        )


def encrypt_token(token: str) -> str:
    """
    Encrypt a token using Fernet symmetric encryption.

    Args:
        token: The plaintext token to encrypt.

    Returns:
        str: The encrypted token with version prefix.

    Raises:
        EncryptionError: If encryption fails.
        EncryptionKeyMissingError: If ENCRYPTION_KEY is not set.
    """
    if not token:
        raise EncryptionError("Cannot encrypt empty token")

    # If already encrypted, return as-is
    if token.startswith(ENCRYPTED_PREFIX):
        return token

    try:
        fernet = get_fernet()
        encrypted_bytes = fernet.encrypt(token.encode('utf-8'))
        encrypted_str = encrypted_bytes.decode('utf-8')
        return f"{ENCRYPTED_PREFIX}{encrypted_str}"
    except (EncryptionError, EncryptionKeyMissingError):
        raise
    except Exception as e:
        raise EncryptionError(f"Failed to encrypt token: {str(e)}")


def decrypt_token(encrypted_token: str) -> str:
    """
    Decrypt an encrypted token.

    Handles both encrypted tokens (with prefix) and legacy plaintext tokens
    for backward compatibility during migration.

    Args:
        encrypted_token: The encrypted token to decrypt.

    Returns:
        str: The decrypted plaintext token.

    Raises:
        EncryptionError: If decryption fails.
        EncryptionKeyMissingError: If ENCRYPTION_KEY is not set.
    """
    if not encrypted_token:
        raise EncryptionError("Cannot decrypt empty token")

    # Handle legacy plaintext tokens (for migration)
    if not encrypted_token.startswith(ENCRYPTED_PREFIX):
        logger.warning(
            "Token is not encrypted. This indicates a legacy token that should be migrated."
        )
        return encrypted_token

    try:
        fernet = get_fernet()
        # Remove prefix before decryption
        encrypted_data = encrypted_token[len(ENCRYPTED_PREFIX):]
        decrypted_bytes = fernet.decrypt(encrypted_data.encode('utf-8'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken:
        raise EncryptionError(
            "Failed to decrypt token: Invalid token or wrong encryption key. "
            "This may occur if the ENCRYPTION_KEY was changed after tokens were encrypted."
        )
    except (EncryptionError, EncryptionKeyMissingError):
        raise
    except Exception as e:
        raise EncryptionError(f"Failed to decrypt token: {str(e)}")


def is_token_encrypted(token: str) -> bool:
    """
    Check if a token is already encrypted.

    Args:
        token: The token to check.

    Returns:
        bool: True if the token is encrypted, False otherwise.
    """
    return token.startswith(ENCRYPTED_PREFIX) if token else False


def generate_encryption_key() -> str:
    """
    Generate a new Fernet encryption key.

    Returns:
        str: A new URL-safe base64-encoded 32-byte key.
    """
    return Fernet.generate_key().decode('utf-8')
