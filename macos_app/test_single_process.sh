#!/bin/bash
# Test script for single-process architecture

echo "=== Testing Single-Process Architecture ==="
echo ""

# Launch the app
echo "1. Launching XeFM.app..."
open build/XeFM.app

# Wait for app to start
sleep 2

# Check processes
echo ""
echo "2. Checking running processes:"
ps aux | grep "XeFM.app/Contents/MacOS/XeFM" | grep -v grep

# Count processes
PROCESS_COUNT=$(ps aux | grep "XeFM.app/Contents/MacOS/XeFM" | grep -v grep | wc -l)
echo ""
echo "3. Process count: $PROCESS_COUNT"

if [ "$PROCESS_COUNT" -eq 1 ]; then
    echo "   ✅ PASS: Single process running (expected)"
else
    echo "   ❌ FAIL: Multiple processes running (unexpected)"
fi

echo ""
echo "4. Check Dock for single XeFM icon"
echo "   (Manual verification required)"
echo ""
echo "5. Close the XeFM window to verify app terminates"
echo "   (Manual verification required)"
echo ""
echo "=== Test Complete ==="
