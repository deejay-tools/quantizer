// Disegna l'icona di Quantizer (PNG 1024×1024): forma d'onda su griglia a battute.
// Uso: swiftc -o make-icon make-icon.swift && ./make-icon icon.png

import AppKit

let size = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"

let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                           bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext

// sfondo: quadrato arrotondato secondo la griglia delle icone macOS (824 pt, margine 100)
let tile = CGRect(x: 100, y: 100, width: 824, height: 824)
let shape = CGPath(roundedRect: tile, cornerWidth: 185, cornerHeight: 185, transform: nil)
ctx.saveGState()
ctx.addPath(shape)
ctx.clip()
let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [
    CGColor(red: 1.0, green: 0.48, blue: 0.20, alpha: 1),     // #ff7a33
    CGColor(red: 0.78, green: 0.25, blue: 0.04, alpha: 1),    // #c7400a
] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(gradient, start: CGPoint(x: 0, y: 924), end: CGPoint(x: 0, y: 100), options: [])

// griglia: linee di battuta più marcate, beat più tenui
let left = 170.0, right = 854.0, top = 800.0, bottom = 224.0
let beats = 8
for k in 0...beats {
    let x = left + (right - left) * Double(k) / Double(beats)
    let bar = k % 4 == 0
    ctx.setStrokeColor(CGColor(gray: 1, alpha: bar ? 0.85 : 0.35))
    ctx.setLineWidth(bar ? 10 : 5)
    ctx.move(to: CGPoint(x: x, y: bottom))
    ctx.addLine(to: CGPoint(x: x, y: top))
    ctx.strokePath()
}

// forma d'onda: colpi che decadono subito dopo ogni beat
let mid = (top + bottom) / 2
ctx.setFillColor(CGColor(gray: 1, alpha: 1))
let bars = 32
let step = (right - left) / Double(bars)
for i in 0..<bars {
    let phase = Double(i % (bars / beats)) / Double(bars / beats)  // 0 sul beat
    let accent = (i / (bars / beats)) % 4 == 0 ? 1.0 : 0.8
    let amp = (0.12 + 0.88 * exp(-5.5 * phase)) * accent * (top - bottom) * 0.44
    let x = left + step * Double(i) + step * 0.2
    let r = CGRect(x: x, y: mid - amp, width: step * 0.6, height: amp * 2)
    ctx.addPath(CGPath(roundedRect: r, cornerWidth: step * 0.3, cornerHeight: step * 0.3, transform: nil))
}
ctx.fillPath()
ctx.restoreGState()

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
print("icona scritta in \(out)")
