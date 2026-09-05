# Codex Switcher

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh-CN.md">简体中文</a>
</p>

Codex Switcher 是一个轻量级 macOS 应用，用于在多个本地 Codex / ChatGPT Desktop 启动配置之间快速切换，同时保持不同 Profile 的登录状态彼此隔离。

它主要面向需要在同一台 Mac 上使用多个 Codex 账号的用户，让你无需反复退出和重新登录，也可以继续使用相同的本地项目目录。

## 主要功能

- 最多 6 个本地启动台（A–F）；A 保持系统默认启动方式，B–F 可配置为相互隔离的 Codex Profile。

- 原生 macOS AppKit + WKWebView 应用，不使用 Electron。
- 支持 Apple Silicon（`arm64`）。
- App 启动时自动启动本地后台，退出 App 时自动停止后台。
- 启动台 A 始终使用 ChatGPT 的系统默认启动方式。
- 其他启动台可分别使用独立的 `CODEX_HOME` 和 Desktop `user-data-dir`。
- 多个启动台可以访问相同的本地工作区。
- 本地账户助记符和会员类型标签。
- 最多支持 20 个账户助记符，达到上限后新增控件会明确置灰并提示。
- 周额度记录和周重置时间管理。
- 5 小时重置倒计时以及自定义重置时间修正。
- 可重置次数管理和全局重置操作。
- 只读查看 Workspace 配置。
- 查看用户级 Codex Skills，并在不同 Profile 之间安全复制缺失 Skill。
- 支持明亮模式和黑暗模式。
- 支持 English 和简体中文。
- 首次启动欢迎说明面板。
- 自定义 Codex Switcher macOS App 图标。
- 实验室：可按启动台安全重置 Codex Desktop UI 设置，自动备份 config.toml，并支持一键还原。
- 顶部当前 / 建议 / 预览启动台支持平滑切换动画。
- 周剩余滑块支持关键百分比吸附点。
- 提供持久化的 **Next Codex Hand Off** 会话交接暂存台。
- 可直接在当前启动台区域编辑 5 小时下次重置时间。

## 工作原理

Codex Switcher 将 **启动台 Profile** 与 **账户助记符** 分离管理。

启动台决定 ChatGPT / Codex Desktop 如何启动：

- **启动台 A**：使用系统默认的 ChatGPT 启动方式。
- **启动台 B–F**：可以分别使用独立的 `CODEX_HOME` 和 Desktop `user-data-dir`。

账户助记符只是本地人工标签，不会验证真实 OpenAI 账号身份。

因此，如果你在某个启动台内部临时登录了另一个账号，只需要手动修改该启动台绑定的账户助记符即可，不需要改变启动台本身。

## 安装

### GitHub Release

下载：

```text
Codex-Switcher-v0.21.2-macOS-arm64.zip
```

然后：

1. 解压 ZIP。
2. 将 `Codex Switcher.app` 移动到 `/Applications`。
3. 打开 App。

正式 Release 是自包含版本，普通用户**不需要安装 Python、Xcode、Homebrew，也不需要下载源码工程**。

### 从源码构建正式 Release

在 Apple Silicon Mac 上执行：

```bash
./scripts/build-release.sh
```

构建脚本会：

- 优先使用 `/Applications/Xcode-beta.app`，其次使用正式版 Xcode；
- 为 `arm64` 编译原生 AppKit/WKWebView 外壳；
- 使用 PyInstaller 打包自包含 Python 后台；
- 将网页静态资源嵌入 `Codex Switcher.app`；
- 自动生成并嵌入 macOS App 图标；
- 执行 ad-hoc codesign；
- 验证原生程序和后台程序均为 arm64；
- 在 `release/` 中生成 GitHub Release 安装包；
- 将 PyInstaller 构建环境放在稳定的用户 Cache 目录中，因此源码工程改名或移动后，不会因为旧虚拟环境中的绝对路径而失效。

输出：

```text
release/Codex-Switcher-v0.21.2-macOS-arm64.zip
```

### 本地开发安装

```bash
./scripts/install-app.sh
```

安装位置：

```text
~/Applications/Codex Switcher.app
```

开发模式：

```bash
./scripts/run.sh
```

## 用户数据

Codex Switcher 使用标准 macOS Application Support 目录保存本地数据：

```text
~/Library/Application Support/com.nigolarer.codex-switcher/
├── launcher.sqlite3
└── backups/
```

原生 App 日志：

```text
~/Library/Logs/Codex Switcher/native-app.log
```

数据库中会保存启动台配置、账户助记符、额度记录、重置时间、切换历史、主题模式、语言以及其他本地状态。

## 从旧版本迁移

如果新版数据库不存在，Codex Switcher 可以自动从旧版目录迁移：

```text
~/Library/Application Support/com.ping.codex-account-switch-launcher/
```

也可以从更早期的工程内数据库迁移：

```text
data/launcher.sqlite3
```

迁移采用复制方式，不会删除旧数据库。

## 首次启动

第一次打开 Codex Switcher 时，会显示一个 Welcome Panel，说明：

- 启动台 A/B/C 分别代表什么；
- 账户助记符只是本地标签，并不代表经过验证的 OpenAI 账号身份；
- 哪些额度和重置信息会被记录在本地；
- App 不会读取 ChatGPT 密码或认证 Token。

欢迎面板默认只自动显示一次。

之后可以随时点击标题旁边的 `?` 按钮重新打开。

## 本地服务端口

默认端口：

```text
17831
```

可以在 Settings 中修改为 `1024` 到 `65535` 之间的端口。

修改后需要重新启动 Codex Switcher。

## 工作区查看

`查看工作区 / View Workspaces` 是完全只读的功能。

它会读取对应启动台的 `.codex-global-state.json`，解析其中的 `local-projects` 并显示：

- 项目名称；
- 主目录；
- 附加目录。

不会修改 Codex 的 Workspace 状态文件。

## Skills

`查看 Skills / View Skills` 会读取：

```text
$CODEX_HOME/skills
```

只显示包含 `SKILL.md` 的用户级 Skill，并自动排除 `.system`。

`复制缺失 Skills / Copy Missing Skills` 会：

- 只复制目标 Profile 中不存在的用户 Skill；
- 复制完整 Skill 目录，包括 scripts、references、assets 等资源；
- 不覆盖已有同名 Skill；
- 不复制认证信息、Workspace、Thread 或账号状态。

## 隐私

Codex Switcher 的设计原则是：**所有辅助状态都保存在本地。**

App 不会读取你的 ChatGPT 密码或认证 Token。

请不要将以下本地文件提交到 Git：

```text
auth.json
cookies
tokens
本地数据库
包含私人信息的日志
```

仓库中的 `.gitignore` 已经排除了运行时数据库、日志、Python 缓存、虚拟环境、构建产物、Release ZIP、本地环境文件和 IDE 配置。

## 卸载

```bash
./scripts/uninstall-app.sh
```

这个命令只删除 App。

用户数据会继续保留在：

```text
~/Library/Application Support/com.nigolarer.codex-switcher/
```

## macOS Gatekeeper

当前公开版本使用 ad-hoc 签名，还没有使用 Apple Developer ID 进行签名和公证（Notarization）。

如果第一次打开时被 macOS 阻止：

1. 右键点击 `Codex Switcher.app`。
2. 选择 **打开 / Open**。
3. 确认启动。

未来如果配置 Developer ID 并完成 notarization，就可以减少这一额外步骤。

## 当前版本

当前公开版本：

```text
v0.21.2
```

Release 安装包：

```text
Codex-Switcher-v0.21.2-macOS-arm64.zip
```

### v0.21.2 旧后台进程修复

原生 App 现在会同时检查后台版本和静态界面是否可用，不再只凭 `/api/version` 的 200 响应复用旧服务。如果源码目录改名或移动后仍残留旧的 Codex Switcher 后台进程，新版会安全替换这个失效后台，而不是附着后显示 404。Release 构建阶段也会强制校验 `runtime/static/index.html` 是否存在。
