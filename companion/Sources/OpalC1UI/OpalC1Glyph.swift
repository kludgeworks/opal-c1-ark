import AppKit

public enum OpalCameraState: Int32 {
    case idle = 0          // Connected, 0 clients streaming -> Open outline circle
    case live = 1          // Actively streaming -> Filled solid circle
    case paused = 2        // Video Paused -> Diagonal slash
    case disconnected = 3  // Disconnected -> 50% opacity dashed circle
    case attention = 4     // Needs attention -> Orange badge dot
}

public final class OpalC1GlyphRenderer {
    public static func renderGlyph(state: OpalCameraState) -> NSImage {
        let size = NSSize(width: 22, height: 18)
        let image = NSImage(size: size, flipped: false) { rect in
            guard let context = NSGraphicsContext.current?.cgContext else { return false }

            let isAttention = (state == .attention)
            let isDisconnected = (state == .disconnected)

            // Drawing dimensions
            let bodyRect = NSRect(x: 2, y: 2, width: 14, height: 14)
            let lensCenter = NSPoint(x: 9, y: 9)
            let lensRadius: CGFloat = 4.0

            let strokeColor = isDisconnected ? NSColor.labelColor.withAlphaComponent(0.45) : NSColor.labelColor
            strokeColor.setStroke()

            // Outer camera pill
            let bodyPath = NSBezierPath(roundedRect: bodyRect, xRadius: 3.5, yRadius: 3.5)
            bodyPath.lineWidth = 1.3
            if isDisconnected {
                let pattern: [CGFloat] = [2.0, 1.5]
                bodyPath.setLineDash(pattern, count: 2, phase: 0.0)
            }
            bodyPath.stroke()

            // Small lens mount bump on top
            let bumpPath = NSBezierPath()
            bumpPath.move(to: NSPoint(x: 6.5, y: 16))
            bumpPath.line(to: NSPoint(x: 11.5, y: 16))
            bumpPath.lineWidth = 1.3
            bumpPath.stroke()

            // Lens state
            switch state {
            case .idle:
                // Open circle lens outline
                let lensPath = NSBezierPath(ovalIn: NSRect(x: lensCenter.x - lensRadius,
                                                           y: lensCenter.y - lensRadius,
                                                           width: lensRadius * 2,
                                                           height: lensRadius * 2))
                lensPath.lineWidth = 1.3
                lensPath.stroke()

            case .live:
                // Filled solid circle
                strokeColor.setFill()
                let lensPath = NSBezierPath(ovalIn: NSRect(x: lensCenter.x - lensRadius,
                                                           y: lensCenter.y - lensRadius,
                                                           width: lensRadius * 2,
                                                           height: lensRadius * 2))
                lensPath.fill()

            case .paused:
                // Circle with diagonal slash
                let lensPath = NSBezierPath(ovalIn: NSRect(x: lensCenter.x - lensRadius,
                                                           y: lensCenter.y - lensRadius,
                                                           width: lensRadius * 2,
                                                           height: lensRadius * 2))
                lensPath.lineWidth = 1.3
                lensPath.stroke()

                let slashPath = NSBezierPath()
                slashPath.move(to: NSPoint(x: lensCenter.x - lensRadius - 1, y: lensCenter.y - lensRadius - 1))
                slashPath.line(to: NSPoint(x: lensCenter.x + lensRadius + 1, y: lensCenter.y + lensRadius + 1))
                slashPath.lineWidth = 1.5
                slashPath.stroke()

            case .disconnected:
                // Dashed circle lens
                let lensPath = NSBezierPath(ovalIn: NSRect(x: lensCenter.x - lensRadius,
                                                           y: lensCenter.y - lensRadius,
                                                           width: lensRadius * 2,
                                                           height: lensRadius * 2))
                lensPath.lineWidth = 1.2
                let pattern: [CGFloat] = [1.5, 1.5]
                lensPath.setLineDash(pattern, count: 2, phase: 0.0)
                lensPath.stroke()

            case .attention:
                // Outline circle lens + solid orange badge dot at top right
                let lensPath = NSBezierPath(ovalIn: NSRect(x: lensCenter.x - lensRadius,
                                                           y: lensCenter.y - lensRadius,
                                                           width: lensRadius * 2,
                                                           height: lensRadius * 2))
                lensPath.lineWidth = 1.3
                lensPath.stroke()

                // Warning badge dot
                NSColor.systemOrange.setFill()
                let badgeRect = NSRect(x: 15, y: 11, width: 5.5, height: 5.5)
                let badgePath = NSBezierPath(ovalIn: badgeRect)
                badgePath.fill()
            }

            return true
        }

        // Set as template unless it has a colored badge
        image.isTemplate = (state != .attention)
        return image
    }
}
