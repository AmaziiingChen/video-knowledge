import AppKit
import Foundation

struct SymbolEntry: Decodable {
    let asset: String
    let candidates: [String]?
    let kind: String?
}

guard CommandLine.arguments.count == 3 else {
    fputs("usage: render-macos-symbols.swift <manifest.json> <output-dir>\n", stderr)
    exit(2)
}

let manifestURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
let manifestData = try Data(contentsOf: manifestURL)
let manifest = try JSONDecoder().decode([String: SymbolEntry].self, from: manifestData)
let fileManager = FileManager.default
try fileManager.createDirectory(at: outputURL, withIntermediateDirectories: true)

func renderSymbol(_ image: NSImage, to destination: URL) throws {
    let pixels = 128
    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: pixels,
        pixelsHigh: pixels,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else {
        throw NSError(domain: "KnowledgeHubSymbols", code: 1)
    }

    NSGraphicsContext.saveGraphicsState()
    guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        NSGraphicsContext.restoreGraphicsState()
        throw NSError(domain: "KnowledgeHubSymbols", code: 2)
    }
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: pixels, height: pixels).fill()

    let configured = image.withSymbolConfiguration(
        NSImage.SymbolConfiguration(pointSize: 82, weight: .regular)
    ) ?? image
    let sourceSize = configured.size
    let maximum = CGFloat(108)
    let scale = min(maximum / max(sourceSize.width, 1), maximum / max(sourceSize.height, 1))
    let drawSize = NSSize(width: sourceSize.width * scale, height: sourceSize.height * scale)
    let drawRect = NSRect(
        x: (CGFloat(pixels) - drawSize.width) / 2,
        y: (CGFloat(pixels) - drawSize.height) / 2,
        width: drawSize.width,
        height: drawSize.height
    )
    configured.draw(in: drawRect, from: .zero, operation: .sourceOver, fraction: 1)
    context.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()

    guard let png = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "KnowledgeHubSymbols", code: 3)
    }
    try png.write(to: destination, options: .atomic)
}

var renderedAssets = Set<String>()
for (logicalName, entry) in manifest.sorted(by: { $0.key < $1.key }) {
    if entry.kind == "brand" || renderedAssets.contains(entry.asset) {
        continue
    }
    guard let candidates = entry.candidates, !candidates.isEmpty else {
        fputs("missing SF Symbol candidates for \(logicalName)\n", stderr)
        exit(3)
    }

    var resolvedImage: NSImage?
    var resolvedName: String?
    for candidate in candidates {
        if let image = NSImage(systemSymbolName: candidate, accessibilityDescription: nil) {
            resolvedImage = image
            resolvedName = candidate
            break
        }
    }
    guard let image = resolvedImage, let symbolName = resolvedName else {
        fputs("no installed SF Symbol found for \(logicalName): \(candidates.joined(separator: ", "))\n", stderr)
        exit(4)
    }

    let destination = outputURL.appendingPathComponent(entry.asset)
    try renderSymbol(image, to: destination)
    renderedAssets.insert(entry.asset)
    print("rendered:\(entry.asset)")
    if symbolName != candidates[0] {
        fputs("fallback symbol for \(logicalName): \(symbolName)\n", stderr)
    }
}
