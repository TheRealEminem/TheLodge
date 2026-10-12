// Draws the app icon (the same mark as core/web/public/favicon.svg: a low sun over an A-frame lodge) and writes
// mac/AppIcon.icns. Run it again only if the mark changes; the result is checked in.
//
//     swift scripts/make-icon.swift
import AppKit

func render(size: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4,
                               hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let ctx = NSGraphicsContext.current!.cgContext
    let canvas = CGFloat(size)
    let body = canvas * 824 / 1024  // macOS icons leave a margin around the tile
    let inset = (canvas - body) / 2
    let k = body / 64
    ctx.translateBy(x: inset, y: inset + body)
    ctx.scaleBy(x: k, y: -k)  // from here on, the 64 x 64 coordinates of favicon.svg, y pointing down

    func hex(_ value: UInt32, _ alpha: CGFloat = 1) -> CGColor {
        CGColor(red: CGFloat((value >> 16) & 255) / 255, green: CGFloat((value >> 8) & 255) / 255, blue: CGFloat(value & 255) / 255, alpha: alpha)
    }
    let space = CGColorSpaceCreateDeviceRGB()
    let tile = CGPath(roundedRect: CGRect(x: 0, y: 0, width: 64, height: 64), cornerWidth: 16, cornerHeight: 16, transform: nil)

    // A soft shadow under the tile.
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -2.2), blur: 3.4, color: CGColor(gray: 0, alpha: 0.28))
    ctx.addPath(tile)
    ctx.setFillColor(hex(0x1B4E37))
    ctx.fillPath()
    ctx.restoreGState()

    ctx.saveGState()
    ctx.addPath(tile)
    ctx.clip()
    let green = CGGradient(colorsSpace: space, colors: [hex(0x2F7B58), hex(0x1B4E37)] as CFArray, locations: [0, 1])!
    ctx.drawLinearGradient(green, start: CGPoint(x: 0, y: 0), end: CGPoint(x: 0, y: 64), options: [])

    let hill = CGMutablePath()
    hill.move(to: CGPoint(x: 0, y: 42))
    hill.addCurve(to: CGPoint(x: 38, y: 39), control1: CGPoint(x: 13, y: 34), control2: CGPoint(x: 26, y: 34))
    hill.addCurve(to: CGPoint(x: 64, y: 34), control1: CGPoint(x: 50, y: 44), control2: CGPoint(x: 56, y: 38))
    hill.addLine(to: CGPoint(x: 64, y: 64))
    hill.addLine(to: CGPoint(x: 0, y: 64))
    hill.closeSubpath()
    ctx.addPath(hill)
    ctx.setFillColor(CGColor(gray: 1, alpha: 0.07))
    ctx.fillPath()

    func band(_ start: CGPoint, _ first: [CGPoint], _ second: [CGPoint], _ alpha: CGFloat) {
        let p = CGMutablePath()
        p.move(to: start)
        p.addCurve(to: first[2], control1: first[0], control2: first[1])
        p.addCurve(to: second[2], control1: second[0], control2: second[1])
        ctx.addPath(p)
        ctx.setStrokeColor(hex(0xF4EEDC, alpha))
        ctx.setLineWidth(1.3)
        ctx.setLineCap(.round)
        ctx.strokePath()
    }
    band(CGPoint(x: -2, y: 49), [CGPoint(x: 12, y: 43), CGPoint(x: 26, y: 44), CGPoint(x: 38, y: 48)],
         [CGPoint(x: 50, y: 52), CGPoint(x: 56, y: 47), CGPoint(x: 66, y: 43)], 0.2)
    band(CGPoint(x: -2, y: 56), [CGPoint(x: 14, y: 51), CGPoint(x: 28, y: 52), CGPoint(x: 40, y: 55)],
         [CGPoint(x: 52, y: 58), CGPoint(x: 56, y: 54), CGPoint(x: 66, y: 51)], 0.13)

    // The sun.
    ctx.saveGState()
    ctx.addEllipse(in: CGRect(x: 39, y: 12, width: 14, height: 14))
    ctx.clip()
    let sun = CGGradient(colorsSpace: space, colors: [hex(0xF8CB5A), hex(0xEE8540)] as CFArray, locations: [0, 1])!
    ctx.drawLinearGradient(sun, start: CGPoint(x: 0, y: 12), end: CGPoint(x: 0, y: 26), options: [])
    ctx.restoreGState()

    // The lodge.
    ctx.setStrokeColor(hex(0xF6EBCF))
    ctx.setLineCap(.round)
    ctx.setLineJoin(.round)
    ctx.setLineWidth(4.4)
    ctx.move(to: CGPoint(x: 13, y: 53))
    ctx.addLine(to: CGPoint(x: 31, y: 28))
    ctx.addLine(to: CGPoint(x: 49, y: 53))
    ctx.strokePath()
    ctx.setLineWidth(2.6)
    ctx.move(to: CGPoint(x: 26.5, y: 53))
    ctx.addLine(to: CGPoint(x: 31, y: 45.5))
    ctx.addLine(to: CGPoint(x: 35.5, y: 53))
    ctx.strokePath()
    ctx.restoreGState()

    // A hairline edge.
    ctx.addPath(CGPath(roundedRect: CGRect(x: 0.5, y: 0.5, width: 63, height: 63), cornerWidth: 15.5, cornerHeight: 15.5, transform: nil))
    ctx.setStrokeColor(CGColor(gray: 1, alpha: 0.16))
    ctx.setLineWidth(1)
    ctx.strokePath()

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

let root = URL(fileURLWithPath: CommandLine.arguments.first.map { ($0 as NSString).deletingLastPathComponent } ?? ".")
    .appendingPathComponent("..").standardized
let iconset = root.appendingPathComponent("mac/AppIcon.iconset", isDirectory: true)
try? FileManager.default.removeItem(at: iconset)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
for (name, size) in [("16x16", 16), ("16x16@2x", 32), ("32x32", 32), ("32x32@2x", 64), ("128x128", 128), ("128x128@2x", 256),
                     ("256x256", 256), ("256x256@2x", 512), ("512x512", 512), ("512x512@2x", 1024)] {
    try render(size: size).write(to: iconset.appendingPathComponent("icon_\(name).png"))
}
let task = Process()
task.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
task.arguments = ["-c", "icns", iconset.path, "-o", root.appendingPathComponent("mac/AppIcon.icns").path]
try task.run()
task.waitUntilExit()
try? FileManager.default.removeItem(at: iconset)
print(task.terminationStatus == 0 ? "Wrote mac/AppIcon.icns" : "iconutil failed")
