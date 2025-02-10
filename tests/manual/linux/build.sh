#!/bin/bash

# Set script to exit on error
set -e

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Build function
build() {
    echo -e "${GREEN}Building Process Pilot executable...${NC}"
    
    # Set the output directory for the executable
    OUTPUT_DIR="$SCRIPT_DIR/dist"

    # Create output directory if it doesn't exist
    mkdir -p "$OUTPUT_DIR"

    # Run PyInstaller to build the executable
    pyinstaller --onefile --distpath "$OUTPUT_DIR" "$SCRIPT_DIR/../pyinstaller.py"

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Build successful. Executable created in $OUTPUT_DIR${NC}"
    else
        echo -e "${RED}Build failed.${NC}"
        exit 1
    fi
}

# Error handler
handle_error() {
    echo -e "${RED}Error: Build failed!${NC}"
    exit 1
}

# Set error handler
trap 'handle_error' ERR

# Execute build
build