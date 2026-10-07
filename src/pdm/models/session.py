from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import urllib.parse
from contextlib import closing
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

import hishel
import hishel.httpx
import httpx
from unearth.fetchers import PyPIClient
from unearth.utils import commonprefix, split_auth_from_url

from pdm.__version__ import __version__
from pdm.termui import logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ssl import SSLContext

    from hishel import Request as HishelRequest
    from hishel._core._storages._sync_base import SyncBaseStorage

    from pdm._types import RepositoryConfig


def _create_truststore_ssl_context() -> SSLContext | None:
    try:
        import ssl
    except ImportError:
        return None

    try:
        import truststore
    except ImportError:
        return None

    import certifi

    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(certifi.where())
    return ctx


_ssl_context = _create_truststore_ssl_context()
CACHES_TTL = 7 * 24 * 60 * 60  # 7 days
MAX_RETRIES = 4

# Prefix/version for cache scopes. Bump this if the key derivation changes so
# that entries produced by an older layout can never be matched by accident.
CACHE_SCOPE_VERSION = "pdm1"
# Scope tag for requests that do not carry an Authorization header.
ANONYMOUS_AUTH_SCOPE = "anonymous"
# Index identity for hosts that are not a configured index (e.g. file hosts).
EXTERNAL_INDEX_SCOPE = "external"
_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}


def _normalize_origin(scheme: str, hostname: str | None, port: int | None) -> tuple[str, str, int | None]:
    scheme = scheme.lower()
    host = (hostname or "").lower()
    # urlsplit() leaves the port unset when it is omitted from the URL, so
    # normalize default ports explicitly to keep origins comparable.
    if port is None:
        port = _DEFAULT_PORTS.get(scheme)
    return scheme, host, port


class CacheScope:
    """Derive a stable cache scope for an outgoing request.

    The scope combines two independent dimensions:

        * the *index identity* the request belongs to (the source name of the
          configured index), so that switching from one index to another one
          never reuses the previous index's entries, even when a URL happens to
          be served by both;
        * the *authentication scope*, a digest of the request's Authorization
          header, so that responses fetched with different credentials (or
          without credentials) are never mixed.

    Requests to hosts that are not configured as indexes (package files hosted
    on a CDN, files.pythonhosted.org, ...) fall into the shared
    ``external`` identity and are only separated by their auth scope. This
    keeps the cross-project reuse of public artifacts identical to a plain
    URL-keyed cache.

    A scope is purely a function of the current sources configuration and the
    request itself, so it is deterministic across processes: entries written
    by a previous run are reused when the configuration matches and are simply
    left untouched (never deleted, never served to another scope) when it does
    not.
    """

    def __init__(self, sources: list[RepositoryConfig]) -> None:
        # (scheme, host, port, index_path, source_name)
        self._records: list[tuple[str, str, int | None, str, str]] = []
        for source in sources:
            if not source.url:
                continue
            # Strip userinfo: credentials live in the Authorization header and
            # must not influence index identity matching.
            _, url_without_auth = split_auth_from_url(source.url)
            parsed = urllib.parse.urlsplit(url_without_auth)
            scheme, host, port = _normalize_origin(parsed.scheme, parsed.hostname, parsed.port)
            path = parsed.path or "/"
            self._records.append((scheme, host, port, path, source.name))

    @staticmethod
    def _is_within(target_path: str, index_path: str) -> bool:
        prefix = index_path if index_path.endswith("/") else index_path + "/"
        return target_path == index_path.rstrip("/") or target_path.startswith(prefix)

    def index_identity(self, url: str) -> str:
        """Return the source name an URL belongs to.

        Matching follows the same rules as credential lookup in
        :mod:`pdm.models.auth`: same scheme/host/port, preferring the index
        whose path is a prefix of the request path, otherwise the one sharing
        the longest common path prefix.
        """
        parsed = urllib.parse.urlsplit(url)
        scheme, host, port = _normalize_origin(parsed.scheme, parsed.hostname, parsed.port)
        target_path = parsed.path or "/"
        same_origin = [
            record
            for record in self._records
            if record[0] == scheme and record[1] == host and record[2] == port
        ]
        if not same_origin:
            return EXTERNAL_INDEX_SCOPE
        prefix_matches = [record for record in same_origin if self._is_within(target_path, record[3])]
        if prefix_matches:
            # The most specific index wins for path-based multi-tenancy.
            return max(prefix_matches, key=lambda record: len(record[3]))[4]
        # Downloads may be served outside of the index path (e.g. /packages
        # next to /simple); associate them with the closest index on the host.
        return max(
            same_origin,
            key=lambda record: commonprefix(record[3].rstrip("/"), target_path.rstrip("/")).rfind("/"),
        )[4]

    def scope_for(self, url: str, authorization: str | None = None) -> str:
        if authorization:
            auth_scope = "auth-" + hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:16]
        else:
            auth_scope = ANONYMOUS_AUTH_SCOPE
        return f"{CACHE_SCOPE_VERSION}|{self.index_identity(url)}|{auth_scope}"


class _ScopedSyncCacheProxy(hishel.SyncCacheProxy):
    """A :class:`hishel.SyncCacheProxy` that keys entries by (scope, URL)."""

    def __init__(
        self,
        request_sender: Callable[[HishelRequest], Any],
        *,
        storage: SyncBaseStorage | None = None,
        scope: CacheScope,
    ) -> None:
        super().__init__(request_sender, storage=storage)
        self._scope = scope

    def _get_key_for_request(self, request: HishelRequest) -> str:
        if self.policy.use_body_key or request.metadata.get("hishel_body_key"):
            # The parent implementation consumes and re-winds the request
            # stream while hashing the body, so it must only run once.
            body_key = super()._get_key_for_request(request)
            material = f"body:{self._scope.scope_for(str(request.url))}|{body_key}"
        else:
            authorization = request.headers.get("authorization") or ""
            scope = self._scope.scope_for(str(request.url), authorization)
            material = f"{scope}|{request.url}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


class _ScopedSyncCacheTransport(hishel.httpx.SyncCacheTransport):
    """SyncCacheTransport wired to a :class:`CacheScope`."""

    def __init__(
        self,
        next_transport: httpx.BaseTransport,
        *,
        storage: SyncBaseStorage | None,
        scope: CacheScope,
    ) -> None:
        super().__init__(next_transport=next_transport, storage=storage)
        # Replace the proxy created by the parent with one that derives
        # scope-aware cache keys; both share the same storage and policy.
        self._cache_proxy = _ScopedSyncCacheProxy(
            self.request_sender,
            storage=storage,
            scope=scope,
        )


@cache
def _get_transport(
    verify: bool | SSLContext | str = True,
    cert: tuple[str, str | None] | None = None,
    proxy: httpx.Proxy | None = None,
) -> httpx.BaseTransport:
    return httpx.HTTPTransport(verify=verify, cert=cert, trust_env=True, proxy=proxy, retries=MAX_RETRIES)


class ThreadedSyncSqliteStorage(hishel.SyncSqliteStorage):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._local_conns: dict[int, sqlite3.Connection] = {}
        self._lock = threading.Lock()
        self._initialized = False
        super().__init__(*args, **kwargs)

    @property
    def connection(self) -> sqlite3.Connection | None:
        return self._local_conns.get(threading.get_ident())

    @connection.setter
    def connection(self, conn: sqlite3.Connection | None) -> None:
        if conn is not None:
            self._local_conns[threading.get_ident()] = conn

    def close(self) -> None:
        with self._lock:
            while self._local_conns:
                _, conn = self._local_conns.popitem()
                conn.close()

    def _ensure_connection(self) -> sqlite3.Connection:
        """
        Ensure connection is established and database is initialized.

        We need to create connections with check_same_thread=False for the sake of close(),
        so we have to open-code the entire implementation here.
        """

        # we take a lock _despite_ using TLS to protect against concurrent close(), otherwise we have a TOCTOU
        # this is kinda ugly and defeats the purpose of using TLS, but eh
        with self._lock:
            if self.connection is None:
                # Create cache directory and resolve full path on first connection
                self.database_path.parent.mkdir(parents=True, exist_ok=True)
                full_path = self.database_path.resolve()
                conn = sqlite3.connect(str(full_path), check_same_thread=False)
                with closing(conn.cursor()) as cursor:
                    cursor.execute("PRAGMA foreign_keys=ON")
                self.connection = conn
            if not self._initialized:
                self._initialize_database()
                self._initialized = True
            return self.connection


class PDMPyPIClient(PyPIClient):
    def __init__(self, *, sources: list[RepositoryConfig], cache_dir: Path | None = None, **kwargs: Any) -> None:
        import shutil

        from httpx._utils import URLPattern
        from unearth.fetchers.sync import LocalFSTransport

        # Isolate cache entries by index identity and authentication scope,
        # so that switching indexes or updating credentials never reuses
        # responses fetched for a previous configuration.
        cache_scope = CacheScope(sources)

        if cache_dir is None:

            def cache_transport(transport: httpx.BaseTransport) -> httpx.BaseTransport:
                return transport
        else:
            # clean up old (pre-hishel 1.0) cache
            cache_db = cache_dir / "http-cache.db"
            if not cache_db.exists():
                for f in cache_dir.iterdir():
                    if not f.name.startswith("http-cache.db"):
                        if f.is_dir():
                            shutil.rmtree(f, ignore_errors=True)
                        else:
                            f.unlink()
            storage = ThreadedSyncSqliteStorage(database_path=cache_db, default_ttl=CACHES_TTL)

            def cache_transport(transport: httpx.BaseTransport) -> httpx.BaseTransport:
                return _ScopedSyncCacheTransport(next_transport=transport, storage=storage, scope=cache_scope)

        mounts: dict[str, httpx.BaseTransport] = {"file://": LocalFSTransport()}
        self._trusted_host_ports: set[tuple[str, int | None]] = set()
        self._proxy_map = {
            URLPattern(key): proxy for key, proxy in self._get_proxy_map(None, allow_env_proxies=True).items()
        }
        self._proxy_map = dict(sorted(self._proxy_map.items()))
        for s in sources:
            assert s.url is not None
            url = httpx.URL(s.url)
            if s.verify_ssl is False:
                self._trusted_host_ports.add((url.host, url.port))
            if s.name == "pypi":
                kwargs["transport"] = self._transport_for(s)
                continue
            mounts[f"{url.scheme}://{url.netloc.decode('ascii')}/"] = cache_transport(self._transport_for(s))
        mounts.update(kwargs.pop("mounts", None) or {})
        kwargs.update(follow_redirects=True)

        httpx.Client.__init__(self, mounts=mounts, **kwargs)

        self.headers["User-Agent"] = self._make_user_agent()
        self.event_hooks["response"].append(self.on_response)
        self._transport = cache_transport(self._transport)  # type: ignore[has-type]

    def _transport_for(self, source: RepositoryConfig) -> httpx.BaseTransport:
        if source.verify_ssl is False:
            verify: str | bool | SSLContext = False
        elif source.ca_certs:
            verify = source.ca_certs
        else:
            verify = os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("CURL_CA_BUNDLE") or _ssl_context or True
        if source.client_cert:
            cert = (source.client_cert, source.client_key)
        else:
            cert = None
        source_url = httpx.URL(cast(str, source.url))
        proxy = next((proxy for pattern, proxy in self._proxy_map.items() if pattern.matches(source_url)), None)
        return _get_transport(verify=verify, cert=cert, proxy=proxy)

    def _make_user_agent(self) -> str:
        import platform

        return f"pdm/{__version__} {platform.python_implementation()}/{platform.python_version()} {platform.system()}/{platform.release()}"

    def on_response(self, response: httpx.Response) -> None:
        from unearth.utils import ARCHIVE_EXTENSIONS

        if response.extensions.get("from_cache"):
            response.from_cache = True  # type: ignore[attr-defined]
            if response.url.path.endswith(ARCHIVE_EXTENSIONS):
                logger.info("Using cached response for %s", response.url)
