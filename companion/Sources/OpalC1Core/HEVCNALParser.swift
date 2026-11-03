import Foundation
import CoreMedia

public enum HEVCNALType: UInt8 {
    case trailN = 0
    case trailR = 1
    case tsaN = 2
    case tsaR = 3
    case stsaN = 4
    case stsaR = 5
    case radlN = 6
    case radlR = 7
    case raslN = 8
    case raslR = 9
    case idrWRadl = 19
    case idrNLp = 20
    case craNut = 21
    case vps = 32
    case sps = 33
    case pps = 34
    case prefixSei = 39
    case suffixSei = 40
    case unknown = 255

    public var isParameterSet: Bool {
        return self == .vps || self == .sps || self == .pps
    }

    public var isKeyFrame: Bool {
        return self == .idrWRadl || self == .idrNLp || self == .craNut
    }
}

public struct NALUnit {
    public let type: HEVCNALType
    public let rawType: UInt8
    public let data: Data
    public let offset: Int

    public init(rawType: UInt8, data: Data, offset: Int) {
        self.rawType = rawType
        self.type = HEVCNALType(rawValue: rawType) ?? .unknown
        self.data = data
        self.offset = offset
    }
}

public final class HEVCNALParser {
    public private(set) var vps: Data?
    public private(set) var sps: Data?
    public private(set) var pps: Data?

    public init() {}

    /// Parses Annex B byte stream into individual NAL units.
    public func parseAnnexB(data: Data) -> [NALUnit] {
        var units: [NALUnit] = []
        let bytes = [UInt8](data)
        let count = bytes.count
        var index = 0

        // Find start codes (0x000001 or 0x00000001)
        var startIndices: [(index: Int, codeLen: Int)] = []

        while index < count - 2 {
            if bytes[index] == 0 && bytes[index + 1] == 0 {
                if bytes[index + 2] == 1 {
                    startIndices.append((index: index + 3, codeLen: 3))
                    index += 3
                    continue
                } else if index < count - 3 && bytes[index + 2] == 0 && bytes[index + 3] == 1 {
                    startIndices.append((index: index + 4, codeLen: 4))
                    index += 4
                    continue
                }
            }
            index += 1
        }

        for i in 0..<startIndices.count {
            let start = startIndices[i].index
            let end: Int
            if i + 1 < startIndices.count {
                // Subtract codeLen of the next start code
                let nextCodeLen = startIndices[i + 1].codeLen
                end = startIndices[i + 1].index - nextCodeLen
            } else {
                end = count
            }

            guard end > start else { continue }
            let nalData = data.subdata(in: start..<end)
            guard !nalData.isEmpty else { continue }

            let nalHeader = nalData[0]
            let nalTypeRaw = (nalHeader >> 1) & 0x3F
            let unit = NALUnit(rawType: nalTypeRaw, data: nalData, offset: start)

            if unit.type == .vps { self.vps = nalData }
            if unit.type == .sps { self.sps = nalData }
            if unit.type == .pps { self.pps = nalData }

            units.append(unit)
        }

        return units
    }

    /// Creates a CMVideoFormatDescription from cached VPS, SPS, and PPS.
    public func createFormatDescription() throws -> CMVideoFormatDescription? {
        guard let vps = vps, let sps = sps, let pps = pps else {
            return nil
        }

        var formatDesc: CMVideoFormatDescription?
        var status: OSStatus = noErr

        vps.withUnsafeBytes { vpsRaw in
            sps.withUnsafeBytes { spsRaw in
                pps.withUnsafeBytes { ppsRaw in
                    guard let vpsPtr = vpsRaw.baseAddress?.assumingMemoryBound(to: UInt8.self),
                          let spsPtr = spsRaw.baseAddress?.assumingMemoryBound(to: UInt8.self),
                          let ppsPtr = ppsRaw.baseAddress?.assumingMemoryBound(to: UInt8.self) else {
                        status = -1
                        return
                    }

                    let pointers = [vpsPtr, spsPtr, ppsPtr]
                    let sizes = [vps.count, sps.count, pps.count]

                    status = CMVideoFormatDescriptionCreateFromHEVCParameterSets(
                        allocator: kCFAllocatorDefault,
                        parameterSetCount: 3,
                        parameterSetPointers: pointers,
                        parameterSetSizes: sizes,
                        nalUnitHeaderLength: 4,
                        extensions: nil,
                        formatDescriptionOut: &formatDesc
                    )
                }
            }
        }

        guard status == noErr, let desc = formatDesc else {
            throw NSError(domain: "OpalC1.HEVC", code: Int(status), userInfo: [NSLocalizedDescriptionKey: "Failed to create CMVideoFormatDescription: \(status)"])
        }

        return desc
    }
}
