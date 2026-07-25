#!/bin/bash
# Test runner script with different isolation modes

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "XeFM Test Runner"
echo "==============="
echo ""

# Parse command line arguments
MODE="${1:-isolated}"
PATTERN="${2:-test/}"

case "$MODE" in
    isolated)
        echo -e "${GREEN}Running tests in isolated processes (one test per process)${NC}"
        echo "Each test gets 10 second timeout"
        echo ""
        python -m pytest "$PATTERN" --forked --timeout=10 -v
        ;;
    
    parallel)
        echo -e "${GREEN}Running tests in parallel (multiple processes)${NC}"
        echo "Each test gets 10 second timeout"
        echo ""
        python -m pytest "$PATTERN" -n auto --timeout=10 -v
        ;;
    
    sequential)
        echo -e "${GREEN}Running tests sequentially (single process)${NC}"
        echo "Each test gets 10 second timeout"
        echo ""
        python -m pytest "$PATTERN" --timeout=10 -v
        ;;
    
    quick)
        echo -e "${GREEN}Quick test run (fail fast, no timeout)${NC}"
        echo ""
        python -m pytest "$PATTERN" -x -v
        ;;
    
    *)
        echo -e "${RED}Unknown mode: $MODE${NC}"
        echo ""
        echo "Usage: $0 [mode] [pattern]"
        echo ""
        echo "Modes:"
        echo "  isolated   - Run each test in separate process (safest, default)"
        echo "  parallel   - Run tests in parallel across CPU cores (fastest)"
        echo "  sequential - Run tests one by one in same process (traditional)"
        echo "  quick      - Run until first failure, no timeout (debugging)"
        echo ""
        echo "Examples:"
        echo "  $0 isolated test/"
        echo "  $0 parallel test/test_archive*.py"
        echo "  $0 quick test/test_archive_copy_integration.py"
        exit 1
        ;;
esac
