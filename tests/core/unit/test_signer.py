"""Tests for sdk.core.signer."""

from datetime import datetime, timezone

import httpx

from sdk.core.signer import (
    ALGORITHM,
    SignOptions,
    _canonical_path,
    _canonical_query,
    _derive_key,
    _format_date,
    _format_datetime,
    _hash_sha256,
    _hmac_sha256,
    _signed_headers_string,
    sign_request,
)

# Fixed timestamp for reproducible tests
FIXED_TIME = datetime(2024, 4, 15, 10, 30, 0, tzinfo=timezone.utc)
FIXED_DT_STR = "20240415T103000Z"
FIXED_DATE_STR = "20240415"

OPTS = SignOptions(
    access_key="TESTAKXXXXXXXX",
    secret_key="TESTSKXXXXXXXXXXXXXXXXXXXXXXXX",
    region_name="eu-de",
    service_name="dns",
)


class TestFormatting:
    def test_format_datetime(self):
        assert _format_datetime(FIXED_TIME) == FIXED_DT_STR

    def test_format_date(self):
        assert _format_date(FIXED_TIME) == FIXED_DATE_STR


class TestCryptoPrimitives:
    def test_hash_sha256_empty(self):
        result = _hash_sha256(b"")
        assert result == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_hash_sha256_data(self):
        result = _hash_sha256(b"hello")
        assert result == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    def test_hmac_sha256(self):
        result = _hmac_sha256("data", b"secret")
        assert len(result) == 32  # SHA-256 always 32 bytes

    def test_derive_key_deterministic(self):
        key1 = _derive_key("SK_TEST", "20240415", "eu-de", "dns")
        key2 = _derive_key("SK_TEST", "20240415", "eu-de", "dns")
        assert key1 == key2
        assert len(key1) == 32

    def test_derive_key_different_date(self):
        key1 = _derive_key("SK_TEST", "20240415", "eu-de", "dns")
        key2 = _derive_key("SK_TEST", "20240416", "eu-de", "dns")
        assert key1 != key2


class TestCanonicalPath:
    def test_simple_path(self):
        req = httpx.Request("GET", "https://example.com/v2/zones")
        path = _canonical_path(req)
        assert path == "/v2/zones/"

    def test_root_path(self):
        req = httpx.Request("GET", "https://example.com/")
        path = _canonical_path(req)
        assert path == "/"

    def test_trailing_slash_preserved(self):
        req = httpx.Request("GET", "https://example.com/v2/zones/")
        path = _canonical_path(req)
        assert path == "/v2/zones/"


class TestCanonicalQuery:
    def test_no_params(self):
        req = httpx.Request("GET", "https://example.com/v2/zones")
        assert _canonical_query(req) == ""

    def test_sorted_params(self):
        req = httpx.Request("GET", "https://example.com/v2/zones?name=test&limit=10")
        qs = _canonical_query(req)
        assert "limit" in qs
        assert "name" in qs
        # 'limit' should come before 'name' alphabetically
        assert qs.index("limit") < qs.index("name")

    def test_special_chars_encoded(self):
        req = httpx.Request("GET", "https://example.com/test?key=hello world")
        qs = _canonical_query(req)
        assert "hello%20world" in qs


class TestSignRequest:
    def test_adds_authorization_header(self):
        req = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        assert "authorization" in req.headers
        assert req.headers["authorization"].startswith(ALGORITHM)

    def test_adds_sdk_date_header(self):
        req = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        assert req.headers["x-sdk-date"] == FIXED_DT_STR

    def test_adds_host_header(self):
        req = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        assert req.headers["host"] == "dns.eu-de.otc.t-systems.com"

    def test_authorization_contains_credential(self):
        req = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        assert f"Credential={OPTS.access_key}/" in auth

    def test_authorization_contains_signed_headers(self):
        req = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        assert "SignedHeaders=" in auth
        assert "host" in auth
        assert "x-sdk-date" in auth

    def test_authorization_contains_signature(self):
        req = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        assert "Signature=" in auth
        # Signature is hex, 64 chars
        sig = auth.split("Signature=")[1]
        assert len(sig) == 64

    def test_deterministic_signature(self):
        """Same request + same timestamp = same signature."""
        req1 = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        req2 = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        sign_request(req1, OPTS, timestamp=FIXED_TIME)
        sign_request(req2, OPTS, timestamp=FIXED_TIME)
        assert req1.headers["authorization"] == req2.headers["authorization"]

    def test_different_timestamp_different_signature(self):
        ts1 = datetime(2024, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 4, 15, 11, 0, 0, tzinfo=timezone.utc)
        req1 = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        req2 = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        sign_request(req1, OPTS, timestamp=ts1)
        sign_request(req2, OPTS, timestamp=ts2)
        assert req1.headers["authorization"] != req2.headers["authorization"]

    def test_post_with_body(self):
        req = httpx.Request(
            "POST",
            "https://dns.eu-de.otc.t-systems.com/v2/zones",
            json={"name": "example.com.", "zone_type": "public"},
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        assert req.headers["authorization"].startswith(ALGORITHM)

    def test_scope_format(self):
        req = httpx.Request("GET", "https://dns.eu-de.otc.t-systems.com/v2/zones")
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        expected_scope = f"{FIXED_DATE_STR}/eu-de/dns/sdk_request"
        assert expected_scope in auth
