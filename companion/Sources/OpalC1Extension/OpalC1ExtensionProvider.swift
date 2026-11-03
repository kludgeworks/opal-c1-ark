import Foundation
import CoreMediaIO

public final class OpalC1ExtensionProviderSource: NSObject, CMIOExtensionProviderSource {
    public private(set) var provider: CMIOExtensionProvider!
    public private(set) var deviceSource: OpalC1ExtensionDeviceSource!

    public init(clientQueue: DispatchQueue? = nil) {
        super.init()
        self.provider = CMIOExtensionProvider(source: self, clientQueue: clientQueue)
        self.deviceSource = OpalC1ExtensionDeviceSource()

        do {
            try self.provider.addDevice(self.deviceSource.device)
            print("[+] Opal C1 CMIOExtension device registered successfully.")
        } catch {
            print("[-] Failed to register device with provider: \(error)")
        }
    }

    public func connect(to client: CMIOExtensionClient) throws {
        print("[+] Client connected to Opal C1 extension: \(client.clientID)")
    }

    public func disconnect(from client: CMIOExtensionClient) {
        print("[-] Client disconnected from Opal C1 extension: \(client.clientID)")
    }

    public var availableProperties: Set<CMIOExtensionProperty> {
        return [.providerManufacturer]
    }

    public func providerProperties(forProperties properties: Set<CMIOExtensionProperty>) throws -> CMIOExtensionProviderProperties {
        let response = CMIOExtensionProviderProperties(dictionary: [:])
        if properties.contains(.providerManufacturer) {
            response.manufacturer = "Kludgeworks"
        }
        return response
    }

    public func setProviderProperties(_ providerProperties: CMIOExtensionProviderProperties) throws {
    }
}
