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

账户助记符仍然是本地人工标签，但现在可以选择与 Codex `app-server` 返回的稳定 `accountId` 进行绑定。绑定后，同一个真实账户即使出现在不同启动台，也可以被自动识别。

启动台中选择的账户助记符表示“预期账户”；实际检测到的账户身份与额度以 Codex 返回值为准。如果检测到未绑定账户，主页面会提供一键绑定。

## 安装

### GitHub Release

下载：

```text
Codex-Switcher-v0.22.5-macOS-arm64.zip
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
release/Codex-Switcher-v0.22.5-macOS-arm64.zip
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
- 账户助记符可以与 Codex 返回的 `accountId` 绑定；
- 额度和重置时间可以通过 Codex `app-server` 自动同步；
- App 不会直接读取 ChatGPT 密码或认证 Token。

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

App 不会直接读取你的 ChatGPT 密码或认证 Token。账户身份与额度通过 Codex 自己的 `app-server` 获取，Switcher 只在本地保存 `accountId` 与账户助记符的映射以及最近一次额度状态。

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
v0.22.5
```

Release 安装包：

```text
Codex-Switcher-v0.22.5-macOS-arm64.zip
```


### v0.22.5 · 自动额度同步可见性修复 + 立即同步

- 修复“后台已经按 5 / 10 / 30 / 60 分钟完成额度同步，但界面仍显示十几分钟前”的问题：此前主页面只每 30 分钟重新获取一次本地状态，导致 UI 没有及时看到后端已经完成的同步。现在主界面每 30 秒只读取一次本地 `/api/state`，不会因此调用 Codex 或增加账户额度查询频率。
- 修复启动阶段提前写入自动同步时间戳的问题。只有真正同步成功后才推进自动同步计时；如果 Codex Desktop 仍在启动，调度器可以在后续轮询中及时重试。
- 每个已绑定账户的启动台，在“最后一次同步”超过 1 分钟后，会在工作区 / Skills 工具组中显示“立即同步”按钮。
- “立即同步”属于明确的用户操作：可以对该启动台发起一次 Codex `app-server` 查询；1 分钟内刚同步过的账户不会重复触发。返回的 `accountId` 仍由 Codex 作为事实来源，不会把错误账户额度写入预期助记符。

### v0.22.4 · 下一启动台回退显示 + 低频账户巡检

- 即使其他启动台当前都暂不可用，“建议下一个”也不再留空，而是显示预计最早恢复的启动台，并明确提示“当前暂不可用”及预计恢复时间。
- 新增可配置的后台账户巡检窗口：默认 6 小时，最小 1 小时，推荐设置为 6 小时或更高。
- 后台每 30 分钟只检查一次时间戳，仅对超过配置窗口仍未成功同步的已绑定账户调用一次 Codex `app-server`。
- 按 Codex `accountId` 去重；同一账户即使出现在多个启动台，也不会重复巡检。
- 后台巡检不会启动 ChatGPT Desktop 界面。
- 修复真实 Codex 账户的可用性判断：存在未来的 5 小时重置时间并不代表当前不可用，只要 5H 剩余额度仍大于 0 就会正常参与推荐。

### v0.22.3 · 已绑定账户的只读实时额度 UI

- 已绑定且成功检测到真实 Codex 账户后，主界面不再重复显示额外的 5 小时 / 周额度面板。
- Codex 同步得到的额度直接替换原有手工额度区域：进度条与重置时间正常展示，但变为只读，不再响应点击或显示铅笔、重置、增加次数等手工调整入口。
- 已绑定账户的启动台悬停工具仅保留本地工作区与 Skills 等本地工具；未绑定/纯手工账户仍保留原来的手工额度能力作为 fallback。
- 账户身份区域新增“最后一次同步”，以相对时间显示，例如“刚刚同步（5分钟内）”“6分钟前”“1小时前”“1天前”，并随时间自动更新。
- 设置 → 账户助记符中也使用相同的相对同步时间。
- 延续 v0.22.2 的 5 / 10 / 30 / 60 分钟自动同步规则，并且仍只同步当前正在运行的启动台。

### v0.22.0 · Codex 账户身份绑定与实时额度

- 通过 Codex 自带 `app-server` 的 `account/rateLimits/read` 读取当前启动台真实账户信息，不直接读取或保存认证 Token。
- 自动识别 Codex `accountId`、套餐类型、5 小时剩余额度/重置时间、周剩余额度/重置时间和可重置次数。
- 账户助记符可与稳定的 Codex `accountId` 一键绑定；同一真实账户换到其他启动台后仍可自动识别。
- 当前启动台检测到未绑定账户时，主页面显示一键绑定提示；若实际账户与启动台预期助记符不一致，会显示账户不一致提示并以检测到的真实账户为准。
- 设置 → 账户助记符会显示“已绑定 / 未绑定”，已绑定账户可一键解绑。解绑不会删除助记符，也不会改变启动台配置。
- 实时额度只作为 Codex 返回的动态状态同步到已绑定助记符；认证信息仍完全由 Codex 自己管理。

### v0.21.2 旧后台进程修复

原生 App 现在会同时检查后台版本和静态界面是否可用，不再只凭 `/api/version` 的 200 响应复用旧服务。如果源码目录改名或移动后仍残留旧的 Codex Switcher 后台进程，新版会安全替换这个失效后台，而不是附着后显示 404。Release 构建阶段也会强制校验 `runtime/static/index.html` 是否存在。
