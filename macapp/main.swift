import Cocoa
import WebKit

class ViewController: NSViewController, WKNavigationDelegate {
    var webView: WKWebView!
    var backendProcess: Process?
    var loadingIndicator: NSProgressIndicator!

    override func loadView() {
        view = NSView(frame: NSRect(x: 0, y: 0, width: 1200, height: 800))
    }

    override func viewDidLoad() {
        super.viewDidLoad()

        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        webView = WKWebView(frame: view.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        view.addSubview(webView)

        // 加载指示器
        loadingIndicator = NSProgressIndicator(frame: NSRect(x: 0, y: 0, width: 40, height: 40))
        loadingIndicator.style = .spinning
        loadingIndicator.controlSize = .large
        loadingIndicator.frame = NSRect(x: view.bounds.midX - 20, y: view.bounds.midY - 20, width: 40, height: 40)
        view.addSubview(loadingIndicator)
        loadingIndicator.startAnimation(nil)

        startBackend()
    }

    func resourcesDir() -> URL {
        return Bundle.main.resourceURL!
    }

    func startBackend() {
        checkBackend { [weak self] running in
            if running {
                self?.loadFrontend()
            } else {
                self?.launchBackendProcess()
                self?.pollBackend(retries: 40)
            }
        }
    }

    func checkBackend(completion: @escaping (Bool) -> Void) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8900/api/providers")!)
        request.timeoutInterval = 2
        URLSession.shared.dataTask(with: request) { _, resp, _ in
            if let http = resp as? HTTPURLResponse, http.statusCode == 200 {
                completion(true)
            } else {
                completion(false)
            }
        }.resume()
    }

    func launchBackendProcess() {
        let res = resourcesDir()
        let backendDir = res.appendingPathComponent("backend", isDirectory: true)
        let sitePackages = res.appendingPathComponent("site-packages", isDirectory: true)
        let frontendDir = res.appendingPathComponent("frontend", isDirectory: true)

        // 数据目录: ~/Library/Application Support/ABcode
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dataDir = appSupport.appendingPathComponent("ABcode", isDirectory: true)
        try? FileManager.default.createDirectory(at: dataDir, withIntermediateDirectories: true)
        let dbPath = dataDir.appendingPathComponent("abcode.db").path

        // 使用系统 Python3（Xcode 自带 3.9）
        let pythonPath = "/usr/bin/python3"

        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8900", "--app-dir", backendDir.path]

        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = sitePackages.path
        env["ABCODE_DB"] = dbPath
        env["ABCODE_FRONTEND"] = frontendDir.path
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        process.currentDirectoryURL = backendDir

        // 日志输出到数据目录
        let logPath = dataDir.appendingPathComponent("backend.log").path
        FileManager.default.createFile(atPath: logPath, contents: nil)
        let logFile = FileHandle(forWritingAtPath: logPath)
        process.standardOutput = logFile
        process.standardError = logFile

        do {
            try process.run()
            backendProcess = process
        } catch {
            NSLog("ABcode 后端启动失败: \(error)")
        }
    }

    func pollBackend(retries: Int) {
        guard retries > 0 else {
            showError("后端启动超时，请确认系统已安装 Python3 后重试。\n日志: ~/Library/Application Support/ABcode/backend.log")
            return
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + 1) { [weak self] in
            self?.checkBackend { running in
                DispatchQueue.main.async {
                    if running {
                        self?.loadFrontend()
                    } else {
                        self?.pollBackend(retries: retries - 1)
                    }
                }
            }
        }
    }

    func loadFrontend() {
        guard let url = URL(string: "http://127.0.0.1:8900/") else { return }
        webView.load(URLRequest(url: url))
    }

    func showError(_ msg: String) {
        DispatchQueue.main.async {
            self.loadingIndicator.stopAnimation(nil)
            self.loadingIndicator.removeFromSuperview()
            let label = NSTextField(labelWithString: msg)
            label.frame = self.view.bounds.insetBy(dx: 80, dy: 300)
            label.alignment = .center
            label.textColor = .systemRed
            label.font = NSFont.systemFont(ofSize: 14)
            self.view.addSubview(label)
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loadingIndicator.stopAnimation(nil)
        loadingIndicator.removeFromSuperview()
    }

    override func viewWillDisappear() {
        super.viewWillDisappear()
        if let p = backendProcess, p.isRunning {
            p.terminate()
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var vc: ViewController!

    func applicationDidFinishLaunching(_ notification: Notification) {
        vc = ViewController()
        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1200, height: 800),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "ABcode"
        window.contentViewController = vc
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
