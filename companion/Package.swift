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
        .executable(
            name: "OpalC1Companion",
            targets: ["OpalC1Companion"]
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
        .executableTarget(
            name: "OpalC1Companion",
            dependencies: ["OpalC1Core", "OpalC1UI"],
            path: "Sources/OpalC1Companion"
        ),
        .executableTarget(
            name: "OpalC1TestRunner",
            dependencies: ["OpalC1Core"],
            path: "Sources/OpalC1TestRunner"
        )
    ]
)
