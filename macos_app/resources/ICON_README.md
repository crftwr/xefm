# XeFM Application Icon

## Current Icon

The current `XeFM.icns` file is a placeholder icon created automatically. It features:
- Blue gradient background
- "XeFM" text in white
- "File Manager" subtitle
- Rounded rectangle border

## Replacing the Icon

To replace the placeholder icon with your custom icon:

### Option 1: Replace the .icns file directly

If you already have a `.icns` file:

```bash
# Replace the icon file
cp your_custom_icon.icns macos_app/resources/XeFM.icns

# Rebuild the app
cd macos_app
./build.sh
```

### Option 2: Create .icns from PNG

If you have a PNG file (1024x1024 recommended):

```bash
# Create iconset directory
mkdir XeFM.iconset

# Generate all required sizes
sips -z 16 16     your_icon.png --out XeFM.iconset/icon_16x16.png
sips -z 32 32     your_icon.png --out XeFM.iconset/icon_16x16@2x.png
sips -z 32 32     your_icon.png --out XeFM.iconset/icon_32x32.png
sips -z 64 64     your_icon.png --out XeFM.iconset/icon_32x32@2x.png
sips -z 128 128   your_icon.png --out XeFM.iconset/icon_128x128.png
sips -z 256 256   your_icon.png --out XeFM.iconset/icon_128x128@2x.png
sips -z 256 256   your_icon.png --out XeFM.iconset/icon_256x256.png
sips -z 512 512   your_icon.png --out XeFM.iconset/icon_256x256@2x.png
sips -z 512 512   your_icon.png --out XeFM.iconset/icon_512x512.png
sips -z 1024 1024 your_icon.png --out XeFM.iconset/icon_512x512@2x.png

# Convert to .icns
iconutil -c icns XeFM.iconset -o macos_app/resources/XeFM.icns

# Clean up
rm -rf XeFM.iconset

# Rebuild the app
cd macos_app
./build.sh
```

### Option 3: Use a design tool

Create your icon using:
- **Sketch** - Export as .icns directly
- **Figma** - Export as PNG, then convert using Option 2
- **Adobe Illustrator** - Export as PNG, then convert using Option 2
- **Icon Composer** (Xcode) - Import PNG and export as .icns

## Icon Design Guidelines

For best results, follow Apple's icon design guidelines:

### Size and Format
- Base size: 1024x1024 pixels
- Format: PNG with transparency (before conversion to .icns)
- Color space: sRGB

### Visual Design
- Use a simple, recognizable design
- Avoid text (except for app name/initials if needed)
- Use a consistent color palette
- Consider both light and dark mode appearances
- Test at small sizes (16x16, 32x32) to ensure clarity

### macOS Style
- Rounded corners (typically 180px radius for 1024x1024)
- Subtle shadows and gradients
- 3D depth (optional, but common in macOS icons)
- Consistent with macOS Big Sur+ design language

## Icon Resources

- **Apple Human Interface Guidelines**: https://developer.apple.com/design/human-interface-guidelines/app-icons
- **SF Symbols**: https://developer.apple.com/sf-symbols/ (for inspiration)
- **Icon templates**: Search for "macOS icon template" for Sketch/Figma templates

## Verifying the Icon

After rebuilding, verify the icon appears correctly:

```bash
# Open the app
open macos_app/build/XeFM.app

# Check in Finder
open macos_app/build/

# Check in Dock (after launching)
# The icon should appear in the Dock when the app is running
```

## Troubleshooting

### Icon doesn't appear after rebuild

1. Clear icon cache using the make target:
   ```bash
   make macos-refresh-icon
   ```

2. Or manually clear icon cache:
   ```bash
   sudo rm -rf /Library/Caches/com.apple.iconservices.store
   killall Dock
   killall Finder
   ```

3. Verify icon is in bundle:
   ```bash
   ls -lh macos_app/build/XeFM.app/Contents/Resources/XeFM.icns
   ```

2. Check Info.plist references the icon:
   ```bash
   grep -A 1 "CFBundleIconFile" macos_app/build/XeFM.app/Contents/Info.plist
   ```

### Icon looks blurry

- Ensure your source image is at least 1024x1024 pixels
- Use PNG format with transparency
- Avoid JPEG (lossy compression)
- Check that all icon sizes were generated correctly

### Icon has wrong colors

- Verify color space is sRGB
- Check that transparency is preserved
- Test in both light and dark mode

## Current Placeholder Details

The placeholder icon was generated using:
- Python PIL (Pillow) library
- Blue gradient background (RGB: 30,60,100 to 30,60,255)
- Helvetica font for text
- 1024x1024 base resolution
- All standard macOS icon sizes (16x16 through 512x512@2x)

Location: `macos_app/resources/XeFM.icns`
