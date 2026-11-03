// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "OpalC1Companion",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .library(
            name: "OpalC1Core",
            targets: ["OpalC1Core"]
        ),
        .library(
            name: "OpalC1UI",
            type: .dynamic,
            targets: ["OpalC1UI"]
        ),
        .library(
            name: "OpalC1Extension",
            type: .dynamic,
            targets: ["OpalC1Extension"]
        ),
        .executable(
            name: "OpalC1Companion",
            targets: ["OpalC1Companion"]
        ),
        .executable(
            name: "OpalC1ExtensionService",
            targets: ["OpalC1ExtensionService"]
        ),
        .executable(
            name: "OpalC1TestRunner",
            targets: ["OpalC1TestRunner"]
        )
    ],
    dependencies: [],
    targets: [
        .target(
            name: "OpalC1Core",
            dependencies: [],
            path: "Sources/OpalC1Core"
        ),
        .target(
            name: "OpalC1UI",
            dependencies: ["OpalC1Core"],
            path: "Sources/OpalC1UI"
        ),
        .target(
            name: "OpalC1Extension",
            dependencies: ["OpalC1Core"],
            path: "Sources/OpalC1Extension"
        ),
        .executableTarget(
            name: "OpalC1Companion",
            dependencies: ["OpalC1Core", "OpalC1UI", "OpalC1Extension"],
            path: "Sources/OpalC1Companion"
        ),
        .executableTarget(
            name: "OpalC1ExtensionService",
            dependencies: ["OpalC1Core", "OpalC1Extension"],
            path: "Sources/OpalC1ExtensionService"
        ),
        .executableTarget(
            name: "OpalC1TestRunner",
            dependencies: ["OpalC1Core"],
            path: "Sources/OpalC1TestRunner"
        )
    ]
)
