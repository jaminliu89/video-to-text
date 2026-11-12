// DRE Media Workbench native OCR worker.
// Compile: swiftc -O native/apple_vision/ocr.swift -o /tmp/dre-ocr
// Run: /tmp/dre-ocr /absolute/path/to/frame.jpg
// Prints JSON. No network, no LLM, no cloud fallback.
import Foundation
import Vision
import AppKit

struct TextItem: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct Output: Codable {
    let ok: Bool
    let items: [TextItem]
}

guard CommandLine.arguments.count == 2 else {
    fputs("usage: dre-ocr /path/to/image\n", stderr)
    exit(2)
}
let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
request.recognitionLanguages = ["zh-Hans", "en-US"]
try VNImageRequestHandler(url: imageURL, options: [:]).perform([request])
let results = (request.results ?? []).compactMap { item -> TextItem? in
    guard let candidate = item.topCandidates(1).first else { return nil }
    return TextItem(
        text: candidate.string,
        confidence: candidate.confidence,
        x: Double(item.boundingBox.minX),
        y: Double(item.boundingBox.minY),
        width: Double(item.boundingBox.width),
        height: Double(item.boundingBox.height)
    )
}
let output = Output(ok: true, items: results)
let data = try JSONEncoder().encode(output)
FileHandle.standardOutput.write(data)
