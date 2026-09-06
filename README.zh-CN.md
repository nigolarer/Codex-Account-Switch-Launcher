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
Codex-Switcher-v1.0.9-macOS-arm64.zip
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
release/Codex-Switcher-v1.0.9-macOS-arm64.zip
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
- App 永远不会读取 ChatGPT 密码；只有用户主动执行“绑定账号 / 立即同步”时，才会临时在本机读取对应 `auth.json` 的 OAuth Token 来查询真实额度，Token 不会被保存或显示。

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

App 不会读取你的 ChatGPT 密码。可选的“绑定账号 / 立即同步”功能只会在你主动操作时，临时读取当前启动台 `auth.json` 中的 OAuth Token 以查询 Codex 真实额度；Codex Switcher 不会保存或显示该 Token。

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
v1.0.9
```

Release 安装包：

```text
Codex-Switcher-v1.0.9-macOS-arm64.zip
```

### v0.21.2 旧后台进程修复

原生 App 现在会同时检查后台版本和静态界面是否可用，不再只凭 `/api/version` 的 200 响应复用旧服务。如果源码目录改名或移动后仍残留旧的 Codex Switcher 后台进程，新版会安全替换这个失效后台，而不是附着后显示 404。Release 构建阶段也会强制校验 `runtime/static/index.html` 是否存在。

## 版本记录

### v1.0.3 已绑定额度只读与 UI 修复

- 已绑定账号的“可重置次数”现在视为只读：隐藏编辑铅笔和“增加可重置次数”，账户设置中禁用该字段，后端接口也会拒绝手动修改；全局重置卡同样跳过已绑定账号。
- 已绑定账号的 5 小时剩余为 100% 时，倒计时始终显示 `—`，并在当前启动台、建议下一个和下方启动台卡片中明确显示 **下次重置：未开始**。
- 统一顶部“当前启动台 / 建议下一个”和下方启动台列表中 **已绑定** 与 Plus / Pro 等套餐标签之间的间距。

### v0.22.4 官方同步时间与绑定账号交互优化

- 已绑定账号的“官方信息同步”改为相对时间显示：5 分钟内显示“刚刚同步”，之后显示“5 分钟前 / 30 分钟前 / N 小时前 / N 天前”等。
- 同一行追加“下次同步 HH:MM”，只显示时和分。
- 已绑定账号每 30 分钟自动同步一次官方额度；若同步失败，5 分钟后重试。
- 当前启动台中的已绑定账号不再显示“开始 / 重新倒计时 5H”按钮，只保留“立即同步”，避免官方同步与本地手动倒计时并存。

### v0.22.1 绑定持久化与“注意”状态 UI

- 将额度状态中的“**危险**”改为更合适的“**注意**”，并把提示放到真正触发条件的指标右侧：周剩余、5 小时剩余分别独立显示；两个都触发时两边都会显示。
- 恢复真实正在运行的启动台上的“**绑定账号**”按钮：顶部“当前启动台”和下方启动台列表都会显示。
- 真实账号绑定信息现在写入 Application Support 下稳定的 SQLite 数据库，因此重新 build / 升级 App 不再丢失绑定。OAuth Token 不会写入数据库。
- 绑定成功后，在顶部“当前启动台 / 建议下一个”和下方启动台卡片中，都在 Plus / Pro 等套餐标识左侧显示“**已绑定**”。平时只显示这一枚状态标识，鼠标悬停后才显示 Plus 账号 ID、真实套餐、绑定来源 CODEX_HOME 和最近同步时间。
- 当前启动台原来的真实额度查询按钮改名为“**立即同步**”。点击时按需读取该启动台本地 Codex OAuth 凭据，并同步真实的 5 小时/周剩余量与重置时间。
- 保留 v0.22.0 的额度感知推荐逻辑：默认 5 小时 15%、Plus 周额度 10% 的“注意阈值”，两项均可在设置中调整。


### v1.0.3 已绑定账号重置控制修复

- 已绑定账号不再允许编辑周重置时间、重新启动本地 5 小时倒计时或自定义 5 小时重置时间。
- 已绑定启动台卡片改为显示 **立即同步**，以官方额度与重置时间为准。
- 后端同步增加保护，即使绕过 UI 也不能修改已绑定账号的这些重置时间。

### v1.0.0 UI 优化与 Hand Off 预设信息

- Next Codex Hand Off 新增 **预设信息** 按钮；中文和英文界面会填入各自独立的固定“继续执行指令”，已有内容时会先确认是否替换。
- 项目版本号正式更新为 **1.0.0**，并同步到后端、Release 构建、App Bundle 元数据和文档。
- 当前启动台的 **立即同步** 与建议下一个的 **切换并启动** 按钮高度完全一致，但宽度仍按各自文字自适应。


### v1.0.7 恢复同步频率设置

- 在设置中恢复独立的 **同步设置** 区域。
- 当前启动台的官方额度自动同步频率支持：**5 分钟 / 30 分钟 / 1 小时 / 3 小时**，默认 30 分钟。
- 恢复与上述频率完全独立的 **全局同步**：定期刷新所有不同的已绑定账号，默认 **6 小时**一次；全局周期可单独设置为 1–168 小时。
- 已绑定账号下方的“下次同步”会取当前启动台同步计划与全局同步计划中更早的时间。
- 两个同步设置都会持久化到现有 SQLite 状态中，升级版本后不会丢失。


### v1.0.7 行内同步反馈

- **立即同步** 不再弹出确认或成功提示框。
- 手动同步进行中时，按钮会变为 **同步中**，并在文字后显示 CSS loading 圆环。
- 点击后 5 秒内禁止重复触发手动同步。
- 同步成功后，“刚刚同步”会短暂从下方进入并变为绿色，然后平滑恢复为普通次级文字颜色。
- 当前启动台和下方启动台卡片中的“立即同步”统一使用同一套交互。


### v1.0.7 全绑定账号的全局同步模式

- 当所有本地账户助记符都已绑定官方账号时，顶部的 **全局额度重置** 和 **全局重置卡** 会自动隐藏。
- 两个按钮会由 **全局立即同步** 替代；它手动触发与“全局同步周期”（默认 6 小时）完全相同的全量官方同步逻辑。
- 手动全局同步采用行内 Loading，至少 5 秒内禁止重复点击，并会更新全局同步时间以及所有成功同步账号的界面状态。
- 如果之后又出现未绑定账号，本地的两个全局重置按钮会自动恢复，全局立即同步则自动隐藏。


### v1.0.7 额度警示视觉优化

- “周剩余”和“5 小时剩余”会在触发“注意”阈值时同步变为柔和红色。
- 随剩余额度逐渐接近 0%，红色警示会平滑增强。
- 当剩余低于 5% 时，“注意”标签自动改为 **余量不足**。


### v1.0.8 同步时自动修正已绑定账号映射

- 点击 **立即同步** 时，如果发现启动台当前实际登录的 Codex 账号与 Codex Switcher 中选择的账户助记符不一致，会先在本地所有已绑定账号中寻找这个真实账号。
- 如果能够找到匹配的已绑定账号，会自动把该启动台切换到对应的账户助记符，并继续完成同步，不再弹出账号不匹配错误。
- 只有当当前实际登录的账号在本地没有任何匹配绑定时，才会继续提示账号不匹配。
- 这样即使直接在 Codex 内退出并登录了另一个账号、没有先在 Codex Switcher 中手动切换，也会在下一次“立即同步”时自动修正映射。


### v1.0.9 额度警示与同步 UI 优化

- 周剩余和 5 小时剩余文字保持原有颜色；仅“注意”徽标会随额度降低从柔和黄色过渡到橘红色，低于 5% 后显示浅红色“余量不足”。
- 删除启动台工具按钮组中重复的“立即同步”，已绑定启动台只保留 5 小时区域内的同步入口。
- “下次同步”改为相对时间：5 分钟内按 1 分钟粒度显示，5 分钟以上按 5 分钟粒度显示。
