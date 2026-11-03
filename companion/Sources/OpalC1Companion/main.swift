import AppKit
import Foundation
import OpalC1UI
import OpalC1Core

// Standalone executable entrypoint for Opal C1 Companion UI
let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let controller = OpalC1MenuBarController.shared
controller.setup()

controller.registerCallback { action in
    print("Action received: \(action)")
}

print("Opal C1 Companion v0 Menu Bar Extra started.")
app.run()
