import Foundation
import CoreMediaIO

public final class OpalC1ExtensionDeviceSource: NSObject, CMIOExtensionDeviceSource {
    public private(set) var device: CMIOExtensionDevice!
    public private(set) var streamSource: OpalC1ExtensionStreamSource!

    public init(localizedName: String = "Opal C1 (Ark Edition)") {
        super.init()
        let deviceID = UUID(uuidString: "74B46E56-8A39-44F4-A447-1B903E7F63D0")!
        self.device = CMIOExtensionDevice(
            localizedName: localizedName,
            deviceID: deviceID,
            legacyDeviceID: nil,
            source: self
        )

        self.streamSource = OpalC1ExtensionStreamSource(localizedName: "4K Video Stream")
        do {
            try self.device.addStream(self.streamSource.stream)
        } catch {
            print("[-] Failed to add stream to device: \(error)")
        }
    }

    public var availableProperties: Set<CMIOExtensionProperty> {
        return [.deviceModel]
    }

    public func deviceProperties(forProperties properties: Set<CMIOExtensionProperty>) throws -> CMIOExtensionDeviceProperties {
        let response = CMIOExtensionDeviceProperties(dictionary: [:])
        if properties.contains(.deviceModel) {
            response.model = "Opal C1 (Ark Edition)"
        }
        return response
    }

    public func setDeviceProperties(_ deviceProperties: CMIOExtensionDeviceProperties) throws {
    }
}
