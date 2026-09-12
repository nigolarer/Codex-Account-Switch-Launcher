import Cocoa
import WebKit
import Darwin

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var serverProcess: Process?
    private var ownsServer = false
    private var launcherURL: URL?
    private var runtimeRoot: URL!
    private var bundledServerURL: URL?
    private var sourceServerURL: URL?
    private var pythonPath: String = ""

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        guard loadRuntimeConfiguration() else { return }
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(workspaceDidWake),
            name: NSWorkspace.didWakeNotification,
            object: nil
        )
        buildWindow()
        startOrAttachServer()
    }

    @objc private func workspaceDidWake() {
        guard let base = launcherURL else { return }
        var request = URLRequest(url: base.appendingPathComponent("api/account/prime-check"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = Data("{}".utf8)
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request).resume()
    }

    private func loadRuntimeConfiguration() -> Bool {
        guard let resources = Bundle.main.resourceURL else {
            showFatal("App resources are unavailable. Please reinstall Codex Switcher.")
            return false
        }
        runtimeRoot = resources.appendingPathComponent("runtime", isDirectory: true)

        let releaseServer = runtimeRoot.appendingPathComponent("server/CodexSwitcherServer")
        if FileManager.default.isExecutableFile(atPath: releaseServer.path) {
            bundledServerURL = releaseServer
            return true
        }

        // Development/local-install fallback. Public release builds do not need Python.
        let sourceServer = runtimeRoot.appendingPathComponent("app/server.py")
        sourceServerURL = sourceServer
        guard FileManager.default.fileExists(atPath: sourceServer.path) else {
            showFatal("The bundled local service is missing. Please reinstall Codex Switcher.")
            return false
        }

        if let pythonURL = Bundle.main.url(forResource: "python-path", withExtension: "txt"),
           let raw = try? String(contentsOf: pythonURL, encoding: .utf8) {
            pythonPath = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if pythonPath.isEmpty || !FileManager.default.isExecutableFile(atPath: pythonPath) {
            let candidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
            pythonPath = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) ?? ""
        }
        guard !pythonPath.isEmpty else {
            showFatal("No usable Python 3 installation was found. Install Python 3 or use the self-contained Release build.")
            return false
        }
        return true
    }

    private func buildWindow() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.setValue(false, forKey: "drawsBackground")

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1220, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Codex Switcher"
        window.minSize = NSSize(width: 900, height: 650)
        window.contentView = webView
        window.center()
        window.isReleasedWhenClosed = false
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func makeServerProcess(arguments: [String]) -> Process? {
        let process = Process()
        if let bundled = bundledServerURL {
            process.executableURL = bundled
            process.arguments = arguments
        } else if let source = sourceServerURL {
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [source.path] + arguments
        } else {
            return nil
        }
        process.currentDirectoryURL = runtimeRoot
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["CODEX_LAUNCHER_RUNTIME_ROOT"] = runtimeRoot.path
        process.environment = env
        return process
    }

    private func configuredPort() -> Int {
        guard let process = makeServerProcess(arguments: ["--print-port"]) else { return 17831 }
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            if let raw = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
               let port = Int(raw), port >= 1024, port <= 65535 {
                return port
            }
        } catch { }
        return 17831
    }

    private func startOrAttachServer() {
        let port = configuredPort()
        guard let url = URL(string: "http://127.0.0.1:\(port)/") else { return }
        launcherURL = url

        inspectExistingServer(url: url) { [weak self] state in
            guard let self else { return }
            switch state {
            case .currentAndHealthy:
                self.ownsServer = false
                self.loadLauncher()
            case .codexSwitcherButStale:
                // A server from an older/moved source checkout can keep /api/version
                // alive while its static directory has disappeared. Reclaim the port,
                // but only when the listener is positively identified as our backend.
                if self.terminateKnownCodexSwitcherListener(port: port) {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                        self.startServer()
                    }
                } else {
                    self.showErrorPage("Port \(port) is occupied by a stale Codex Switcher service that could not be stopped. Quit old Codex Switcher instances and reopen this app.")
                }
            case .notCodexSwitcher:
                self.startServer()
            }
        }
    }

    private enum ExistingServerState {
        case currentAndHealthy
        case codexSwitcherButStale
        case notCodexSwitcher
    }

    private func currentAppVersion() -> String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
    }

    private func inspectExistingServer(url: URL, completion: @escaping (ExistingServerState) -> Void) {
        var versionRequest = URLRequest(url: url.appendingPathComponent("api/version"))
        versionRequest.timeoutInterval = 0.6
        URLSession.shared.dataTask(with: versionRequest) { data, response, _ in
            guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode,
                  let data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let version = obj["version"] as? String else {
                DispatchQueue.main.async { completion(.notCodexSwitcher) }
                return
            }

            var rootRequest = URLRequest(url: url)
            rootRequest.timeoutInterval = 0.6
            rootRequest.cachePolicy = .reloadIgnoringLocalCacheData
            URLSession.shared.dataTask(with: rootRequest) { _, rootResponse, _ in
                let rootOK = (rootResponse as? HTTPURLResponse).map { 200..<300 ~= $0.statusCode } ?? false
                let state: ExistingServerState = (version == self.currentAppVersion() && rootOK)
                    ? .currentAndHealthy
                    : .codexSwitcherButStale
                DispatchQueue.main.async { completion(state) }
            }.resume()
        }.resume()
    }

    private func terminateKnownCodexSwitcherListener(port: Int) -> Bool {
        let candidates = ["/usr/sbin/lsof", "/usr/bin/lsof"]
        guard let lsofPath = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            return false
        }

        let lsof = Process()
        let output = Pipe()
        lsof.executableURL = URL(fileURLWithPath: lsofPath)
        lsof.arguments = ["-nP", "-tiTCP:\(port)", "-sTCP:LISTEN"]
        lsof.standardOutput = output
        lsof.standardError = Pipe()
        do {
            try lsof.run()
            lsof.waitUntilExit()
        } catch {
            return false
        }

        let raw = String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let pids = raw.split(whereSeparator: \.isWhitespace).compactMap { Int32($0) }
        var stoppedAny = false

        for pid in pids {
            let ps = Process()
            let psOutput = Pipe()
            ps.executableURL = URL(fileURLWithPath: "/bin/ps")
            ps.arguments = ["-p", String(pid), "-o", "command="]
            ps.standardOutput = psOutput
            ps.standardError = Pipe()
            do {
                try ps.run()
                ps.waitUntilExit()
            } catch {
                continue
            }
            let command = String(data: psOutput.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            let lower = command.lowercased()
            let knownBackend = command.contains("CodexSwitcherServer") ||
                (lower.contains("server.py") && (lower.contains("codex-switcher") || lower.contains("codex-account-switch")))
            if knownBackend && Darwin.kill(pid, SIGTERM) == 0 {
                stoppedAny = true
            }
        }
        return stoppedAny
    }

    private func startServer() {
        guard let process = makeServerProcess(arguments: []) else {
            showFatal("Unable to configure the bundled local service.")
            return
        }

        let logDir = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Codex Switcher", isDirectory: true)
        try? FileManager.default.createDirectory(at: logDir, withIntermediateDirectories: true)
        let logURL = logDir.appendingPathComponent("native-app.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let handle = try? FileHandle(forWritingTo: logURL) {
            try? handle.seekToEnd()
            process.standardOutput = handle
            process.standardError = handle
        }

        process.terminationHandler = { [weak self] p in
            DispatchQueue.main.async {
                guard let self, self.ownsServer else { return }
                self.ownsServer = false
                if p.terminationStatus != 0 {
                    self.showErrorPage("The local service exited with status \(p.terminationStatus). Quit and reopen Codex Switcher to retry. See ~/Library/Logs/Codex Switcher/native-app.log for details.")
                }
            }
        }
        do {
            try process.run()
            serverProcess = process
            ownsServer = true
            waitForServer(attempt: 0)
        } catch {
            showFatal("Unable to start the local service: \(error.localizedDescription)")
        }
    }

    private func waitForServer(attempt: Int) {
        guard let url = launcherURL else { return }
        if attempt >= 80 {
            showErrorPage("The local service timed out while starting. See ~/Library/Logs/Codex Switcher/native-app.log")
            return
        }
        probe(url: url) { [weak self] running in
            guard let self else { return }
            if running {
                self.loadLauncher()
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                    self.waitForServer(attempt: attempt + 1)
                }
            }
        }
    }

    private func probe(url: URL, completion: @escaping (Bool) -> Void) {
        var request = URLRequest(url: url.appendingPathComponent("api/version"))
        request.timeoutInterval = 0.5
        URLSession.shared.dataTask(with: request) { _, response, _ in
            let ok = (response as? HTTPURLResponse).map { 200..<300 ~= $0.statusCode } ?? false
            DispatchQueue.main.async { completion(ok) }
        }.resume()
    }

    private func loadLauncher() {
        guard let base = launcherURL else { return }
        var comps = URLComponents(url: base, resolvingAgainstBaseURL: false)
        comps?.queryItems = [
            URLQueryItem(name: "native", value: "1"),
            URLQueryItem(name: "v", value: String(Int(Date().timeIntervalSince1970)))
        ]
        if let url = comps?.url {
            webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10))
        }
    }

    private func showErrorPage(_ message: String) {
        let escaped = message
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
        webView.loadHTMLString("""
        <html><body style='font-family:-apple-system;background:#111;color:#eee;padding:40px'>
        <h2>Codex Switcher</h2><p>\(escaped)</p></body></html>
        """, baseURL: nil)
    }

    private func showFatal(_ message: String) {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "Codex Switcher"
        alert.informativeText = message
        alert.runModal()
        NSApp.terminate(nil)
    }

    // WKWebView does not present JavaScript alert/confirm/prompt dialogs unless
    // a WKUIDelegate implements them. The web UI relies on these dialogs for
    // destructive or state-changing actions, so bridge them to native NSAlert.
    func webView(_ webView: WKWebView,
                 runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = "Codex Switcher"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        if let window = window, window.isVisible {
            alert.beginSheetModal(for: window) { _ in completionHandler() }
        } else {
            alert.runModal()
            completionHandler()
        }
    }

    func webView(_ webView: WKWebView,
                 runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Codex Switcher"
        alert.informativeText = message
        alert.addButton(withTitle: "Confirm")
        alert.addButton(withTitle: "Cancel")
        if let window = window, window.isVisible {
            alert.beginSheetModal(for: window) { response in
                completionHandler(response == .alertFirstButtonReturn)
            }
        } else {
            let response = alert.runModal()
            completionHandler(response == .alertFirstButtonReturn)
        }
    }

    func webView(_ webView: WKWebView,
                 runJavaScriptTextInputPanelWithPrompt prompt: String,
                 defaultText: String?,
                 initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping (String?) -> Void) {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = "Codex Switcher"
        alert.informativeText = prompt
        let input = NSTextField(string: defaultText ?? "")
        input.frame = NSRect(x: 0, y: 0, width: 320, height: 24)
        alert.accessoryView = input
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        if let window = window, window.isVisible {
            alert.beginSheetModal(for: window) { response in
                completionHandler(response == .alertFirstButtonReturn ? input.stringValue : nil)
            }
        } else {
            let response = alert.runModal()
            completionHandler(response == .alertFirstButtonReturn ? input.stringValue : nil)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            window?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        NSWorkspace.shared.notificationCenter.removeObserver(self)
        if ownsServer, let process = serverProcess, process.isRunning {
            process.terminate()
            let deadline = Date().addingTimeInterval(1.5)
            while process.isRunning && Date() < deadline {
                RunLoop.current.run(until: Date().addingTimeInterval(0.05))
            }
            if process.isRunning { process.interrupt() }
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
