# Codex 账号切换启动器 v0.17.0

一个面向 macOS Codex / ChatGPT Desktop 多账号串行切换的轻量工具。A 是系统默认启动方式，B/C 使用独立的 `CODEX_HOME` 与 Desktop `user-data-dir`，账号助记符、额度、Work/Skills 查看等状态由本地 Launcher 管理。

## v0.17.0：真正独立安装的 macOS App

这一版完成了两个结构性改造：

1. **App 不再依赖源码目录。** `app/server.py` 和 `static/` 会在安装时复制到 `.app/Contents/Resources/runtime/`。安装完成后，源码目录可以移动或删除。
2. **用户数据迁移到标准 Application Support。** 默认数据位置为：

```text
~/Library/Application Support/com.ping.codex-account-switch-launcher/
├── launcher.sqlite3
└── backups/
```

App 本身安装在：

```text
~/Applications/Codex账号切换启动器.app
```

日志写入：

```text
~/Library/Logs/Codex Account Switch Launcher/native-app.log
```

## 从旧版本升级

在原来的工程目录中运行：

```bash
./scripts/install-app.sh
```

如果新版 Application Support 中还没有数据库，而旧工程存在：

```text
<旧工程>/data/launcher.sqlite3
```

安装器会**复制**旧数据库到新的标准目录，并尽量同时复制旧 `backups/`。旧工程中的原始数据库不会删除，因此天然保留一份迁移前备份。

以后只读取 Application Support 中的数据。源码工程被移动、覆盖或删除都不会影响已安装 App。

## 原生 App 生命周期

- App 显示在 Dock。
- 打开 App 时自动启动内置 Python 本地服务。
- UI 使用原生 `WKWebView`，不额外打开浏览器。
- 红色关闭按钮只隐藏窗口，App 和服务仍在运行。
- 再次点击 Dock 图标恢复窗口。
- `⌘Q` 退出 App 时，由 App 启动的服务同时停止。
- 不需要 LaunchAgent，不需要先运行 `run.sh`。

## 安装

```bash
./scripts/install-app.sh
```

构建器优先使用：

```text
/Applications/Xcode-beta.app
```

其次回退到正式 Xcode。构建时显式使用所选 Xcode 的 macOS SDK，并把最低运行目标固定为 macOS 13.0，避免 Beta 系统自动推导出错误 target。

当前机器需要可用的 `python3`。安装器会记录 Python 可执行文件路径到 App Resource；如果之后该路径失效，App 还会尝试常见 Homebrew / 系统 Python 路径。

## 端口

默认：

```text
17831
```

可在设置中改为 `1024–65535`。端口保存在 Application Support 数据库中，退出并重新打开 App 后使用新端口。

## 启动台

### A

A 永远是原始系统启动方式：

```bash
open -a /Applications/ChatGPT.app
```

不会附加 `CODEX_HOME` 或 `--user-data-dir`，不可删除。

### B / C

使用各自独立的：

```text
CODEX_HOME
Desktop user-data-dir
```

账号助记符与启动台解绑，因此 A/B/C 实际登录哪个账号可以独立人工记录。

## Workspace 查看

“查看工作区”只读解析对应 `CODEX_HOME/.codex-global-state.json` 的 `local-projects`，显示项目名称和 `rootPaths`，不会修改 Codex 工作区状态。

## Skills

“查看 Skills”只读取 `$CODEX_HOME/skills` 中包含 `SKILL.md` 的用户 Skill，并排除 `.system`。复制时只复制目标缺失的整个 Skill 目录，不覆盖同名 Skill，也不复制认证、Workspace、SQLite 或 Thread 状态。

## 开发模式

已安装 App 不依赖源码，但开发/排障时仍可运行：

```bash
./scripts/run.sh
```

开发模式也使用同一个 Application Support 数据库。如果新版数据目录尚未建立，而当前源码目录仍有旧 `data/launcher.sqlite3`，会将其作为一次性迁移来源。

旧 LaunchAgent 模式已废弃：

```bash
./scripts/install.sh
```

只会提示使用原生 App。

## 卸载

```bash
./scripts/uninstall-app.sh
```

只删除 App，不删除用户数据。若要彻底清除数据，需要用户自行删除：

```text
~/Library/Application Support/com.ping.codex-account-switch-launcher/
```

## GitHub / 隐私

`.gitignore` 会排除运行数据、SQLite、日志、Python 缓存、环境文件、虚拟环境、IDE 本地配置、构建产物和 ZIP。发布包也不会包含用户 `data/`、账号认证文件或数据库。

不要提交 `auth.json`、Cookie、Token 或其他账号认证数据。
