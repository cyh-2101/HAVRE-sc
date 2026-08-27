// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "HAVREiPhone",
    platforms: [.iOS(.v17)],
    products: [
        .library(name: "HAVREMobileCore", targets: ["HAVREMobileCore"]),
        .executable(name: "HAVREiPhone", targets: ["HAVREiPhone"]),
        .executable(name: "HAVREMobileBenchmarks", targets: ["HAVREMobileBenchmarks"]),
    ],
    targets: [
        .target(name: "HAVREMobileCore"),
        .executableTarget(
            name: "HAVREiPhone",
            dependencies: ["HAVREMobileCore"]
        ),
        .executableTarget(
            name: "HAVREMobileBenchmarks",
            dependencies: ["HAVREMobileCore"]
        ),
        .testTarget(
            name: "HAVREMobileCoreTests",
            dependencies: ["HAVREMobileCore"]
        ),
    ]
)
