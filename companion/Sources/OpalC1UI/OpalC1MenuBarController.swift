import AppKit
import Foundation

public enum OpalAction: Int32 {
    case togglePause = 1
    case toggleLaunchAtLogin = 2
    case selectPreset1 = 11
    case selectPreset2 = 12
    case selectPreset3 = 13
    case quit = 99
}

public typealias OpalActionCallback = @convention(c) (Int32) -> Void

public final class OpalC1MenuBarController: NSObject, NSMenuDelegate {
    public static let shared = OpalC1MenuBarController()

    private var statusItem: NSStatusItem?
    private var mainMenu: NSMenu?

    // Menu Items
    private var headerItem: NSMenuItem?
    private var telemetryItem: NSMenuItem?
    private var clientItem: NSMenuItem?
    private var pauseItem: NSMenuItem?
    private var launchAtLoginItem: NSMenuItem?
    private var preset1Item: NSMenuItem?
    private var preset2Item: NSMenuItem?
    private var preset3Item: NSMenuItem?

    private var actionCallback: OpalActionCallback?

    public private(set) var currentState: OpalCameraState = .idle
    public private(set) var isPaused: Bool = false
    public private(set) var isLaunchAtLogin: Bool = false
    public private(set) var activePreset: Int = 1

    public override init() {
        super.init()
    }

    public func registerCallback(_ callback: @escaping OpalActionCallback) {
        self.actionCallback = callback
    }

    public func setup() {
        guard statusItem == nil else { return }

        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        updateGlyph()

        let menu = NSMenu()
        menu.delegate = self
        menu.autoenablesItems = false

        // 1. Header
        let header = NSMenuItem(title: "Opal C1 (Ark Edition)", action: nil, keyEquivalent: "")
        header.isEnabled = false
        let font = NSFont.boldSystemFont(ofSize: 13)
        header.attributedTitle = NSAttributedString(string: "Opal C1 (Ark Edition)", attributes: [.font: font])
        menu.addItem(header)
        self.headerItem = header

        // 2. Telemetry status line
        let telemetry = NSMenuItem(title: "Idle · 4K Ready", action: nil, keyEquivalent: "")
        telemetry.isEnabled = false
        menu.addItem(telemetry)
        self.telemetryItem = telemetry

        // 3. Client Line (hidden if no client active)
        let client = NSMenuItem(title: "", action: nil, keyEquivalent: "")
        client.isEnabled = false
        client.isHidden = true
        menu.addItem(client)
        self.clientItem = client

        menu.addItem(NSMenuItem.separator())

        // 4. Pause Video (⌃⌥V)
        let pause = NSMenuItem(title: "Pause Video", action: #selector(handlePause), keyEquivalent: "v")
        pause.keyEquivalentModifierMask = [.control, .option]
        pause.target = self
        menu.addItem(pause)
        self.pauseItem = pause

        // 5. Presets submenu
        let presetsMenu = NSMenu(title: "Framing Presets")
        presetsMenu.autoenablesItems = false

        let p1 = NSMenuItem(title: "Headshot", action: #selector(handlePreset1), keyEquivalent: "1")
        p1.keyEquivalentModifierMask = [.control, .option]
        p1.target = self
        p1.state = .on
        presetsMenu.addItem(p1)
        self.preset1Item = p1

        let p2 = NSMenuItem(title: "Desk View", action: #selector(handlePreset2), keyEquivalent: "2")
        p2.keyEquivalentModifierMask = [.control, .option]
        p2.target = self
        presetsMenu.addItem(p2)
        self.preset2Item = p2

        let p3 = NSMenuItem(title: "Wide Studio", action: #selector(handlePreset3), keyEquivalent: "3")
        p3.keyEquivalentModifierMask = [.control, .option]
        p3.target = self
        presetsMenu.addItem(p3)
        self.preset3Item = p3

        let presetsParent = NSMenuItem(title: "Framing Presets", action: nil, keyEquivalent: "")
        presetsParent.submenu = presetsMenu
        menu.addItem(presetsParent)

        menu.addItem(NSMenuItem.separator())

        // 6. Launch at Login
        let launch = NSMenuItem(title: "Launch at Login", action: #selector(handleLaunchAtLogin), keyEquivalent: "")
        launch.target = self
        launch.state = isLaunchAtLogin ? .on : .off
        menu.addItem(launch)
        self.launchAtLoginItem = launch

        menu.addItem(NSMenuItem.separator())

        // 7. Quit Opal C1 Ark
        let quit = NSMenuItem(title: "Quit Opal C1 Ark", action: #selector(handleQuit), keyEquivalent: "q")
        quit.keyEquivalentModifierMask = [.command]
        quit.target = self
        menu.addItem(quit)

        self.mainMenu = menu
        statusItem?.menu = menu
    }

    public func updateGlyph() {
        let displayState: OpalCameraState
        if isPaused {
            displayState = .paused
        } else {
            displayState = currentState
        }
        statusItem?.button?.image = OpalC1GlyphRenderer.renderGlyph(state: displayState)
        statusItem?.button?.imagePosition = .imageOnly
    }

    public func updateState(state: OpalCameraState, statusLine: String?, clientName: String?, fps: Double, bitrateMbps: Double, tempC: Double) {
        self.currentState = state
        updateGlyph()

        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }
            var telemetryText: String
            switch state {
            case .idle:
                telemetryText = "Idle · 4K Ready"
            case .live:
                telemetryText = String(format: "4K30 · HEVC %.1f Mb/s · %.1f°C", bitrateMbps > 0 ? bitrateMbps : 25.0, tempC > 0 ? tempC : 41.5)
            case .paused:
                telemetryText = "Video Paused (Black Frame)"
            case .disconnected:
                telemetryText = "Camera Disconnected"
            case .attention:
                telemetryText = String(format: "⚠️ Thermal Throttle: %.1f°C", tempC)
            }

            if let custom = statusLine, !custom.isEmpty {
                telemetryText = custom
            }
            self.telemetryItem?.title = telemetryText

            if let client = clientName, !client.isEmpty {
                self.clientItem?.title = "Live in \(client)"
                self.clientItem?.isHidden = false
            } else {
                self.clientItem?.isHidden = true
            }
        }
    }

    @objc private func handlePause() {
        isPaused.toggle()
        pauseItem?.state = isPaused ? .on : .off
        updateGlyph()
        actionCallback?(OpalAction.togglePause.rawValue)
    }

    @objc private func handleLaunchAtLogin() {
        isLaunchAtLogin.toggle()
        launchAtLoginItem?.state = isLaunchAtLogin ? .on : .off
        actionCallback?(OpalAction.toggleLaunchAtLogin.rawValue)
    }

    @objc private func handlePreset1() {
        activePreset = 1
        preset1Item?.state = .on
        preset2Item?.state = .off
        preset3Item?.state = .off
        actionCallback?(OpalAction.selectPreset1.rawValue)
    }

    @objc private func handlePreset2() {
        activePreset = 2
        preset1Item?.state = .off
        preset2Item?.state = .on
        preset3Item?.state = .off
        actionCallback?(OpalAction.selectPreset2.rawValue)
    }

    @objc private func handlePreset3() {
        activePreset = 3
        preset1Item?.state = .off
        preset2Item?.state = .off
        preset3Item?.state = .on
        actionCallback?(OpalAction.selectPreset3.rawValue)
    }

    @objc private func handleQuit() {
        actionCallback?(OpalAction.quit.rawValue)
        NSApplication.shared.terminate(nil)
    }

    public func teardown() {
        if let item = statusItem {
            NSStatusBar.system.removeStatusItem(item)
            statusItem = nil
        }
    }
}
