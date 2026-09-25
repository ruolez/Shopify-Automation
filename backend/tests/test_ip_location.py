"""Tests for the IP geolocation lookup; the HTTP call is served by an httpx MockTransport."""
import asyncio

import httpx
import pytest

import ip_location
from ip_location import lookup_ip_location

PUBLIC_IP = "72.24.210.88"
ODESSA = {"status": "success", "city": "Odessa", "regionName": "Texas", "country": "United States"}


@pytest.fixture
def served(monkeypatch):
    """Serve ip-api responses from a handler and record the requested URLs"""
    ip_location._cache.clear()
    monkeypatch.delenv("IP_API_KEY", raising=False)
    requests = []
    state = {"handler": lambda request: httpx.Response(200, json=ODESSA)}
    real_client = httpx.AsyncClient

    def client(*args, **kwargs):
        def handle(request):
            requests.append(str(request.url))
            return state["handler"](request)
        kwargs["transport"] = httpx.MockTransport(handle)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(ip_location.httpx, "AsyncClient", client)
    yield state, requests
    ip_location._cache.clear()


def lookup(ip):
    return asyncio.run(lookup_ip_location(ip))


class TestLookupIpLocation:
    def test_formats_city_region_country(self, served):
        _, requests = served
        assert (lookup(PUBLIC_IP), requests) == (
            "Odessa, Texas, United States",
            [f"http://ip-api.com/json/{PUBLIC_IP}?fields=status,city,regionName,country"],
        )

    def test_skips_blank_parts(self, served):
        state, _ = served
        state["handler"] = lambda request: httpx.Response(200, json={**ODESSA, "city": ""})
        assert lookup(PUBLIC_IP) == "Texas, United States"

    def test_second_lookup_is_served_from_cache(self, served):
        _, requests = served
        assert ([lookup(PUBLIC_IP), lookup(PUBLIC_IP)], len(requests)) == (["Odessa, Texas, United States"] * 2, 1)

    @pytest.mark.parametrize("ip", [None, "", "not-an-ip", "10.0.0.5", "127.0.0.1", "192.168.1.9", "::1"])
    def test_private_or_invalid_ip_is_not_looked_up(self, served, ip):
        _, requests = served
        assert (lookup(ip), requests) == (None, [])

    def test_ipv6_is_looked_up(self, served):
        ip = "2607:fb90:55ab:4610:1d28:d3fa:e20e:df7"
        _, requests = served
        assert (lookup(ip), requests) == (
            "Odessa, Texas, United States",
            [f"http://ip-api.com/json/{ip}?fields=status,city,regionName,country"],
        )

    def test_failed_status_is_none(self, served):
        state, _ = served
        state["handler"] = lambda request: httpx.Response(200, json={"status": "fail", "message": "reserved range"})
        assert lookup(PUBLIC_IP) is None

    def test_http_error_is_none_and_not_cached(self, served):
        state, requests = served
        state["handler"] = lambda request: httpx.Response(429)
        assert lookup(PUBLIC_IP) is None
        state["handler"] = lambda request: httpx.Response(200, json=ODESSA)
        assert (lookup(PUBLIC_IP), len(requests)) == ("Odessa, Texas, United States", 2)

    def test_network_error_is_none(self, served):
        state, _ = served

        def fail(request):
            raise httpx.ConnectError("unreachable")
        state["handler"] = fail
        assert lookup(PUBLIC_IP) is None

    def test_api_key_uses_pro_endpoint(self, served, monkeypatch):
        _, requests = served
        monkeypatch.setenv("IP_API_KEY", "secret")
        lookup(PUBLIC_IP)
        assert requests == [f"https://pro.ip-api.com/json/{PUBLIC_IP}?fields=status,city,regionName,country&key=secret"]
