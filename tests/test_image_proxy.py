"""Tests for the image proxy module."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from kikusan.web.image_proxy import (
    ALLOWED_HOSTS,
    ImageCache,
    ImageProxyService,
    validate_image_url,
)


class TestValidateImageUrl:
    def test_allowed_host(self):
        url = "https://lh3.googleusercontent.com/some-image"
        assert validate_image_url(url) == url

    def test_allowed_host_ytimg(self):
        url = "https://i.ytimg.com/vi/abc/maxresdefault.jpg"
        assert validate_image_url(url) == url

    def test_allowed_host_ggpht(self):
        url = "https://yt3.ggpht.com/channel-pic"
        assert validate_image_url(url) == url

    def test_disallowed_host(self):
        assert validate_image_url("https://evil.com/image.jpg") is None

    def test_http_scheme_allowed(self):
        url = "http://lh3.googleusercontent.com/img"
        assert validate_image_url(url) == url

    def test_bad_scheme(self):
        assert validate_image_url("ftp://lh3.googleusercontent.com/img") is None
        assert validate_image_url("javascript:alert(1)") is None

    def test_malformed_url(self):
        assert validate_image_url("") is None
        assert validate_image_url("not-a-url") is None

    def test_no_host(self):
        assert validate_image_url("https://") is None


class TestImageCache:
    def test_put_and_get(self):
        cache = ImageCache()
        cache.put("url1", b"data", "image/png")
        result = cache.get("url1")
        assert result == (b"data", "image/png")

    def test_miss(self):
        cache = ImageCache()
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = ImageCache(ttl=0)
        cache.put("url1", b"data", "image/png")
        # TTL=0 means immediately expired
        assert cache.get("url1") is None

    def test_lru_eviction(self):
        cache = ImageCache(max_entries=2)
        cache.put("url1", b"d1", "image/png")
        cache.put("url2", b"d2", "image/png")
        cache.put("url3", b"d3", "image/png")  # evicts url1
        assert cache.get("url1") is None
        assert cache.get("url2") is not None
        assert cache.get("url3") is not None

    def test_lru_access_refreshes(self):
        cache = ImageCache(max_entries=2)
        cache.put("url1", b"d1", "image/png")
        cache.put("url2", b"d2", "image/png")
        cache.get("url1")  # refresh url1
        cache.put("url3", b"d3", "image/png")  # evicts url2 (least recent)
        assert cache.get("url1") is not None
        assert cache.get("url2") is None
        assert cache.get("url3") is not None

    def test_put_updates_existing(self):
        cache = ImageCache()
        cache.put("url1", b"old", "image/png")
        cache.put("url1", b"new", "image/jpeg")
        result = cache.get("url1")
        assert result == (b"new", "image/jpeg")


class TestImageProxyService:
    @pytest.mark.asyncio
    async def test_fetch_success(self):
        service = ImageProxyService()
        try:
            mock_response = httpx.Response(
                200,
                content=b"fake-image-data",
                headers={"content-type": "image/jpeg"},
                request=httpx.Request("GET", "https://lh3.googleusercontent.com/img"),
            )
            with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response):
                data, content_type = await service.fetch("https://lh3.googleusercontent.com/img")
            assert data == b"fake-image-data"
            assert content_type == "image/jpeg"
        finally:
            await service.close()

    @pytest.mark.asyncio
    async def test_fetch_caches_result(self):
        service = ImageProxyService()
        try:
            mock_response = httpx.Response(
                200,
                content=b"cached-data",
                headers={"content-type": "image/png"},
                request=httpx.Request("GET", "https://lh3.googleusercontent.com/img"),
            )
            mock_get = AsyncMock(return_value=mock_response)
            with patch.object(service._client, "get", mock_get):
                await service.fetch("https://lh3.googleusercontent.com/img")
                # Second fetch should use cache
                data, ct = await service.fetch("https://lh3.googleusercontent.com/img")
            assert data == b"cached-data"
            assert mock_get.call_count == 1
        finally:
            await service.close()

    @pytest.mark.asyncio
    async def test_fetch_rejects_non_image(self):
        service = ImageProxyService()
        try:
            mock_response = httpx.Response(
                200,
                content=b"<html>not an image</html>",
                headers={"content-type": "text/html"},
                request=httpx.Request("GET", "https://lh3.googleusercontent.com/img"),
            )
            with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response):
                with pytest.raises(ValueError, match="not an image"):
                    await service.fetch("https://lh3.googleusercontent.com/img")
        finally:
            await service.close()

    @pytest.mark.asyncio
    async def test_fetch_propagates_http_error(self):
        service = ImageProxyService()
        try:
            mock_response = httpx.Response(
                404,
                request=httpx.Request("GET", "https://lh3.googleusercontent.com/img"),
            )
            with patch.object(service._client, "get", new_callable=AsyncMock, return_value=mock_response):
                with pytest.raises(httpx.HTTPStatusError):
                    await service.fetch("https://lh3.googleusercontent.com/img")
        finally:
            await service.close()


class TestApiImageProxy:
    @pytest.mark.asyncio
    async def test_success(self):
        from kikusan.web.app import api_image_proxy

        mock_service = AsyncMock()
        mock_service.fetch = AsyncMock(return_value=(b"img-bytes", "image/webp"))

        with patch("kikusan.web.app._image_proxy", mock_service):
            response = await api_image_proxy(url="https://lh3.googleusercontent.com/test")

        assert response.body == b"img-bytes"
        assert response.media_type == "image/webp"
        assert response.headers["cache-control"] == "public, max-age=86400"

    @pytest.mark.asyncio
    async def test_bad_url_returns_400(self):
        from kikusan.web.app import api_image_proxy

        with pytest.raises(httpx.HTTPStatusError if False else Exception) as exc_info:
            await api_image_proxy(url="https://evil.com/bad")
        from fastapi import HTTPException
        assert isinstance(exc_info.value, HTTPException)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_upstream_failure_returns_502(self):
        from kikusan.web.app import api_image_proxy

        mock_service = AsyncMock()
        mock_service.fetch = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("kikusan.web.app._image_proxy", mock_service):
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                await api_image_proxy(url="https://lh3.googleusercontent.com/test")
            assert exc_info.value.status_code == 502
