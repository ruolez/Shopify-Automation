"""
Safe regex module with timeout protection against ReDoS attacks.

This module provides functions for safely compiling and matching regex patterns
with timeout limits to prevent Regular Expression Denial of Service (ReDoS) attacks.
"""
import logging
from typing import Optional

import regex

logger = logging.getLogger(__name__)

MAX_PATTERN_LENGTH = 500
REGEX_TIMEOUT = 0.5  # seconds


def safe_regex_match(pattern_str: str, text: str) -> bool:
    """
    Safely match a regex pattern with timeout and length limits.

    Args:
        pattern_str: The regex pattern to match
        text: The text to search in

    Returns:
        True if pattern matches, False on any error, timeout, or no match.
    """
    if not pattern_str or not text:
        return False

    if len(pattern_str) > MAX_PATTERN_LENGTH:
        logger.warning(
            f"Regex pattern too long: {len(pattern_str)} chars (max {MAX_PATTERN_LENGTH})"
        )
        return False

    try:
        pattern = regex.compile(pattern_str, regex.IGNORECASE, timeout=REGEX_TIMEOUT)
        return bool(pattern.search(str(text)))
    except regex.error as e:
        logger.error(f"Invalid regex pattern: {pattern_str[:50]}... - {e}")
        return False
    except TimeoutError:
        logger.error(f"Regex timeout for pattern: {pattern_str[:50]}...")
        return False
    except Exception as e:
        logger.error(f"Regex error: {e}")
        return False


def safe_regex_compile(pattern_str: str) -> Optional[regex.Pattern]:
    """
    Safely compile a regex pattern with validation.

    Args:
        pattern_str: The regex pattern to compile

    Returns:
        Compiled regex pattern or None on error.
    """
    if not pattern_str:
        return None

    if len(pattern_str) > MAX_PATTERN_LENGTH:
        logger.warning(f"Regex pattern too long: {len(pattern_str)} chars")
        return None

    try:
        return regex.compile(pattern_str, regex.IGNORECASE, timeout=REGEX_TIMEOUT)
    except regex.error as e:
        logger.error(f"Invalid regex pattern: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error compiling regex: {e}")
        return None


def validate_regex_pattern(pattern_str: str) -> tuple[bool, str]:
    """
    Validate a regex pattern without executing it.

    Args:
        pattern_str: The regex pattern to validate

    Returns:
        Tuple of (is_valid, error_message). error_message is empty if valid.
    """
    if not pattern_str:
        return False, "Pattern cannot be empty"

    if len(pattern_str) > MAX_PATTERN_LENGTH:
        return False, f"Pattern too long: {len(pattern_str)} chars (max {MAX_PATTERN_LENGTH})"

    try:
        regex.compile(pattern_str, regex.IGNORECASE, timeout=REGEX_TIMEOUT)
        return True, ""
    except regex.error as e:
        return False, f"Invalid regex syntax: {e}"
    except Exception as e:
        return False, f"Validation error: {e}"
