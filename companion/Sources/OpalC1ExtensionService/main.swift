import Foundation
import CoreMediaIO
import OpalC1Extension

let service = OpalC1ExtensionService.shared
service.start()

print("[+] Opal C1 CMIO Extension service running. Press Ctrl+C to terminate.")
CFRunLoopRun()
