import AppKit
import Foundation

@_cdecl("opal_ui_init")
public func opal_ui_init() -> Int32 {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    OpalC1MenuBarController.shared.setup()
    return 0
}

@_cdecl("opal_ui_set_state")
public func opal_ui_set_state(
    stateCode: Int32,
    statusLine: UnsafePointer<CChar>?,
    clientName: UnsafePointer<CChar>?,
    fps: Double,
    bitrateMbps: Double,
    tempC: Double
) {
    let state = OpalCameraState(rawValue: stateCode) ?? .idle
    let statusStr = statusLine != nil ? String(cString: statusLine!) : nil
    let clientStr = clientName != nil ? String(cString: clientName!) : nil

    OpalC1MenuBarController.shared.updateState(
        state: state,
        statusLine: statusStr,
        clientName: clientStr,
        fps: fps,
        bitrateMbps: bitrateMbps,
        tempC: tempC
    )
}

@_cdecl("opal_ui_register_callback")
public func opal_ui_register_callback(callback: @escaping OpalActionCallback) {
    OpalC1MenuBarController.shared.registerCallback(callback)
}

@_cdecl("opal_ui_pump_events")
public func opal_ui_pump_events(timeoutSeconds: Double) -> Int32 {
    let app = NSApplication.shared
    let expirationDate = Date(timeIntervalSinceNow: max(0.001, timeoutSeconds))

    while true {
        guard let event = app.nextEvent(
            matching: .any,
            until: expirationDate,
            inMode: .default,
            dequeue: true
        ) else {
            break
        }
        app.sendEvent(event)
        app.updateWindows()

        if Date() >= expirationDate {
            break
        }
    }

    return 1
}

@_cdecl("opal_ui_run")
public func opal_ui_run() {
    NSApplication.shared.run()
}

@_cdecl("opal_ui_terminate")
public func opal_ui_terminate() {
    OpalC1MenuBarController.shared.teardown()
    NSApplication.shared.terminate(nil)
}
