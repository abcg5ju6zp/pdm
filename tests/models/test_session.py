from __future__ import annotations

import base64
import email.utils
from typing import TYPE_CHECKING

import httpx
import pytest

from pdm._types import RepositoryConfig
from pdm.models.session import (
    ANONYMOUS_AUTH_SCOPE,
    CACHE_SCOPE_VERSION,
    EXTERNAL_INDEX_SCOPE,
    CacheScope,
    PDMPyPIClient,
)

if TYPE_CHECKING:
    from pdm.project.core import Project


def _source(name: str, url: str) -> RepositoryConfig:
    return RepositoryConfig(config_prefix="pypi", name=name, url=url)


def _credentials(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


class FakeTransport(httpx.BaseTransport):
    """An in-memory transport that counts every request that hits the network."""

    def __init__(self, *, anonymous_status: int = 200, raising: bool = False) -> None:
        self.anonymous_status = anonymous_status
        self.raising = raising
        self.requests: list[tuple[str, str | None]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self.raising:
            raise httpx.ConnectError("network is unreachable")
        authorization = request.headers.get("authorization")
        self.requests.append((str(request.url), authorization))
        status = self.anonymous_status if not authorization else 200
        return httpx.Response(
            status,
            headers={"cache-control": "public, max-age=3600", "date": email.utils.formatdate(usegmt=True)},
            content=f"body:{authorization or 'anonymous'}".encode(),
        )

    @property
    def call_count(self) -> int:
        return len(self.requests)


@pytest.fixture
def client_factory(tmp_path, monkeypatch):
    cache_dir = tmp_path / "http"
    cache_dir.mkdir(parents=True)
    clients: list[PDMPyPIClient] = []

    def factory(
        sources: list[RepositoryConfig],
        *,
        transport: FakeTransport | None = None,
        cache: bool = True,
    ) -> tuple[PDMPyPIClient, FakeTransport]:
        transport = transport or FakeTransport()
        monkeypatch.setattr(PDMPyPIClient, "_transport_for", lambda self, s: transport)
        client = PDMPyPIClient(sources=sources, cache_dir=cache_dir if cache else None, auth=None)
        clients.append(client)
        return client, transport

    yield factory

    for client in clients:
        client.close()


PYPI = _source("pypi", "https://pypi.org/simple")
PRIVATE = _source("private", "https://index.example.com/simple")
PRIVATE_RENAMED = _source("renamed", "https://index.example.com/simple")
INDEX_URL = "https://index.example.com/simple/demo/"
DOWNLOAD_URL = "https://files.cdn.example.com/packages/demo-1.0.whl"


def test_session_sources_all_proxy(project: Project, mocker, monkeypatch):
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "no_proxy", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("all_proxy", "http://localhost:8888")
    mock_get_transport = mocker.patch("pdm.models.session._get_transport")

    assert project.environment.session is not None
    transport_args = mock_get_transport.call_args
    assert transport_args is not None
    assert transport_args.kwargs["proxy"].url == "http://localhost:8888"

    monkeypatch.setenv("no_proxy", "pypi.org")
    mock_get_transport.reset_mock()
    del project.environment.session
    assert project.environment.session is not None
    transport_args = mock_get_transport.call_args
    assert transport_args is not None
    assert transport_args.kwargs["proxy"] is None


def test_cache_scope_matches_index_identity() -> None:
    scope = CacheScope(
        [
            PYPI,
            _source("a", "https://example.com/a/simple"),
            _source("b", "https://example.com/b/simple"),
            # Credentials embedded in the URL must not affect identity matching.
            _source("c", "https://user:secret@example.com/c/simple"),
        ]
    )
    assert scope.index_identity("https://example.com/a/simple/demo/") == "a"
    assert scope.index_identity("https://example.com/a/simple") == "a"
    assert scope.index_identity("https://example.com/b/simple/demo/") == "b"
    assert scope.index_identity("https://example.com/c/simple/demo/") == "c"
    # Downloads served next to the index path map to the closest index.
    assert scope.index_identity("https://example.com/a/packages/demo-1.0.whl") == "a"
    # Default ports are normalized to the same origin.
    assert scope.index_identity("https://pypi.org:443/simple/demo/") == "pypi"
    # Unknown hosts and non-matching schemes are treated as external.
    assert scope.index_identity("https://files.pythonhosted.org/packages/x.whl") == EXTERNAL_INDEX_SCOPE
    assert scope.index_identity("http://pypi.org/simple/demo/") == EXTERNAL_INDEX_SCOPE


def test_cache_scope_includes_authentication() -> None:
    scope = CacheScope([PRIVATE])
    anonymous = scope.scope_for(INDEX_URL)
    authenticated = scope.scope_for(INDEX_URL, _credentials("user", "secret"))
    assert anonymous == f"{CACHE_SCOPE_VERSION}|private|{ANONYMOUS_AUTH_SCOPE}"
    assert authenticated != anonymous
    # The raw password must never appear in the scope.
    assert "secret" not in authenticated
    # Different credentials yield different scopes, same credential is stable.
    assert authenticated == scope.scope_for(INDEX_URL, _credentials("user", "secret"))
    assert authenticated != scope.scope_for(INDEX_URL, _credentials("user", "rotated"))
    assert authenticated != scope.scope_for(INDEX_URL, _credentials("other", "secret"))


def test_cached_response_reused_within_same_scope(client_factory) -> None:
    client, transport = client_factory([PYPI, PRIVATE])
    assert client.get(INDEX_URL).status_code == 200
    assert client.get(INDEX_URL).status_code == 200
    assert transport.call_count == 1


def test_cache_reused_across_process_restart(client_factory) -> None:
    first, _ = client_factory([PYPI, PRIVATE])
    assert first.get(INDEX_URL).status_code == 200
    first.close()

    second, new_transport = client_factory([PYPI, PRIVATE], transport=FakeTransport())
    response = second.get(INDEX_URL)
    assert response.status_code == 200
    assert new_transport.call_count == 0


def test_anonymous_401_is_not_reused_for_authenticated_request(client_factory) -> None:
    client, transport = client_factory([PYPI, PRIVATE], transport=FakeTransport(anonymous_status=401))

    # The unauthenticated probe receives (and caches) a 401 in its own scope.
    assert client.get(INDEX_URL).status_code == 401
    # The authenticated retry must not be served the anonymous 401.
    response = client.get(INDEX_URL, headers={"Authorization": _credentials("user", "secret")})
    assert response.status_code == 200
    assert transport.call_count == 2


def test_cache_isolated_between_credentials(client_factory) -> None:
    client, transport = client_factory([PYPI, PRIVATE])
    old_auth = _credentials("user", "old-token")
    new_auth = _credentials("user", "new-token")

    assert client.get(INDEX_URL, headers={"Authorization": old_auth}).status_code == 200
    assert client.get(INDEX_URL, headers={"Authorization": new_auth}).status_code == 200
    assert transport.call_count == 2

    # Repeating either request serves the matching scope only.
    assert client.get(INDEX_URL, headers={"Authorization": old_auth}).status_code == 200
    assert client.get(INDEX_URL, headers={"Authorization": new_auth}).status_code == 200
    assert client.get(INDEX_URL, headers={"Authorization": old_auth}).content == b"body:" + old_auth.encode()
    assert transport.call_count == 2


def test_cache_not_reused_after_index_switch_but_old_scope_is_kept(client_factory) -> None:
    old_client, old_transport = client_factory([PYPI, PRIVATE])
    auth = _credentials("user", "token")
    assert old_client.get(INDEX_URL, headers={"Authorization": auth}).status_code == 200
    assert old_transport.call_count == 1
    old_client.close()

    # Same URL, same credentials, but the index has a different identity now.
    switched, switched_transport = client_factory([PYPI, PRIVATE_RENAMED], transport=FakeTransport())
    assert switched.get(INDEX_URL, headers={"Authorization": auth}).status_code == 200
    assert switched_transport.call_count == 1
    switched.close()

    # The previous index's cache is retained and still reusable on its own scope.
    back, back_transport = client_factory([PYPI, PRIVATE], transport=FakeTransport())
    assert back.get(INDEX_URL, headers={"Authorization": auth}).status_code == 200
    assert back_transport.call_count == 0


def test_external_hosts_remain_shared_across_indexes(client_factory) -> None:
    first, transport = client_factory([PYPI, PRIVATE])
    assert first.get(DOWNLOAD_URL).status_code == 200

    second, _ = client_factory(
        [PYPI, _source("other", "https://other.example.com/simple")], transport=transport
    )
    # Anonymous public artifact downloads keep being shared.
    assert second.get(DOWNLOAD_URL).status_code == 200
    assert transport.call_count == 1

    # Authenticated access to the same URL is a different scope, though.
    assert second.get(DOWNLOAD_URL, headers={"Authorization": _credentials("user", "token")}).status_code == 200
    assert transport.call_count == 2


def test_network_outage_keeps_safe_cache_without_leaking_to_other_scope(client_factory) -> None:
    online, _ = client_factory([PYPI, PRIVATE])
    auth = _credentials("user", "token")
    assert online.get(INDEX_URL, headers={"Authorization": auth}).status_code == 200
    online.close()

    offline, _ = client_factory([PYPI, PRIVATE], transport=FakeTransport(raising=True))
    # The fresh response is served without touching the network.
    assert offline.get(INDEX_URL, headers={"Authorization": auth}).status_code == 200
    # An unknown credential scope must not fall back to the cached response.
    with pytest.raises(httpx.ConnectError):
        offline.get(INDEX_URL, headers={"Authorization": _credentials("user", "other-token")})
    # The cached response is still available to its own scope afterwards.
    assert offline.get(INDEX_URL, headers={"Authorization": auth}).status_code == 200


def test_no_cache_dir_disables_http_cache(client_factory) -> None:
    client, transport = client_factory([PYPI, PRIVATE], cache=False)
    assert client.get(INDEX_URL).status_code == 200
    assert client.get(INDEX_URL).status_code == 200
    assert transport.call_count == 2
