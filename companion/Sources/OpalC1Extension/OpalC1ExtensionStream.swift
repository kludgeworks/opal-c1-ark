import Foundation
import CoreMediaIO
import CoreMedia
import CoreVideo

public final class OpalC1ExtensionStreamSource: NSObject, CMIOExtensionStreamSource {
    public private(set) var stream: CMIOExtensionStream!
    public private(set) var streamFormats: [CMIOExtensionStreamFormat] = []
    public private(set) var activeFormatIndex: Int = 0
    public private(set) var isStreaming: Bool = false

    private var formatDescription4K: CMVideoFormatDescription?
    private var formatDescription1080p: CMVideoFormatDescription?

    public var onStreamStateChanged: ((Bool) -> Void)?

    public init(localizedName: String) {
        super.init()
        let streamID = UUID(uuidString: "E85A1D20-562F-46C4-82D0-2C5E789B1F20")!

        // Format 1: 4K (3840x2160 @ 30 FPS)
        var desc4K: CMFormatDescription?
        CMVideoFormatDescriptionCreate(
            allocator: kCFAllocatorDefault,
            codecType: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
            width: 3840,
            height: 2160,
            extensions: nil,
            formatDescriptionOut: &desc4K
        )
        self.formatDescription4K = desc4K

        if let f4k = desc4K {
            let format4K = CMIOExtensionStreamFormat(
                formatDescription: f4k,
                maxFrameDuration: CMTime(value: 1, timescale: 30),
                minFrameDuration: CMTime(value: 1, timescale: 30),
                validFrameDurations: nil
            )
            streamFormats.append(format4K)
        }

        // Format 2: 1080p (1920x1080 @ 60 FPS)
        var desc1080p: CMFormatDescription?
        CMVideoFormatDescriptionCreate(
            allocator: kCFAllocatorDefault,
            codecType: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
            width: 1920,
            height: 1080,
            extensions: nil,
            formatDescriptionOut: &desc1080p
        )
        self.formatDescription1080p = desc1080p

        if let f1080 = desc1080p {
            let format1080 = CMIOExtensionStreamFormat(
                formatDescription: f1080,
                maxFrameDuration: CMTime(value: 1, timescale: 60),
                minFrameDuration: CMTime(value: 1, timescale: 60),
                validFrameDurations: nil
            )
            streamFormats.append(format1080)
        }

        self.stream = CMIOExtensionStream(
            localizedName: localizedName,
            streamID: streamID,
            direction: .source,
            clockType: .hostTime,
            source: self
        )
    }

    public var formats: [CMIOExtensionStreamFormat] {
        return streamFormats
    }

    public var availableProperties: Set<CMIOExtensionProperty> {
        return [.streamActiveFormatIndex, .streamFrameDuration]
    }

    public func streamProperties(forProperties properties: Set<CMIOExtensionProperty>) throws -> CMIOExtensionStreamProperties {
        let response = CMIOExtensionStreamProperties(dictionary: [:])
        if properties.contains(.streamActiveFormatIndex) {
            response.activeFormatIndex = activeFormatIndex
        }
        if properties.contains(.streamFrameDuration) {
            response.frameDuration = CMTime(value: 1, timescale: 30)
        }
        return response
    }

    public func setStreamProperties(_ streamProperties: CMIOExtensionStreamProperties) throws {
        if let index = streamProperties.activeFormatIndex, index < streamFormats.count {
            self.activeFormatIndex = index
        }
    }

    public func authorizedToStartStream(for client: CMIOExtensionClient) -> Bool {
        return true
    }

    public func startStream() throws {
        self.isStreaming = true
        onStreamStateChanged?(true)
    }

    public func stopStream() throws {
        self.isStreaming = false
        onStreamStateChanged?(false)
    }

    public func sendPixelBuffer(_ pixelBuffer: CVPixelBuffer, timestamp: CMTime = .invalid) {
        guard isStreaming else { return }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let formatDesc = (width == 3840) ? formatDescription4K : (formatDescription1080p ?? formatDescription4K)
        guard let validFormatDesc = formatDesc else { return }

        let pts = timestamp.isValid ? timestamp : CMTime(value: CMTimeValue(mach_absolute_time()), timescale: 1_000_000_000)
        var timing = CMSampleTimingInfo(
            duration: CMTime(value: 1, timescale: 30),
            presentationTimeStamp: pts,
            decodeTimeStamp: .invalid
        )

        var sampleBuffer: CMSampleBuffer?
        let status = CMSampleBufferCreateForImageBuffer(
            allocator: kCFAllocatorDefault,
            imageBuffer: pixelBuffer,
            dataReady: true,
            makeDataReadyCallback: nil,
            refcon: nil,
            formatDescription: validFormatDesc,
            sampleTiming: &timing,
            sampleBufferOut: &sampleBuffer
        )

        if status == noErr, let buffer = sampleBuffer {
            let hostTime = mach_absolute_time()
            stream.send(buffer, discontinuity: [], hostTimeInNanoseconds: hostTime)
        }
    }
}
