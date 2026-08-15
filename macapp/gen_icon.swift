import AppKit

// ABcode 应用图标: 圆角蓝底 + "AB" 文字
let size: CGFloat = 1024
let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()

// 背景圆角矩形
let rect = NSRect(x: 0, y: 0, width: size, height: size)
let path = NSBezierPath(roundedRect: rect, xRadius: 200, yRadius: 200)
NSColor(calibratedRed: 0.31, green: 0.43, blue: 0.97, alpha: 1.0).setFill()
path.fill()

// 渐变装饰
let gradient = NSGradient(colors: [
    NSColor(calibratedRed: 0.55, green: 0.70, blue: 1.0, alpha: 0.35),
    NSColor(calibratedRed: 0.31, green: 0.43, blue: 0.97, alpha: 0.0),
])!
gradient.draw(in: NSRect(x: 0, y: 450, width: size, height: 574), angle: 90)

// 文字 "AB"
let text = "AB" as NSString
let font = NSFont.systemFont(ofSize: 430, weight: .bold)
let attrs: [NSAttributedString.Key: Any] = [
    .font: font,
    .foregroundColor: NSColor.white,
]
let textSize = text.size(withAttributes: attrs)
let textRect = NSRect(
    x: (size - textSize.width) / 2,
    y: (size - textSize.height) / 2 - 30,
    width: textSize.width,
    height: textSize.height
)
text.draw(in: textRect, withAttributes: attrs)

image.unlockFocus()

// 保存 PNG
let rep = NSBitmapImageRep(data: image.tiffRepresentation!)!
let pngData = rep.representation(using: .png, properties: [:])!
try! pngData.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
print("icon written")
