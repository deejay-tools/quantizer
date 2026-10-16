// Quantizer.app — finestra nativa per la GUI di Quantizer.
//
// Avvia gui.py (server locale) in background, mostra la pagina in una finestra
// WebKit senza barra degli indirizzi e chiude il server quando l'app termina.
// Il percorso del progetto è scritto in Info.plist (QuantizerRoot) da build.sh.

import Cocoa
import WebKit

let port = 8765
let baseURL = URL(string: "http://127.0.0.1:\(port)/")!

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var server: Process?
    var quitting = false

    // MARK: - avvio

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()

        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()          // localStorage persistente (opzioni salvate)
        config.mediaTypesRequiringUserActionForPlayback = []
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1120, height: 900),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "Quantizer"
        window.minSize = NSSize(width: 640, height: 480)
        window.contentView = webView
        window.center()
        window.setFrameAutosaveName("QuantizerMain")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        showMessage("Avvio di Quantizer…")
        DispatchQueue.global().async { self.startServer() }
    }

    func startServer() {
        if serverIsUp() {                      // già avviato (es. da Quantizer.command): riusalo
            DispatchQueue.main.async { self.webView.load(URLRequest(url: baseURL)) }
            return
        }
        guard let root = Bundle.main.object(forInfoDictionaryKey: "QuantizerRoot") as? String else {
            return fail("Percorso del progetto mancante in Info.plist (QuantizerRoot).")
        }
        let python = "\(root)/.venv/bin/python"
        guard FileManager.default.isExecutableFile(atPath: python) else {
            return fail("Non trovo l'ambiente Python in \(root)/.venv.\nSegui il Setup del README.")
        }

        let logURL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Quantizer.log")
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
        let log = try? FileHandle(forWritingTo: logURL)

        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = ["\(root)/gui.py", "--no-browser", "--port", String(port),
                       "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
        p.currentDirectoryURL = URL(fileURLWithPath: root)
        p.standardOutput = log
        p.standardError = log
        p.terminationHandler = { [weak self] proc in
            guard let self = self, !self.quitting else { return }
            self.fail("Il server di Quantizer si è chiuso (codice \(proc.terminationStatus)).\n"
                      + "Dettagli in ~/Library/Logs/Quantizer.log")
        }
        do {
            try p.run()
        } catch {
            return fail("Impossibile avviare il server: \(error.localizedDescription)")
        }
        server = p

        for _ in 0..<240 {                     // fino a 60 s
            if serverIsUp() {
                DispatchQueue.main.async { self.webView.load(URLRequest(url: baseURL)) }
                return
            }
            if !p.isRunning { return }         // terminationHandler mostra l'errore
            Thread.sleep(forTimeInterval: 0.25)
        }
        fail("Il server non risponde. Dettagli in ~/Library/Logs/Quantizer.log")
    }

    /// GET sincrona verso il server locale (da chiamare fuori dal main thread).
    func request(_ path: String, method: String = "GET", timeout: TimeInterval = 1) -> Data? {
        var req = URLRequest(url: baseURL.appendingPathComponent(path), timeoutInterval: timeout)
        req.httpMethod = method
        if method == "POST" {
            req.httpBody = Data("{}".utf8)
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        var result: Data?
        let done = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { data, response, _ in
            if (response as? HTTPURLResponse)?.statusCode == 200 { result = data }
            done.signal()
        }.resume()
        done.wait()
        return result
    }

    func serverIsUp() -> Bool {
        guard let data = request("api/defaults"),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        return json["app"] as? String == "quantizer"
    }

    func fail(_ message: String) {
        DispatchQueue.main.async { self.showMessage(message, error: true) }
    }

    func showMessage(_ text: String, error: Bool = false) {
        let safe = text
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: "\n", with: "<br>")
        let html = """
        <!doctype html><meta charset="utf-8"><style>
        :root { color-scheme: light dark; }
        body { margin: 0; height: 100vh; display: flex; align-items: center; justify-content: center;
               font: 15px -apple-system, sans-serif; background: #f4f3ef; color: \(error ? "#c92a2a" : "#6d6b64"); }
        @media (prefers-color-scheme: dark) { body { background: #161614; color: \(error ? "#ff8787" : "#9a978e"); } }
        p { max-width: 520px; text-align: center; line-height: 1.5; }
        </style><p>\(safe)</p>
        """
        webView.loadHTMLString(html, baseURL: nil)
    }

    // MARK: - chiusura

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard server != nil,
              let data = request("api/status"),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              json["state"] as? String == "running" else { return .terminateNow }
        let alert = NSAlert()
        alert.messageText = "Elaborazione in corso"
        alert.informativeText = "Se esci ora l'elaborazione dei brani viene interrotta."
        alert.addButton(withTitle: "Esci comunque")
        alert.addButton(withTitle: "Annulla")
        guard alert.runModal() == .alertFirstButtonReturn else { return .terminateCancel }
        _ = request("api/cancel", method: "POST")
        return .terminateNow
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        guard let p = server, p.isRunning else { return }
        p.terminate()
        p.waitUntilExit()
    }

    // MARK: - WebKit

    // La finestra mostra solo la GUI locale: i link esterni si aprono nel browser,
    // e un file trascinato per sbaglio non sostituisce la pagina.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.cancel) }
        if url.scheme == "about" || (url.host == "127.0.0.1" && url.port == port) {
            return decisionHandler(.allow)
        }
        if url.scheme == "http" || url.scheme == "https" { NSWorkspace.shared.open(url) }
        decisionHandler(.cancel)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Annulla")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        webView.load(URLRequest(url: baseURL))
    }

    // MARK: - menu

    @objc func reload(_ sender: Any?) { webView.load(URLRequest(url: baseURL)) }

    @objc func showLog(_ sender: Any?) {
        NSWorkspace.shared.open(FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Quantizer.log"))
    }

    func buildMenu() {
        let main = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Informazioni su Quantizer",
                        action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Nascondi Quantizer", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Esci da Quantizer", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Composizione")
        edit.addItem(withTitle: "Annulla", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "Ripeti", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "Taglia", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copia", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Incolla", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Seleziona tutto", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)

        let viewItem = NSMenuItem()
        let view = NSMenu(title: "Vista")
        view.addItem(withTitle: "Ricarica", action: #selector(reload(_:)), keyEquivalent: "r")
        view.addItem(withTitle: "Mostra registro…", action: #selector(showLog(_:)), keyEquivalent: "")
        viewItem.submenu = view
        main.addItem(viewItem)

        let winItem = NSMenuItem()
        let win = NSMenu(title: "Finestra")
        win.addItem(withTitle: "Riduci a icona", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        win.addItem(withTitle: "Chiudi", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        winItem.submenu = win
        main.addItem(winItem)

        NSApp.mainMenu = main
        NSApp.windowsMenu = win
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
