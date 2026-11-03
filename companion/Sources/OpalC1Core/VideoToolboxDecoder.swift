import Foundation
import CoreMedia
import VideoToolbox
import CoreVideo

public final class VideoToolboxDecoder {
    private var decompressionSession: VTDecompressionSession?
    private var currentFormatDescription: CMVideoFormatDescription?
    private let destinationPixelFormat: OSType

    public init(pixelFormat: OSType = kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange) {
        self.destinationPixelFormat = pixelFormat
    }

    deinit {
        invalidate()
    }

    public func invalidate() {
        if let session = decompressionSession {
            VTDecompressionSessionInvalidate(session)
            decompressionSession = nil
        }
    }

    /// Prepares decompression session with the given format description.
    public func configure(with formatDescription: CMVideoFormatDescription) throws {
        if currentFormatDescription == formatDescription && decompressionSession != nil {
            return
        }

        invalidate()
        self.currentFormatDescription = formatDescription

        let destinationImageBufferAttributes: [CFString: Any] = [
            kCVPixelBufferPixelFormatTypeKey: destinationPixelFormat,
            kCVPixelBufferMetalCompatibilityKey: true,
            kCVPixelBufferIOSurfacePropertiesKey: [:]
        ]

        var session: VTDecompressionSession?

        let status = VTDecompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            formatDescription: formatDescription,
            decoderSpecification: nil,
            imageBufferAttributes: destinationImageBufferAttributes as CFDictionary,
            decompressionSessionOut: &session
        )

        guard status == noErr, let validSession = session else {
            throw NSError(domain: "OpalC1.VideoToolbox", code: Int(status), userInfo: [NSLocalizedDescriptionKey: "Failed to create VTDecompressionSession: \(status)"])
        }

        self.decompressionSession = validSession
    }

    /// Decodes an Annex B or AVCC NAL unit packet synchronously, returning the CVPixelBuffer and decode duration in milliseconds.
    public func decode(nalData: Data, presentationTime: CMTime = .invalid) throws -> (pixelBuffer: CVPixelBuffer, durationMs: Double)? {
        guard let session = decompressionSession, let formatDesc = currentFormatDescription else {
            throw NSError(domain: "OpalC1.VideoToolbox", code: -1, userInfo: [NSLocalizedDescriptionKey: "Decoder not configured"])
        }

        // Convert NAL to 4-byte length-prefixed AVCC format
        var avccData = Data(capacity: nalData.count + 4)
        var lengthBigEndian = UInt32(nalData.count).bigEndian
        withUnsafeBytes(of: &lengthBigEndian) { avccData.append(contentsOf: $0) }
        avccData.append(nalData)

        var blockBuffer: CMBlockBuffer?
        let memoryBlock = UnsafeMutableRawPointer.allocate(byteCount: avccData.count, alignment: 16)
        avccData.copyBytes(to: memoryBlock.assumingMemoryBound(to: UInt8.self), count: avccData.count)

        let customDeallocator = CMBlockBufferCustomBlockSource(
            version: 0,
            AllocateBlock: nil,
            FreeBlock: { _, refCon, _ in
                refCon.deallocate()
            },
            refCon: memoryBlock
        )
        var customSource = customDeallocator

        let bbStatus = CMBlockBufferCreateWithMemoryBlock(
            allocator: kCFAllocatorDefault,
            memoryBlock: memoryBlock,
            blockLength: avccData.count,
            blockAllocator: kCFAllocatorDefault,
            customBlockSource: &customSource,
            offsetToData: 0,
            dataLength: avccData.count,
            flags: 0,
            blockBufferOut: &blockBuffer
        )

        guard bbStatus == noErr, let validBlockBuffer = blockBuffer else {
            memoryBlock.deallocate()
            throw NSError(domain: "OpalC1.VideoToolbox", code: Int(bbStatus), userInfo: [NSLocalizedDescriptionKey: "Failed to create CMBlockBuffer: \(bbStatus)"])
        }

        var sampleBuffer: CMSampleBuffer?
        var sampleSize = avccData.count
        var timingInfo = CMSampleTimingInfo(
            duration: .invalid,
            presentationTimeStamp: presentationTime.isValid ? presentationTime : CMTime(value: 0, timescale: 30),
            decodeTimeStamp: .invalid
        )

        let sbStatus = CMSampleBufferCreateReady(
            allocator: kCFAllocatorDefault,
            dataBuffer: validBlockBuffer,
            formatDescription: formatDesc,
            sampleCount: 1,
            sampleTimingEntryCount: 1,
            sampleTimingArray: &timingInfo,
            sampleSizeEntryCount: 1,
            sampleSizeArray: &sampleSize,
            sampleBufferOut: &sampleBuffer
        )

        guard sbStatus == noErr, let validSampleBuffer = sampleBuffer else {
            throw NSError(domain: "OpalC1.VideoToolbox", code: Int(sbStatus), userInfo: [NSLocalizedDescriptionKey: "Failed to create CMSampleBuffer: \(sbStatus)"])
        }

        let startTime = CFAbsoluteTimeGetCurrent()
        var flagsOut: VTDecodeInfoFlags = []
        var outputPixelBuffer: CVPixelBuffer?

        let decodeStatus = VTDecompressionSessionDecodeFrame(
            session,
            sampleBuffer: validSampleBuffer,
            flags: [._EnableAsynchronousDecompression],
            infoFlagsOut: &flagsOut
        ) { status, _, imageBuffer, _, _ in
            if status == noErr, let buffer = imageBuffer {
                outputPixelBuffer = buffer
            }
        }

        guard decodeStatus == noErr else {
            throw NSError(domain: "OpalC1.VideoToolbox", code: Int(decodeStatus), userInfo: [NSLocalizedDescriptionKey: "Decode failed: \(decodeStatus)"])
        }

        // Wait for frame decompression to complete synchronously
        VTDecompressionSessionWaitForAsynchronousFrames(session)
        let durationMs = (CFAbsoluteTimeGetCurrent() - startTime) * 1000.0

        if let buffer = outputPixelBuffer {
            return (buffer, durationMs)
        }
        return nil
    }
}
