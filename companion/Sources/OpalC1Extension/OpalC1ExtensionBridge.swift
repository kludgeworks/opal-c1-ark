import Foundation
import CoreMediaIO
import CoreMedia
import CoreVideo
import OpalC1Core

public final class OpalC1ExtensionService {
    public static let shared = OpalC1ExtensionService()

    public private(set) var providerSource: OpalC1ExtensionProviderSource?
    private var decoder: VideoToolboxDecoder?
    private var nalParser: HEVCNALParser?

    public init() {
        self.nalParser = HEVCNALParser()
        self.decoder = VideoToolboxDecoder()
    }

    public func start() {
        guard providerSource == nil else { return }
        let source = OpalC1ExtensionProviderSource(clientQueue: nil)
        self.providerSource = source

        source.deviceSource.streamSource.onStreamStateChanged = { isStreaming in
            print("[*] CMIOExtension stream active state: \(isStreaming)")
        }

        CMIOExtensionProvider.startService(provider: source.provider)
        print("[+] CMIOExtensionProvider.startService called successfully.")
    }

    public var isStreaming: Bool {
        return providerSource?.deviceSource.streamSource.isStreaming ?? false
    }

    public func sendPixelBuffer(_ pixelBuffer: CVPixelBuffer) {
        providerSource?.deviceSource.streamSource.sendPixelBuffer(pixelBuffer)
    }

    public func ingestH265NAL(bytes: UnsafePointer<UInt8>, length: Int) {
        guard let parser = nalParser, let decoder = decoder else { return }
        let data = Data(bytes: bytes, count: length)
        let nals = parser.parseAnnexB(data: data)

        for nal in nals {
            if nal.type.isParameterSet {
                if let desc = try? parser.createFormatDescription() {
                    try? decoder.configure(with: desc)
                }
            } else if nal.type.isKeyFrame || (!nal.type.isParameterSet && nal.type != .prefixSei && nal.type != .suffixSei) {
                if let result = try? decoder.decode(nalData: nal.data) {
                    sendPixelBuffer(result.pixelBuffer)
                }
            }
        }
    }
}

// C-ABI Exports for Python / Companion integration
@_cdecl("opal_cmio_start")
public func opal_cmio_start() -> Int32 {
    OpalC1ExtensionService.shared.start()
    return 0
}

@_cdecl("opal_cmio_is_streaming")
public func opal_cmio_is_streaming() -> Int32 {
    return OpalC1ExtensionService.shared.isStreaming ? 1 : 0
}

@_cdecl("opal_cmio_send_h265")
public func opal_cmio_send_h265(bytes: UnsafePointer<UInt8>, length: Int32) {
    OpalC1ExtensionService.shared.ingestH265NAL(bytes: bytes, length: Int(length))
}
