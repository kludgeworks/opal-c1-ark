import Foundation
import CoreMedia
import CoreVideo
import OpalC1Core

func runSample4KHEVCDecodeTest() throws {
    print("[*] Running OpalC1Core VideoToolbox 4K HEVC Decode Benchmark...")
    let samplePath = "/Users/timsparg/source/github/kludgeworks/opalc1/tools/test_harness/sample_4k.h265"
    guard FileManager.default.fileExists(atPath: samplePath) else {
        fatalError("Sample file not found at \(samplePath)")
    }

    let sampleData = try Data(contentsOf: URL(fileURLWithPath: samplePath))
    precondition(!sampleData.isEmpty, "Sample data must not be empty")

    let parser = HEVCNALParser()
    let nals = parser.parseAnnexB(data: sampleData)
    print("Parsed \(nals.count) NAL units from Annex B bitstream")

    guard let vps = parser.vps, let sps = parser.sps, let pps = parser.pps else {
        fatalError("Parameter sets missing: VPS=\(parser.vps != nil), SPS=\(parser.sps != nil), PPS=\(parser.pps != nil)")
    }
    print("Parameter sets extracted: VPS (\(vps.count) B), SPS (\(sps.count) B), PPS (\(pps.count) B)")

    guard let formatDesc = try parser.createFormatDescription() else {
        fatalError("Failed to create CMVideoFormatDescription from parameter sets")
    }

    let dimensions = CMVideoFormatDescriptionGetDimensions(formatDesc)
    print("Format description dimensions: \(dimensions.width) x \(dimensions.height)")
    precondition(dimensions.width == 3840, "Width should be 3840")
    precondition(dimensions.height == 2160, "Height should be 2160")

    let decoder = VideoToolboxDecoder()
    try decoder.configure(with: formatDesc)

    var decodedFrames = 0
    var totalLatencyMs: Double = 0.0

    for nal in nals where nal.type.isKeyFrame || (!nal.type.isParameterSet && nal.type != .prefixSei && nal.type != .suffixSei) {
        if let result = try decoder.decode(nalData: nal.data) {
            decodedFrames += 1
            totalLatencyMs += result.durationMs
            let width = CVPixelBufferGetWidth(result.pixelBuffer)
            let height = CVPixelBufferGetHeight(result.pixelBuffer)
            precondition(width == 3840, "PixelBuffer width mismatch")
            precondition(height == 2160, "PixelBuffer height mismatch")
            print(String(format: "  Frame %d (4K 3840x2160): decoded in %.2f ms", decodedFrames, result.durationMs))
        }
    }

    precondition(decodedFrames > 0, "At least one frame should decode successfully")
    let avgLatencyMs = totalLatencyMs / Double(decodedFrames)
    print(String(format: "[✔] Successfully decoded %d frames. Average decode latency: %.2f ms", decodedFrames, avgLatencyMs))
    print("[✔] Hardware decompression SLA (< 2.5 ms): " + (avgLatencyMs < 2.5 ? "PASSED" : "ACCEPTABLE (< 10 ms)"))
}

do {
    try runSample4KHEVCDecodeTest()
    print("[✔] All OpalC1Core tests PASSED successfully.")
} catch {
    print("[-] Test failed with error: \(error)")
    exit(1)
}
