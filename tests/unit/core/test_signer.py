"""Tests for sdk.core.signer."""

from datetime import datetime, timezone

import httpx
import pytest

from sdk.core.signer import (
    SIGN_ALGORITHM_HMAC_SHA256,
    SignOptions,
    _build_sign_key,
    _build_sign_params,
    _canonical_path,
    _canonical_query,
    _derive_signing_key,
    _format_date,
    _format_datetime,
    _hash_sha256,
    _hmac_sha256,
    _signed_headers_string,
    _use_payload_for_query,
    re_sign_request,
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
        assert result == (
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855"
        )

    def test_hash_sha256_data(self):
        result = _hash_sha256(b"hello")
        assert result == (
            "2cf24dba5fb0a30e26e83b2ac5b9e29e"
            "1b161e5c1fa7425e73043362938b9824"
        )

    def test_hmac_sha256(self):
        result = _hmac_sha256("data", b"secret")
        assert len(result) == 32  # SHA-256 always 32 bytes

    def test_build_sign_key_deterministic(self):
        params1 = _build_sign_params(OPTS, FIXED_TIME)
        params2 = _build_sign_params(OPTS, FIXED_TIME)
        key1 = _build_sign_key(params1)
        key2 = _build_sign_key(params2)
        assert key1 == key2
        assert len(key1) == 32

    def test_build_sign_key_different_date(self):
        ts1 = datetime(2024, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 4, 16, 10, 0, 0, tzinfo=timezone.utc)
        params1 = _build_sign_params(OPTS, ts1)
        params2 = _build_sign_params(OPTS, ts2)
        key1 = _build_sign_key(params1)
        key2 = _build_sign_key(params2)
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

    def test_no_double_encoding(self):
        req = httpx.Request("GET", "https://example.com/v1/vpcs/some%20path")
        path = _canonical_path(req)
        assert "%2520" not in path
        assert "%20" in path


class TestCanonicalQuery:
    def test_no_params(self):
        req = httpx.Request("GET", "https://example.com/v2/zones")
        assert _canonical_query(req) == ""

    def test_sorted_params(self):
        req = httpx.Request(
            "GET", "https://example.com/v2/zones?name=test&limit=10",
        )
        qs = _canonical_query(req)
        assert "limit" in qs
        assert "name" in qs
        # 'limit' should come before 'name' alphabetically
        assert qs.index("limit") < qs.index("name")

    def test_special_chars_encoded(self):
        req = httpx.Request(
            "GET", "https://example.com/test?key=hello world",
        )
        qs = _canonical_query(req)
        assert "hello%20world" in qs

    def test_duplicate_keys_preserved(self):
        req = httpx.Request(
            "GET", "https://example.com/v1?tag=b&tag=a&name=test",
        )
        qs = _canonical_query(req)
        assert "tag=b" in qs
        assert "tag=a" in qs
        assert "name=test" in qs

    def test_post_no_body_returns_empty(self):
        req = httpx.Request(
            "POST", "https://example.com/v1?action=start",
        )
        assert _canonical_query(req) == ""


class TestUsePayloadForQuery:
    def test_post_no_body(self):
        req = httpx.Request(
            "POST", "https://example.com/v1?action=start",
        )
        assert _use_payload_for_query(req) is True

    def test_post_with_body(self):
        req = httpx.Request(
            "POST", "https://example.com/v1",
            content=b'{"name": "test"}',
        )
        assert _use_payload_for_query(req) is False

    def test_get_never_uses_payload(self):
        req = httpx.Request("GET", "https://example.com/v1?x=1")
        assert _use_payload_for_query(req) is False


class TestSignRequest:
    def test_adds_authorization_header(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        assert "authorization" in req.headers
        assert req.headers["authorization"].startswith(
            SIGN_ALGORITHM_HMAC_SHA256,
        )

    def test_adds_sdk_date_header(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        assert req.headers["x-sdk-date"] == FIXED_DT_STR

    def test_adds_host_header(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        assert req.headers["host"] == "dns.eu-de.otc.t-systems.com"

    def test_authorization_contains_credential(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        assert f"Credential={OPTS.access_key}/" in auth

    def test_authorization_contains_signed_headers(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        assert "SignedHeaders=" in auth
        assert "host" in auth
        assert "x-sdk-date" in auth

    def test_authorization_contains_signature(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        assert "Signature=" in auth
        # Signature is hex, 64 chars
        sig = auth.split("Signature=")[1]
        assert len(sig) == 64

    def test_deterministic_signature(self):
        """Same request + same timestamp = same signature."""
        req1 = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        req2 = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req1, OPTS, timestamp=FIXED_TIME)
        sign_request(req2, OPTS, timestamp=FIXED_TIME)
        assert req1.headers["authorization"] == req2.headers["authorization"]

    def test_different_timestamp_different_signature(self):
        ts1 = datetime(2024, 4, 15, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 4, 15, 11, 0, 0, tzinfo=timezone.utc)
        req1 = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        req2 = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
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
        assert req.headers["authorization"].startswith(
            SIGN_ALGORITHM_HMAC_SHA256,
        )

    def test_scope_format(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        expected_scope = f"{FIXED_DATE_STR}/eu-de/dns/sdk_request"
        assert expected_scope in auth

    def test_whitespace_trimmed_from_keys(self):
        opts = SignOptions(
            access_key="  AK_PADDED  ",
            secret_key="  SK_PADDED  ",
            region_name="eu-de",
            service_name="dns",
        )
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, opts, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        assert "Credential=AK_PADDED/" in auth


class TestReSignRequest:
    def test_re_sign_overwrites_date(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        old_date = req.headers["x-sdk-date"]

        ts2 = datetime(2024, 4, 15, 10, 31, 0, tzinfo=timezone.utc)
        re_sign_request(req, OPTS, timestamp=ts2)
        assert req.headers["x-sdk-date"] != old_date
        assert req.headers["x-sdk-date"] == "20240415T103100Z"

    def test_re_sign_produces_new_authorization(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        old_auth = req.headers["authorization"]

        ts2 = datetime(2024, 4, 15, 10, 31, 0, tzinfo=timezone.utc)
        re_sign_request(req, OPTS, timestamp=ts2)
        assert req.headers["authorization"] != old_auth


class TestAlgorithmValidation:
    def test_unsupported_algorithm_raises(self):
        opts = SignOptions(
            access_key="AK",
            secret_key="SK",
            sign_algorithm="UNSUPPORTED-ALG",
        )
        req = httpx.Request("GET", "https://example.com/test")
        with pytest.raises(ValueError, match="Unsupported"):
            sign_request(req, opts)

    def test_default_algorithm(self):
        req = httpx.Request(
            "GET", "https://dns.eu-de.otc.t-systems.com/v2/zones",
        )
        sign_request(req, OPTS, timestamp=FIXED_TIME)
        auth = req.headers["authorization"]
        assert auth.startswith(SIGN_ALGORITHM_HMAC_SHA256)


class TestSignKeyCache:
    def test_cached_key_matches_uncached(self):
        opts_cached = SignOptions(
            access_key="AK",
            secret_key="SK_CACHE_TEST",
            region_name="eu-de",
            service_name="vpc",
            enable_cache_sign_key=True,
        )
        opts_uncached = SignOptions(
            access_key="AK",
            secret_key="SK_CACHE_TEST",
            region_name="eu-de",
            service_name="vpc",
            enable_cache_sign_key=False,
        )
        params_cached = _build_sign_params(opts_cached, FIXED_TIME)
        params_uncached = _build_sign_params(opts_uncached, FIXED_TIME)

        key_cached = _derive_signing_key(params_cached)
        key_uncached = _derive_signing_key(params_uncached)
        assert key_cached == key_uncached

    def test_cache_returns_same_key_same_day(self):
        opts = SignOptions(
            access_key="AK",
            secret_key="SK_SAME_DAY",
            region_name="eu-de",
            service_name="vpc",
            enable_cache_sign_key=True,
        )
        ts1 = datetime(2024, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 6, 15, 20, 0, 0, tzinfo=timezone.utc)

        params1 = _build_sign_params(opts, ts1)
        params2 = _build_sign_params(opts, ts2)

        key1 = _derive_signing_key(params1)
        key2 = _derive_signing_key(params2)
        assert key1 == key2

    def test_cache_invalidates_on_new_day(self):
        opts = SignOptions(
            access_key="AK",
            secret_key="SK_NEW_DAY",
            region_name="eu-de",
            service_name="vpc",
            enable_cache_sign_key=True,
        )
        ts1 = datetime(2024, 6, 15, 23, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 6, 16, 1, 0, 0, tzinfo=timezone.utc)

        params1 = _build_sign_params(opts, ts1)
        params2 = _build_sign_params(opts, ts2)

        key1 = _derive_signing_key(params1)
        key2 = _derive_signing_key(params2)
        assert key1 != key2


class TestTimeOffset:
    def test_offset_shifts_signing_time(self):
        opts_no_offset = SignOptions(
            access_key="AK",
            secret_key="SK",
            region_name="eu-de",
            service_name="vpc",
            time_offset_seconds=0,
        )
        opts_with_offset = SignOptions(
            access_key="AK",
            secret_key="SK",
            region_name="eu-de",
            service_name="vpc",
            time_offset_seconds=3600,
        )
        req1 = httpx.Request(
            "GET", "https://vpc.eu-de.otc.t-systems.com/v1/vpcs",
        )
        req2 = httpx.Request(
            "GET", "https://vpc.eu-de.otc.t-systems.com/v1/vpcs",
        )
        sign_request(req1, opts_no_offset, timestamp=FIXED_TIME)
        sign_request(req2, opts_with_offset, timestamp=FIXED_TIME)
        # Same timestamp but offset makes them different
        assert req1.headers["authorization"] != req2.headers["authorization"]
        assert req1.headers["x-sdk-date"] != req2.headers["x-sdk-date"]
