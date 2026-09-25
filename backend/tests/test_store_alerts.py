"""Tests for recognizing repeated store alerts whose messages differ only by Shopify request IDs. Pure."""
import pytest

from tasks import _alert_fingerprint

FIRST = ("GraphQL errors: [{'message': 'Internal error. Looks like something went wrong on our end.\\nRequest ID: "
         "a9ff0709-945c-4d91-9578-ff7c62c38bfa-1790348040 (include this in support requests).', 'extensions': "
         "{'requestId': 'a9ff0709-945c-4d91-9578-ff7c62c38bfa-1790348040', 'code': 'INTERNAL_SERVER_ERROR'}}]")
SECOND = FIRST.replace("a9ff0709-945c-4d91-9578-ff7c62c38bfa-1790348040", "810322cf-1652-40eb-8ac8-b13fc6273bed-1790348007")


class TestAlertFingerprint:
    def test_messages_differing_only_by_request_id_match(self):
        assert _alert_fingerprint(FIRST) == _alert_fingerprint(SECOND)

    def test_request_ids_are_masked(self):
        assert "a9ff0709" not in _alert_fingerprint(FIRST)

    @pytest.mark.parametrize("other", [
        "Shopify GraphQL error: 401",
        FIRST.replace("INTERNAL_SERVER_ERROR", "ACCESS_DENIED"),
    ])
    def test_different_problems_do_not_match(self, other):
        assert _alert_fingerprint(FIRST) != _alert_fingerprint(other)

    def test_message_without_ids_is_unchanged(self):
        assert _alert_fingerprint("Shipper database unreachable: timeout") == "Shipper database unreachable: timeout"

    def test_none_is_empty(self):
        assert _alert_fingerprint(None) == ""
