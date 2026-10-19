import AppKit

/// The menu bar icon: the app's mark as line art (a low sun over an A-frame lodge, with a small door).
/// It matches the app icon and the logo in the sidebar (core/web/components/illustrations.tsx).
enum Mark {
    static let menuIcon = icon(dimmed: false)
    static let menuIconDimmed = icon(dimmed: true)

    private static func icon(dimmed: Bool) -> NSImage {
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: false) { _ in
            NSColor.black.setStroke()
            NSColor.black.setFill()
            NSBezierPath(ovalIn: NSRect(x: 11.1, y: 11.3, width: 4.8, height: 4.8)).fill()  // sun

            let roof = NSBezierPath()  // the A-frame
            roof.move(to: NSPoint(x: 2.4, y: 1.6))
            roof.line(to: NSPoint(x: 8.6, y: 10.6))
            roof.line(to: NSPoint(x: 14.8, y: 1.6))
            roof.lineWidth = 1.9
            roof.lineCapStyle = .round
            roof.lineJoinStyle = .round
            roof.stroke()

            let door = NSBezierPath()
            door.move(to: NSPoint(x: 6.6, y: 1.6))
            door.line(to: NSPoint(x: 8.6, y: 4.9))
            door.line(to: NSPoint(x: 10.6, y: 1.6))
            door.lineWidth = 1.3
            door.lineCapStyle = .round
            door.lineJoinStyle = .round
            door.stroke()
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
