# 索引凭据切换后的会话缓存隔离

> **Workspace:** /Users/ding/Documents/swe/0910061/project-08

---

**User**

项目维护者在同一 PDM 进程中切换私有包索引或更新凭据后再次解析依赖时，HTTP 会话缓存可能复用切换前的响应，把旧索引的 401、包元数据或下载结果带到新配置。请让会话缓存按索引身份和认证范围隔离，配置变化后不复用不匹配的响应；认证失败、网络中断或进程重启时保留可安全复用的旧缓存但不泄露给新索引，公开 PyPI、额外索引、离线缓存和现有 resolver/install 行为继续兼容。

**Assistant**

I'll start by recalling relevant experience, then explore the PDM codebase to understand the HTTP caching mechanism.Now let me explore the PDM codebase structure to understand the HTTP and caching mechanisms.

toolName: todo_write

status: success

Todos updated: 6 items

toolName: view_folder

status: success

/Users/ding/Documents/swe/0910061/project-08/src/pdm

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/caches.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/auth.py

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/environments/base.py

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

`uv` and Python 3.11 are available. Let me set up a development environment.

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

Now let me inspect hishel's cache key generation and controller behavior.

toolName: Shell

status: success

toolName: Shell

status: success

toolName: view_folder

status: success

/Users/ding/Documents/swe/0910061/project-08/.venv/lib/python3.11/site-packages/hishel/_core

toolName: Shell

status: success

toolName: Shell

status: success

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/.venv/lib/python3.11/site-packages/hishel/_sync_cache.py

Let me examine hishel's spec policy, storage schema, and httpx integration to understand entry matching.

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/.venv/lib/python3.11/site-packages/hishel/_core/_storages/_sync_sqlite.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/.venv/lib/python3.11/site-packages/hishel/_sync_httpx.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/.venv/lib/python3.11/site-packages/hishel/_policies.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/.venv/lib/python3.11/site-packages/hishel/_core/_spec.py

Now let me examine how unearth applies auth to requests (to confirm `Authorization` reaches the transport layer).

toolName: Shell

status: success

toolName: view_files

status: success

filePath: /var/folders/c9/fvr80z_j2sz6s4j877kcqpfc0000gn/T/trae-agent-toolhost-501/jobs/job-3216f24cd4a6486d95d3ded0c652876b/output.log

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/.venv/lib/python3.11/site-packages/unearth/auth.py

Let me look at how PDM handles offline mode and where `enable_cache`/`offline` state is used.

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/core.py

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

Now let me look at `RepositoryConfig` and how sources are built.

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/_types.py

Now let me review existing tests related to session/caching and the test session builder.

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/pytest.py

toolName: Shell

status: success

toolName: Shell

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/tests/models/test_session.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/repositories/pypi.py

toolName: Shell

status: success

toolName: Shell

status: success

Let me see the rest of `get_finder` to confirm session construction with custom sources.

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/environments/base.py

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/project/core.py

toolName: search_by_regex

status: success

Let me read the remainder of hishel's `CacheMiss.next` storage rules.

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/.venv/lib/python3.11/site-packages/hishel/_core/_spec.py

I now have a complete picture of the bug and hishel's internals. Let me record the plan and implement.

toolName: todo_write

status: success

Todos updated: 6 items

Now implementing the scoped cache in [session.py](file:///Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py):

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py

changes: undefined

Now add the scope resolver, scoped proxy, and scoped transport classes:

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py

changes: undefined

Now wire the scoped transport into `PDMPyPIClient`:

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py

changes: undefined

Let me quickly sanity-check the implementation with a manual script:

toolName: Shell

status: success

toolName: Shell

status: success

The 4th call is hishel's default shared-cache policy (authenticated responses aren't stored unless explicitly public — real PyPI/devpi send `public`, so let me emulate that):

toolName: Shell

status: success

Test-script bug (`raise_after=0` is falsy). Fixing the test harness flag:

toolName: Shell

status: success

External-host requests need the default transport (built from the `pypi` source) — adding it as real projects always do:

toolName: Shell

status: success

toolName: Shell

status: success

Restart reuse works. Let me specifically test whether an unknown credential under network outage incorrectly gets a cached response:

toolName: Shell

status: success

Let me reproduce the exact combined sequence that failed earlier to understand:

toolName: Shell

status: success

Let me re-run the exact second script verbatim to check determinism:

toolName: Shell

status: success

toolName: Shell

status: success

Let me save the exact scenario to a file for precise line numbers:

toolName: Write

status: success

filePath: /tmp/scratch_cache.py

changes: undefined

toolName: Shell

status: success

The failure was my scratch handler returning 401 for anonymous external requests — the cache logic is correct. Let me verify `hishel.Request` is exported for type hints and run the existing session test suite:

toolName: Shell

status: success

Now let me write the formal tests. First check lint config for line length:

toolName: search_by_regex

status: success

toolName: Write

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/tests/models/test_session.py

changes: undefined

toolName: Shell

status: success

Two test-harness issues: cache dir must be pre-created, and let me debug the port matching:

toolName: Shell

status: success

`urlsplit` returns `None` for implicit default ports — I need explicit normalization. Fixing the scope class:

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py

changes: undefined

Now fix the test fixture to create the cache directory:

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/tests/models/test_session.py

changes: undefined

toolName: Shell

status: success

Test artifact — the second client got a fresh transport; assertions checked the first. Reusing one transport across both sessions (shared network):

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/tests/models/test_session.py

changes: undefined

toolName: Shell

status: success

All tests pass. Let me update progress and run the broader non-integration test suite to verify compatibility:

toolName: todo_write

status: success

Todos updated: 6 items

toolName: Shell

status: success

Core suites pass. Now the full non-integration suite:

toolName: Shell

status: success

All 1497 tests pass. Now lint and type checks on the changed files:

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/tests/models/test_session.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/tests/models/test_session.py

changes: undefined

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

Both errors are on pre-existing lines (the cert tuple and `threading.Lock()` assignment present in the original file). Let me confirm they're baseline by running mypy on the whole package and checking with the original version:

toolName: Shell

status: success

Both errors are pre-existing baseline. Let me do a final review of the complete implementation:

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py

The implementation is coherent. Let me re-run the session tests after formatting edits, plus a final full non-integration run to be safe:

toolName: Shell

status: success

All green. Let me review the final diff:

toolName: Shell

status: success

toolName: view_files

status: success

filePath: /var/folders/c9/fvr80z_j2sz6s4j877kcqpfc0000gn/T/trae-agent-toolhost-501/jobs/job-8bac3512d01d45b0a09e619f9eb47545/output.log

Let me do one final end-to-end verification with PDM's real auth object (`PdmBasicAuth`) wired in, to confirm credential rotation through the actual auth flow isolates cache entries:

toolName: Shell

status: success

toolName: todo_write

status: success

Todos updated: 6 items

已完成会话缓存按索引身份和认证范围隔离的改造。

## 根因

[session.py](file:///Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py) 中所有索引（公开 PyPI、私有源、额外索引）和下载请求共用同一个 hishel sqlite 存储，而 hishel 1.x 的默认缓存键只由请求 URL 决定（`sha256(url)`）。因此同一进程中切换索引或轮换凭据后：

- 匿名探测得到的 401（服务器带 `Cache-Control: max-age` 时会被存）可能直接返回给带认证的重试；
- 旧凭据/旧索引的 200 元数据会被新配置按同一 URL 命中；
- 认证头只在响应带 `Vary: Authorization` 时才参与匹配，私有服务器往往不发该头。

## 修改内容（仅 [session.py](file:///Users/ding/Documents/swe/0910061/project-08/src/pdm/models/session.py) 和测试）

1. **新增 `CacheScope`**：根据当前 sources 配置把每个请求映射到 `版本|索引身份|认证范围`：
   - 索引身份：按 scheme/host/port（默认端口归一化）匹配源，路径前缀优先（支持同主机多租户索引），下载路径（如 `/packages`）按最长公共路径归属，未配置主机归为共享的 `external`；源 URL 内嵌的 userinfo 被剥离，不参与身份。
   - 认证范围：取实际发出的 `Authorization` 头的 SHA-256 摘要（不明文存密码），无认证头为 `anonymous`。
2. **新增 `_ScopedSyncCacheProxy` / `_ScopedSyncCacheTransport`**：缓存键改为 `sha256(scope|url)`，在缓存传输层对所有索引挂载和默认传输统一生效（含重定向后的每一跳）。

## 行为保证

- **切换索引/更新凭据**：键不匹配即 miss，绝不复用旧 401、元数据或下载结果；已用真实 `PdmBasicAuth` 轮换密码验证。
- **旧缓存保留不泄露**：旧作用域条目不删除、不服务给新作用域；认证失败、断网时同作用域仍可用（断网测试中未知凭据直接报错而非回落旧响应），恢复后两作用域条目都在；作用域由配置与请求确定性推导，**进程重启后同配置继续命中**。
- **兼容性**：公开 PyPI 与 `files.pythonhosted.org`/CDN 匿名下载仍是跨项目共享的 `external` 作用域；额外索引、resolver/install、`--no-cache`（`cache_dir=None` 时不加缓存层）路径不变；键前缀带版本号 `pdm1`，升级后旧库条目自然失效（由 7 天 TTL 回收）。

## 验证

- 新增 10 个用例（[test_session.py](file:///Users/ding/Documents/swe/0910061/project-08/tests/models/test_session.py)）：身份/作用域单元匹配、同作用域复用、重启复用、匿名 401 不泄露给认证请求、凭据隔离、索引改名切换后不复用且旧缓存保留、外部主机跨索引共享但按凭据隔离、断网保留安全缓存、无缓存目录不缓存。
- 全量非集成测试 **1497 passed**；ruff 检查/格式通过；mypy 仅剩 2 个改动前就存在的基线告警（cert 元组与锁类型，原始文件第 54/60 行）。
