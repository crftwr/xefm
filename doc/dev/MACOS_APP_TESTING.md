# XeFM macOS App - Testing Guide

This guide provides comprehensive testing procedures for the XeFM macOS application bundle.

## Prerequisites

- XeFM.app built successfully (run `cd macos_app && ./build.sh`)
- macOS 10.13 or later
- Application bundle located at: `macos_app/build/XeFM.app`

## Quick Test Checklist

Essential tests to verify basic functionality:

- [ ] Application launches successfully
- [ ] UI renders correctly with no visual glitches
- [ ] Keyboard navigation works (arrow keys, Tab, Enter, Backspace)
- [ ] Mouse input works (click, scroll, double-click)
- [ ] File operations complete successfully (view, copy, move, delete)
- [ ] Application quits cleanly (Q key, Cmd+Q, Dock menu)
- [ ] Multiple windows work independently
- [ ] Development mode still works (`python3 -m xefm --backend gui`)

## Detailed Test Procedures

### Test 1: First Launch

**Steps:**
1. Open Terminal and navigate to project directory
2. Run: `open macos_app/build/XeFM.app`

**Expected Results:**
- XeFM icon appears in the Dock
- XeFM window opens showing file manager interface
- Window title shows "XeFM - Terminal File Manager"
- File listing displays correctly
- No error dialogs appear

**Verification:**
- Window renders properly with no visual glitches
- File listings show current directory contents
- Status bar displays at bottom of window
- Cursor is visible and positioned correctly

---

### Test 2: Keyboard Input

**Steps:**
1. With XeFM window focused, test these keys:
   - Arrow keys (↑↓) - Navigate file list
   - Tab - Switch between panes
   - Enter - Open directory or file
   - Backspace - Go to parent directory
   - Q - Quit application

**Expected Results:**
- Arrow keys move cursor up/down in file list
- Tab switches focus between left and right panes
- Enter opens directories/files
- Backspace navigates to parent directory
- Q quits the application

**Verification:**
- Keyboard input is responsive with no lag
- Cursor moves smoothly
- Application responds to all key commands

---

### Test 3: Mouse Input

**Steps:**
1. Launch XeFM.app
2. Test these mouse actions:
   - Click on different files in the list
   - Click on the other pane
   - Scroll with mouse wheel or trackpad
   - Double-click on a directory

**Expected Results:**
- Single click selects file/directory
- Clicking switches pane focus
- Scrolling moves through file list
- Double-click opens directory

**Verification:**
- Mouse clicks are accurate
- Scrolling is smooth with no visual artifacts
- Cursor position updates correctly

---

### Test 4: Multi-Window Support

**Steps:**
1. Launch XeFM.app
2. Right-click on XeFM icon in Dock
3. Select "New Window" from menu
4. Navigate to different directories in each window
5. Close one window (Cmd+W or click red close button)
6. Verify other window continues working
7. Close the last window

**Expected Results:**
- Right-click shows Dock menu with "New Window" option
- Second XeFM window opens successfully
- Both windows operate independently
- Each window can navigate to different directories
- Closing one window doesn't affect the other
- Closing last window terminates the application

**Verification:**
- Each window maintains its own state
- File operations in one window don't affect the other
- Windows can be moved and resized independently
- Application terminates cleanly when last window closes

---

### Test 5: Dock Integration

**Steps:**
1. Launch XeFM.app
2. Right-click the XeFM icon in Dock
3. Observe the Dock menu

**Expected Results:**
- Dock menu appears with proper formatting
- "New Window" option is present and functional
- Standard macOS menu items appear (Quit, etc.)
- If multiple windows open, window list appears

**Verification:**
- "New Window" option creates new window when clicked
- Window list (if present) shows all open windows
- Clicking window name brings that window to front

---

### Test 6: File Operations

**Steps:**
1. Launch XeFM.app and navigate to a test directory
2. Test these operations:
   - View a text file (press F3 or V)
   - Copy a file (press F5)
   - Move a file (press F6)
   - Delete a file (press F8)
   - Create a directory (press F7)

**Expected Results:**
- File viewer opens for text files
- Copy dialog appears with progress indicator
- Move dialog appears with progress indicator
- Delete confirmation dialog appears
- Create directory dialog appears

**Verification:**
- All file operations complete successfully
- Progress indicators work correctly
- Error messages appear for invalid operations
- File system changes are reflected immediately

---

### Test 7: Application Quit

**Steps:**
1. Launch XeFM.app
2. Test each quit method:
   - Press Q key in XeFM window
   - Press Cmd+Q
   - Right-click Dock icon and select "Quit"
   - Close all windows

**Expected Results:**
- Q key quits immediately
- Cmd+Q quits immediately
- Dock "Quit" option quits immediately
- Closing last window quits application
- No error dialogs on quit
- No crash or hang

**Verification:**
- Application terminates cleanly
- No zombie processes left running (check with `ps aux | grep XeFM`)
- No error messages in Console.app
- Application can be relaunched successfully

---

### Test 8: Error Handling

**Warning:** This test temporarily breaks the app bundle. Only perform if you want to verify error handling.

**Steps:**
1. Quit XeFM.app if running
2. Temporarily rename Python.framework:
   ```bash
   cd macos_app/build/XeFM.app/Contents/Frameworks
   mv Python.framework Python.framework.backup
   ```
3. Try to launch XeFM.app: `open ../../XeFM.app`
4. Observe error dialog
5. Restore Python.framework:
   ```bash
   mv Python.framework.backup Python.framework
   ```

**Expected Results:**
- Error dialog appears with clear message
- Message mentions Python initialization failure
- Message suggests possible causes and reinstalling XeFM
- Application terminates gracefully after clicking OK

**Verification:**
- Error dialog is properly formatted
- Error message is clear and helpful
- No crash or hang
- Console.app shows detailed error logs

---

### Test 9: Development Mode Compatibility

**Steps:**
1. Open Terminal and navigate to project directory
2. Run XeFM in terminal mode: `python3 -m xefm`
3. Quit (press Q)
4. Run XeFM in desktop mode: `python3 -m xefm --backend gui`
5. Quit (press Q)

**Expected Results:**
- Terminal mode launches with curses interface
- Desktop mode launches with CoreGraphics window
- Both modes work correctly
- No errors or warnings
- Source changes take effect immediately (no rebuild needed)

**Verification:**
- Both modes launch successfully
- Terminal mode uses curses backend
- Desktop mode uses CoreGraphics backend
- No conflicts with app bundle
- Development workflow unchanged

---

### Test 10: Performance and Stability

**Steps:**
1. Launch XeFM.app
2. Navigate through large directories (1000+ files)
3. Open and close multiple windows
4. Perform file operations on large files
5. Leave app running for extended period
6. Switch between XeFM and other applications

**Expected Results:**
- Large directories load quickly
- Scrolling is smooth even with many files
- Multiple windows don't slow down the app
- Large file operations complete successfully
- No memory leaks or performance degradation
- App switching works smoothly

**Verification:**
- Responsive UI at all times
- No memory leaks (check Activity Monitor)
- No CPU spikes during idle
- Stable performance over time
- No crashes or hangs

---

## Troubleshooting

### App Won't Launch

**Possible Causes:**
- Missing or corrupted Python.framework
- Missing XeFM source files in Resources
- Build script errors

**Solutions:**
1. Check Console.app for error messages
2. Verify Python.framework exists: `ls macos_app/build/XeFM.app/Contents/Frameworks/`
3. Verify XeFM source files exist: `ls macos_app/build/XeFM.app/Contents/Resources/xefm/`
4. Try rebuilding: `cd macos_app && ./build.sh`

### Window Doesn't Appear

**Possible Causes:**
- Window hidden behind other windows
- Python errors during initialization
- CoreGraphics backend issues

**Solutions:**
1. Check if window is hidden (use Mission Control or Cmd+Tab)
2. Check Console.app for Python errors
3. Verify CoreGraphics backend is working
4. Try development mode: `python3 -m xefm --backend gui`

### Keyboard/Mouse Not Working

**Possible Causes:**
- Window doesn't have focus
- Accessibility permissions not granted
- Input event handling issues

**Solutions:**
1. Verify window has focus (click on it)
2. Check System Preferences > Security & Privacy > Accessibility
3. Grant accessibility permissions if prompted
4. Try restarting the application

### File Operations Fail

**Possible Causes:**
- Insufficient file permissions
- Insufficient disk space
- File system errors

**Solutions:**
1. Check file permissions: `ls -la`
2. Verify sufficient disk space: `df -h`
3. Check Console.app for error messages
4. Try operations in development mode to isolate issue

---

## Reporting Issues

If you encounter issues during testing:

### 1. Check Console.app for Error Logs

```bash
# Open Console.app and filter for "XeFM" or "Python"
# Copy relevant error messages
```

### 2. Gather System Information

```bash
# macOS version
sw_vers

# Python version
python3 --version

# XeFM version (check Info.plist)
plutil -p macos_app/build/XeFM.app/Contents/Info.plist | grep CFBundleVersion
```

### 3. Document Steps to Reproduce

- What were you doing when the issue occurred?
- Can you reproduce it consistently?
- Does it happen in development mode too?

### 4. Create Issue Report

Include:
- Error messages from Console.app
- System information
- Steps to reproduce
- Screenshots if relevant

---

## Success Criteria

All tests should pass with these results:

- ✅ Application launches successfully
- ✅ UI renders correctly
- ✅ Keyboard and mouse input work
- ✅ Multiple windows work independently
- ✅ Dock integration functions properly
- ✅ File operations complete successfully
- ✅ Application quits cleanly
- ✅ Error handling works as expected
- ✅ Development mode still works
- ✅ Performance is acceptable

If all tests pass, the XeFM macOS application bundle is ready for distribution!

---

## Distribution Preparation

After successful testing, prepare for distribution:

### 1. Create Application Icon (Optional)

```bash
# Design icon in .icns format
# Place at macos_app/resources/XeFM.icns
# Rebuild application
cd macos_app && ./build.sh
```

### 2. Code Signing (Optional, for distribution)

```bash
export CODESIGN_IDENTITY="Developer ID Application: Your Name"
cd macos_app && ./build.sh
```

### 3. Create DMG Installer (Optional)

```bash
make macos-dmg
```

### 4. Install to Applications (Optional)

```bash
make macos-app-install
```

### 5. Distribution Options

- Share XeFM.app bundle directly
- Share DMG installer
- Submit to Mac App Store (requires additional steps)

---

## Related Documentation

- **Build System**: `doc/dev/MACOS_APP_BUILD_SYSTEM.md` - Comprehensive build system documentation
- **Build Script**: `macos_app/build.sh` - Main build script with inline documentation
- **Makefile**: `Makefile` - Build automation targets

