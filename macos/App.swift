import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var serverProcess: Process?
    private var ownsServer = false
    private var launcherURL: URL?
    private var runtimeRoot: URL!
    private var serverURL: URL!
    private var pythonPath: String = ""

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        guard loadRuntimeConfiguration() else { return }
        buildWindow()
        startOrAttachServer()
    }

    private func loadRuntimeConfiguration() -> Bool {
        guard let resources = Bundle.main.resourceURL else {
            showFatal("App resources are unavailable. Please reinstall Codex Switcher.")
            return false
        }
        runtimeRoot = resources.appendingPathComponent("runtime", isDirectory: true)
        serverURL = runtimeRoot.appendingPathComponent("app/server.py")
        guard FileManager.default.fileExists(atPath: serverURL.path) else {
            showFatal("The bundled local service is missing. Please run scripts/install-app.sh again.")
            return false
        }

        if let pythonURL = Bundle.main.url(forResource: "python-path", withExtension: "txt"),
           let raw = try? String(contentsOf: pythonURL, encoding: .utf8) {
            pythonPath = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if pythonPath.isEmpty || !FileManager.default.isExecutableFile(atPath: pythonPath) {
            // Fallback for a Python installation that moved after App installation.
            let candidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
            pythonPath = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) ?? ""
        }
        guard !pythonPath.isEmpty else {
            showFatal("No usable Python 3 installation was found. Install Python 3 and run scripts/install-app.sh again.")
            return false
        }
        return true
    }

    private func buildWindow() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
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

    private func configuredPort() -> Int {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [serverURL.path, "--print-port"]
        process.currentDirectoryURL = runtimeRoot
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
        probe(url: url) { [weak self] running in
            guard let self else { return }
            if running {
                self.ownsServer = false
                self.loadLauncher()
            } else {
                self.startServer(port: port)
            }
        }
    }

    private func startServer(port: Int) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [serverURL.path]
        process.currentDirectoryURL = runtimeRoot
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env

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
                    self.showErrorPage("The local service exited with status \(p.terminationStatus). Quit and reopen Codex Switcher to retry.")
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
        if attempt >= 60 {
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

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            window?.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        if ownsServer, let process = serverProcess, process.isRunning {
            process.terminate()
            let deadline = Date().addingTimeInterval(1.5)
            while process.isRunning && Date() < deadline {
                RunLoop.current.run(until: Date().addingTimeInterval(0.05))
            }
            if process.isRunning {
                process.interrupt()
            }
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
