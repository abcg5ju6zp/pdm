# 安装事务失败后的环境与缓存回滚

> **Workspace:** /Users/ding/Documents/swe/0910061/project-09

---

**User**

一次项目安装会先下载依赖，随后 wheel 解压、脚本生成或环境元数据写入可能失败，虚拟环境只装了一半，缓存却把失败包标成可复用，下一次 install 因而跳过缺失步骤。请在临时环境和候选缓存中完成依赖、脚本和元数据校验，全部成功后再切换活动环境；失败、取消、磁盘不足或进程中止都恢复上一份可用环境并清理候选，已确认缓存不能被失败批次覆盖。editable、本地路径、PEP 582、镜像源和只读检查保持兼容，重试应确定地继续或重新执行未确认步骤。

**Assistant**

我先查看相关经验，然后分析 PDM 代码库的安装架构。经验已获取（核心教训：前置条件未确认不能宣称成功、原子化清理与执行、回退需可诊断）。现在分析 PDM 安装器架构。

toolName: todo_write

status: success

Todos updated: 6 items

toolName: view_folder

status: success

/Users/ding/Documents/swe/0910061/project-09/src/pdm

toolName: view_folder

status: success

/Users/ding/Documents/swe/0910061/project-09/src/pdm/installers

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/synchronizers.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/base.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/manager.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/installers.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/uninstallers.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/cached_package.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/caches.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/environments/base.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/environments/python.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/cli/commands/install.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/core.py

toolName: search_by_regex

status: success

toolName: Shell

status: success

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_installer_manager.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_installer.py

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/utils.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/project/core.py

现在查看 `.checksum` 的写入位置、local 环境（PEP 582）布局，以及 config 默认项。

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/environments/local.py

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/project/config.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/uv.py

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/__init__.py

查看同步器相关测试与 conftest 基建，确认改动影响面。

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_synchronizer_base.py

设计已清晰。查看 markers/EnvSpec 以便在目标环境上正确做依赖闭包校验。

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/markers.py

方案已成形。更新任务清单并开始实现：候选/确认缓存分离 → 暂存事务（日志、校验、提交、回滚、崩溃恢复）→ 同步器集成。

toolName: todo_write

status: success

Todos updated: 7 items

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/exceptions.py

开始实现。先改造 `CachedPackage` 与 `PackageCache`（候选/确认分离、校验、原子提升、残留清扫）。

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/cached_package.py

changes: undefined

给 `CachedPackage` 增加完整性校验方法：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/cached_package.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/cached_package.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/cached_package.py

changes: undefined

现在重写 `PackageCache`，实现候选提取、严格校验、原子提升与残留清扫：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/caches.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/caches.py

changes: undefined

现在改造底层 `install_wheel` 与 `InstallDestination`，支持候选包注入、清单收集与延迟引用登记：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/installers.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/installers.py

changes: undefined

现在更新 `install_wheel` 签名与缓存包使用逻辑：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/installers.py

changes: undefined

核心事务模块现在创建。先给 `StashedRemovePaths` 增加可指定 stash 根目录的参数（事务回滚需要 stash 与事务同生命周期）：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/uninstallers.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/uninstallers.py

changes: undefined

现在创建事务核心模块：

toolName: Write

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

初稿有几处需要修正：脚本槽位识别、更新操作的线程安全匹配、`from_dist` 透传 stash_root、崩溃恢复的提交/完成双事件。逐一修复：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

重写提交/回滚的事件日志，加入意图+完成双事件以支持进程崩溃后的确定性恢复：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

现在重放逻辑改为基于意图/完成双事件，并简化跨进程恢复：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

更新 `StashedRemovePaths.from_dist` 支持 `stash_root`：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/uninstallers.py

changes: undefined

现在把事务接入 `InstallManager`：

toolName: Write

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/manager.py

changes: undefined

补充事务侧的 `discard_op`，然后更新 BaseSynchronizer 与配置：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/manager.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/manager.py

changes: undefined

现在给 `BaseSynchronizer` 增加 `atomic` 参数并将事务传给 manager：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/base.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/base.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/base.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/project/config.py

changes: undefined

现在把事务编排接入 `Synchronizer.synchronize()`：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/synchronizers.py

changes: undefined

复查整个事务文件，确认逻辑一致：

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

发现一个关键问题：symlink 模式下暂存链接指向候选项路径，提升（rename）后会悬空。需要在提升后重写暂存区符号链接指向确认缓存：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

先做语法检查并运行既有安装器测试：

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

toolName: Shell

status: success

环境就绪。运行编译检查与既有安装器相关测试：

toolName: Shell

status: success

保持非事务路径原行为（缓存获取仍在 `install_wheel` 内部），修复 mock 兼容：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/manager.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/manager.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/manager.py

changes: undefined

toolName: Shell

status: success

候选包哈希校验与实际 wheel 不符，直接调试 fixture wheel：

toolName: Shell

status: success

RECORD 哈希使用的是 urlsafe-base64 而非 hex，修正校验算法：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/cached_package.py

changes: undefined

toolName: Shell

status: success

既有测试全部通过。运行 CLI 安装端到端测试与缓存测试：

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

端到端机制就绪。查看 CLI 测试基建（local_finder、project/pdm fixtures）以编写事务测试：

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/conftest.py

查看 CLI 安装测试的典型写法，用于确定性重试测试：

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/cli/test_install.py

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

现在编写事务机制的专项测试：

toolName: Write

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: Shell

status: success

发现一个产品 bug（caches.py 缺少 `shutil` 导入）、回放逻辑对“旧目录被重建”的处理缺陷，以及测试夹具问题。先修产品代码：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/caches.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

现在修测试：只读用例的异常传播结构，CLI 用例改用本地 wheel 路径依赖：

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/cli/test_add.py

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: Shell

status: success

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

直接调试：临时让两个位置的 `install_wheel` 都抛错，确认实际调用路径：

toolName: Shell

status: success

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/pytest.py

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

直接单独运行 B1 并查看详细解析日志：

toolName: Shell

status: success

原因找到：`working_set` fixture 是模拟集合，导致同步跳过安装。改为断言真实环境：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

调试回滚/恢复两个用例，先手工复现查看日志事件序列：

toolName: Shell

status: success

找到根因：回放保护逻辑把空目录误判为非空，且未完成的 stash 意图错误地删掉了同一临时目录里已完成的备份。修正：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

直接在回放分支插桩，确认恢复路径：

toolName: Shell

status: success

插桩缩进破坏了语法，移除插桩代码：

toolName: Shell

status: success

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

用纯脚本直接验证 `replay_events` 在该场景下的行为：

toolName: Shell

status: success

toolName: Shell

status: success

根因：通配目录事件的 `old` 带尾部分隔符，`shutil.move(new, old+sep)` 会把备份移动为子目录而非替换。归一化路径：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

回滚路径修复。先单独重跑 Layer A 与 CLI 两个用例，确认稳定性：

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

用与真实事件完全相同的路径（含尾部分隔符）测试回放：

toolName: Shell

status: success

toolName: Shell

status: success

回放判定旧目录仍有文件。列出回退那一刻旧目录里到底有什么：

toolName: Shell

status: success

回放下标计算多减了一次，导致“已发布”配对的意图事件被当成未完成意图而漏掉真实文件的删除。重写循环递减：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: Shell

status: success

发布失败回滚已通过。调试跨进程恢复用例：

toolName: Shell

status: success

恢复用例的失败是测试模拟方式导致（`TemporaryDirectory` 终结器在“死亡”前清理了现场）。修正测试以禁用临时目录自动清理：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

现在排查 CLI 用例的 lock 阶段失败，单独运行并查看详细日志：

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

`idna` 是由 `repository` 测试夹具提供的假数据，真实 find-links 里没有。检查可用 fixture wheel，改用无传递依赖的包：

toolName: Shell

status: success

toolName: Shell

status: success

用无传递依赖的 `future_fstrings` 替换 `demo` 作为伴生包：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: Shell

status: success

两处剩余问题。先修 B2（不能用 `monkeypatch.undo()` 全量撤销夹具补丁，改用开关）：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

调试 PEP 582 本地环境的恢复：

toolName: Shell

status: success

真实崩溃时终结器不会运行；测试里需同时屏蔽 3.12 上 weakref 终结器直接调用的 `_rmtree`。改用持久化子类：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

二次调用出现“client closed”。查看 CLI 生命周期如何关闭/重建会话：

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/pytest.py

toolName: search_by_regex

status: success

toolName: search_by_regex

status: success

二次调用失败是测试夹具在每条命令后关闭 exit_stack 所致（新进程场景）。让第一次失败调用使用 `cleanup=False` 保持会话有效：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: Shell

status: success

20 个事务测试全部通过。运行更广泛的回归测试：

toolName: todo_write

status: success

Todos updated: 7 items

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

预检误把从不写入的只读 stdlib 目录纳入探测。修正为只探测实际写入/删除会触及的目录：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

验证其余失败是否为既有问题（与本次改动无关）：

toolName: Shell

status: success

toolName: Shell

status: success

基线同样失败，属环境既有问题。验证预检修复后重跑受影响测试与全量：

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

缺少测试依赖（我建 venv 时没装全 test 组）。补装后重跑：

toolName: Shell

status: success

toolName: Shell

status: success

全量 1506 通过，唯一失败是基线已有的环境问题。现在跑 ruff 与 mypy：

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/synchronizers.py

changes: undefined

合并 with 后需要整体去缩进一层。查看并重写整个块：

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/synchronizers.py

toolName: edit_file_search_replace

status: failed

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/synchronizers.py

changes: undefined

用脚本精确地把该块整体去缩进 4 空格：

toolName: Shell

status: success

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/cached_package.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/caches.py

changes: undefined

修正误合并的行：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/caches.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/models/caches.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py

changes: undefined

toolName: Shell

status: success

toolName: Shell

status: success

格式化后重新验证语法与关键测试：

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

部分 mypy 报错可能是既有的。先对比基线：

toolName: Shell

status: success

逐一修复 mypy（StagedEnvironment 改为子类、类型注解、`_path` ignore、NormalizedPath）：

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/synchronizers.py

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/uninstallers.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

现在将 `StagedEnvironment` 改为 `BaseEnvironment` 子类：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: failed

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/base.py

changes: undefined

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/base.py

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/base.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/base.py

changes: undefined

toolName: Shell

status: success

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/uninstallers.py

changes: undefined

toolName: Shell

status: success

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/uninstallers.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/uninstallers.py

changes: undefined

toolName: Shell

status: success

toolName: Shell

status: success

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

检查文档是否需要补充新配置项：

toolName: search_by_regex

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/docs/usage/config.md

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/docs/usage/config.md

changes: undefined

最终全量回归：

toolName: todo_write

status: success

Todos updated: 7 items

toolName: Shell

status: success

清理未使用字段并做最终代码走查：

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: edit_file_search_replace

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

changes: undefined

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/synchronizers.py

toolName: Shell

status: success

做一次真实 CLI 冒烟（离线 find-links → 安装 → 导入验证 → 二次安装幂等）：

toolName: Shell

status: success

toolName: Shell

status: success

toolName: Shell

status: success

冒烟通过（venv 安装、脚本、幂等）。清理临时目录并检查工作区状态：

toolName: Shell

status: success

工作区干净。最后通读关键 diff 做终审：

toolName: Shell

status: success

toolName: view_files

status: success

filePath: /Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py

最终确认 news 片段约定并收尾：

toolName: Shell

status: success

toolName: todo_write

status: success

Todos updated: 7 items

已完成原子化安装改造。问题的根源与修复如下：

## 问题根因

1. `install_wheel` 直接把文件、console 脚本、dist-info 元数据写进活动环境，中途失败（磁盘满/进程被杀）就留下半成品；
2. `PackageCache.cache_wheel()` 仅凭目录存在即复用缓存，解压中断会留下“毒缓存”；
3. 下次同步扫描 working set 时半成品 dist-info 被当成已安装，`_should_update` 返回 False，于是跳过缺失步骤。

## 改动内容

**新增 [transaction.py](file:///Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/transaction.py)** — 带持久日志的安装事务：
- **暂存**：`StagedEnvironment`（`BaseEnvironment` 子类代理）把所有 scheme 目录映射到环境前缀下同文件系统的暂存树，shebang 仍指向真实解释器；文件经 per-file `os.replace` 才能进活动环境。
- **校验**：逐包校验 RECORD 哈希（urlsafe-base64）、dist-info 元数据可读、console/gui 脚本存在且有可执行位；整批再做依赖闭包校验（按目标环境 `EnvSpec.markers_with_defaults()` 评估 marker，含 extras）。
- **提交**：只读预检（不碰只读系统目录如 stdlib）→ 原子提升候选缓存 → 旧文件 stash（移动）→ 暂存文件逐个 `os.replace` 发布 → referrer 登记；每个物理操作记录“意图/完成”双事件。
- **回滚/中止**：失败、`SIGTERM`、atexit 均回滚；ENOSPC 转为明确的 `InstallationError`。
- **崩溃恢复**：下次安装先按 env 哈希找日志，`staging` 直接丢弃，`committing` 按事件逆序确定性重放（恢复 stash、撤销发布、恢复 pth），兼容杀进程遗留现场。

**缓存候选/确认分离**（[caches.py](file:///Users/ding/Documents/swe/0910061/project-09/src/pdm/models/caches.py)、[cached_package.py](file:///Users/ding/Documents/swe/0910061/project-09/src/pdm/models/cached_package.py)）：先解压到 `.<name>.candidate` 并做全量 RECORD 校验，再 `os.replace` 原子提升为确认项；**完整确认项永不覆盖**，损坏项自动重建；`sweep_candidates()` 靠非阻塞锁清理死事务候选目录。

**接线**：[manager.py](file:///Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/manager.py) 的 install/uninstall/overwrite 支持事务（非事务路径行为与调用签名保持不变）；[synchronizers.py](file:///Users/ding/Documents/swe/0910061/project-09/src/pdm/installers/synchronizers.py) 用事务包裹整个同步与重试循环，失败批回滚后重试确定性重跑未确认步骤；新增配置 `install.atomic`（默认开，`PDM_INSTALL_ATOMIC=0` 可回退旧行为）。

**兼容性**：editable 与本地路径走 copy 暂存（不入包缓存）；PEP 582 与 venv 两种 scheme 均有参数化测试；镜像源/下载层不变；只读环境在任何变更前拒绝安装。

## 验证

- 新增 [test_install_transaction.py](file:///Users/ding/Documents/swe/0910061/project-09/tests/test_install_transaction.py) 20 个用例（双环境参数）：提交、缓存提升/符号链接重指、暂存期回滚、提交期磁盘满回滚、杀进程后恢复、只读预检、毒缓存重建、候选清扫、editable 兼容、失败批回滚后二次安装成功、失败作业确定性重试。
- 全量 `pytest -m "not integration"`：**1506 passed**；唯一失败 `test_completion_bash...` 在改动前的干净 HEAD 上同样失败（本机缺 bash-completion）。
- ruff check/format、mypy 均通过（仅剩一处改动前就存在的 mypy 告警）；并用真实 CLI 做了离线安装/导入/幂等冒烟。
