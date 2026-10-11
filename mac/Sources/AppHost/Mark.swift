import AppKit

/// The menu bar icon: the family mark as line art (a low sun, a ridge, a trail winding up to it).
/// Each family app swaps the trail for its own motif, keeping the sun and the ridge.
enum Mark {
    static let menuIcon = icon(dimmed: false)
    static let menuIconDimmed = icon(dimmed: true)

    private static func icon(dimmed: Bool) -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { _ in
            NSColor.black.setStroke()
            NSColor.black.setFill()
            NSBezierPath(ovalIn: NSRect(x: 11.2, y: 10.6, width: 4.6, height: 4.6)).fill()  // sun

            let ridge = NSBezierPath()
            ridge.move(to: NSPoint(x: 1.2, y: 7.2))
            ridge.curve(to: NSPoint(x: 16.8, y: 7.6), controlPoint1: NSPoint(x: 5.5, y: 11.2), controlPoint2: NSPoint(x: 11, y: 10.6))
            ridge.lineWidth = 1.3
            ridge.lineCapStyle = .round
            ridge.stroke()

            let trail = NSBezierPath()  // ← the part a sibling app replaces with its own motif
            trail.move(to: NSPoint(x: 5.2, y: 1.2))
            trail.curve(to: NSPoint(x: 8.6, y: 4.6), controlPoint1: NSPoint(x: 6.2, y: 3.4), controlPoint2: NSPoint(x: 9.8, y: 3.2))
            trail.curve(to: NSPoint(x: 10.8, y: 7.6), controlPoint1: NSPoint(x: 7.4, y: 6), controlPoint2: NSPoint(x: 9.2, y: 7.2))
            trail.lineWidth = 1.9
            trail.lineCapStyle = .round
            trail.lineJoinStyle = .round
            trail.stroke()
            return true
        }
        image.isTemplate = true
        guard dimmed else { return image }
        let faded = NSImage(size: image.size, flipped: false) { rect in
            image.draw(in: rect, from: .zero, operation: .sourceOver, fraction: 0.45)
            return true
        }
        faded.isTemplate = true
        return faded
    }
}
