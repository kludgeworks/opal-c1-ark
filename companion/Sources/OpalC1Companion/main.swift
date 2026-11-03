import AppKit
import Foundation
import SystemExtensions
import OpalC1UI
import OpalC1Core
import OpalC1Extension

final class ExtensionActivationDelegate: NSObject, OSSystemExtensionRequestDelegate {
    func request(_ request: OSSystemExtensionRequest, didFinishWithResult result: OSSystemExtensionRequest.Result) {
        print("[+] System extension activation succeeded! Result: \(result.rawValue)")
    }

    func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) {
        print("[-] System extension activation error: \(error)")
    }

    func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {
        print("[!] Camera extension requires approval in System Settings > General > Login Items & Extensions > Camera Extensions")
    }

    func request(
        _ request: OSSystemExtensionRequest,
        actionForReplacingExtension existing: OSSystemExtensionProperties,
        withExtension ext: OSSystemExtensionProperties
    ) -> OSSystemExtensionRequest.ReplacementAction {
        return .replace
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

let controller = OpalC1MenuBarController.shared
controller.setup()

let activationDelegate = ExtensionActivationDelegate()

func activateCameraExtension() {
    print("[*] Submitting activation request for com.kludgeworks.opalc1.extension...")
    let request = OSSystemExtensionRequest.activationRequest(
        forExtensionWithIdentifier: "com.kludgeworks.opalc1.extension",
        queue: .main
    )
    request.delegate = activationDelegate
    OSSystemExtensionManager.shared.submitRequest(request)
}

controller.registerCallback { action in
    print("Action received: \(action)")
}

// Auto-trigger extension activation
activateCameraExtension()

print("Opal C1 Companion v0 Menu Bar Extra running.")
app.run()
