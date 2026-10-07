# 候选缓存中断后的安全代际

> **Workspace:** /Users/ding/Documents/swe/0910061/project-07

---

**User**

网络解析或构建过程中，PDM 更新候选元数据或哈希缓存时若进程中止，JSONFileCache 可能被截断；下一次 lock 或 install 读取到残缺缓存后会忽略、报错或重复访问源。请让候选信息和哈希缓存的写入与读取按一次完整代际提交，残缺条目自动丢弃而不影响其他键；失败或取消不覆盖上次有效值，重启后可继续填充，禁用缓存、本地目录、不同 Python 环境和现有 resolver/install 行为保持不变。

**Assistant**

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py

现在查看 `atomic_open_for_write` 工具函数和相关测试，以理解现有机制：

toolName: search_by_regex

status: success

toolName: file_search

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/tests/cli/test_cache.py

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/cli/commands/use.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/project/core.py

toolName: search_by_regex

status: success

查看 git 历史和变更日志，了解缓存文件的演进背景：

toolName: Shell

status: success

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

查看 test_use.py 中对 JSONFileCache 的使用方式，以及测试目录结构：

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/tests/cli/test_use.py

toolName: view_folder

status: success

/Users/ding/Documents/swe/0910061/project-07/tests/models

toolName: todo_write

status: failed

Todos updated: 7 items

toolName: todo_write

status: success

Todos updated: 5 items

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/utils.py

工具函数的失败清理已完备。现在为其增加 `fsync` 参数以保证代际提交的持久性：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/utils.py

changes: undefined

现在改造 [caches.py](file:///Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py) 中的 `JSONFileCache`：

toolName: todo_write

status: success

Todos updated: 5 items

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py

changes: undefined

现在加固 `HashCache` 的读取校验与写入提交：

toolName: todo_write

status: success

Todos updated: 5 items

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py

changes: undefined

核心改动完成。现在添加单元测试验证原子提交与抢救行为：

toolName: todo_write

status: success

Todos updated: 5 items

toolName: Write

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/tests/models/test_caches.py

changes: undefined

修正截断测试中不够确定的切割逻辑：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/tests/models/test_caches.py

changes: undefined

运行新增测试和相关的现有缓存测试：

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

使用 uv 准备测试环境并运行新测试：

toolName: Shell

status: success

环境就绪，运行测试：

toolName: Shell

status: success

3 个失败，先调试抢救逻辑中嵌套条目的问题：

toolName: Shell

status: success

toolName: Shell

status: success

发现两个问题：抢救循环中跳过冒号后未跳过空白导致 `raw_decode` 失败；哈希仅按字符集校验无法识别截断的十六进制。逐一修复：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py

changes: undefined

修复测试中的截断位置：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/tests/models/test_caches.py

changes: undefined

toolName: Shell

status: success

全部通过。运行相关的现有测试套件确认无回归：

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

运行代码质量检查（ruff、mypy）覆盖改动文件：

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

按格式化要求简化日志语句：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py

changes: undefined

toolName: Shell

status: success

直接让 ruff 格式化该文件：

toolName: Shell

status: success

格式化与类型检查通过。确认 uv 解析器对 HashCache 的使用方式没有其他格式假设：

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/resolver/uv.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py

接口兼容。运行完整的非集成测试套件做最终回归确认：

toolName: Shell

status: success

全部 1505 个测试通过。检查 codespell 以及工作区是否留下 uv 构建产物：

toolName: Shell

status: success

codespell 无问题。清理 uv 生成的临时锁文件（不属于本次改动），然后查看最终差异：

toolName: delete_file

status: success

toolName: Shell

status: success

最后做一次端到端崩溃场景模拟验证：

toolName: Shell

status: success

toolName: todo_write

status: success

Todos updated: 5 items

已完成。候选元数据缓存与哈希缓存现在都按"完整代际（generation）"提交，进程中止不再损坏缓存。

## 改动内容

**1. [caches.py — JSONFileCache](file:///Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py#L30-L123)（候选信息缓存）**

- **写入代际提交**：`_write_cache()` 不再直接 `open("w")` 截断原文件，改为写入同目录临时文件 → `flush()` + `fsync()` → `os.replace()` 原子替换。序列化失败、磁盘错误或协程取消时，临时文件被丢弃，上一版缓存原封不动。
- **残缺条目按条丢弃**：读取时先整体解析；遇到残缺 JSON 时用流式解码器（`raw_decode`）从头部逐条恢复完整的 `"key": value`，在第一个被截断的条目处停止——只丢残缺键，前面的键全部保留；非对象类型、完全损坏或无 `{` 的内容则从空缓存开始。
- **重启继续填充**：恢复出的条目进入内存缓存，下一次 `set()` 会把"抢救出的旧条目 + 新条目"作为一个完整代际重新发布，文件恢复为合法 JSON。
- 缓存文件路径、文件名（`package_meta_<python_requires哈希>.json`）和单 JSON 对象格式均未变，旧缓存可直接读取。

**2. [caches.py — HashCache](file:///Users/ding/Documents/swe/0910061/project-07/src/pdm/models/caches.py#L232-L269)（哈希缓存）**

- 写入同样开启 `fsync` 的完整代际提交（原本已有临时文件 + `os.replace`，补上落盘同步）。
- 读取时校验 `algo:digest` 形态，并按哈希算法校验摘要长度（如 sha256 必须为 64 位十六进制）——截断但恰好全是十六进制字符的条目也能识别，丢弃后自动重新计算并覆盖，不会把残缺哈希带到安装校验。

**3. [utils.py — atomic_open_for_write](file:///Users/ding/Documents/swe/0910061/project-07/src/pdm/utils.py#L163-L202)**：新增默认关闭的 `fsync` 参数，仅两处缓存写入启用，toml 等其他调用方行为不变。

## 保持不变的部分

- `EmptyCandidateInfoCache` / `EmptyHashCache`（`--no-cache`）仍是 no-op；
- 本地目录/本地文件不进缓存（`_get_key` 的 KeyError 路径、`_should_cache`）；
- 不同 Python 环境仍按 `python_requires` 分文件；
- resolver、uv 解析器、installer 调用的 `get/set/get_hash` 接口零变化。

## 验证

新增 [test_caches.py](file:///Users/ding/Documents/swe/0910061/project-07/tests/models/test_caches.py) 18 个用例（正常持久化、尾部截断抢救、嵌套残缺条目单独丢弃、写入失败保留上代、垃圾文件后继续填充、哈希残缺/长度校验、空缓存 no-op 等）；全量非集成测试 **1505 passed**，ruff / ruff-format / mypy / codespell 均通过，并额外做了中断-重启场景的端到端模拟。
