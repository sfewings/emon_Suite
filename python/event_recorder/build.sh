#!/bin/bash
# Build script for Event Recorder Docker image
# Supports multi-platform builds (amd64, arm64, arm/v7)

set -e

# Configuration
IMAGE_NAME="sfewings32/emon_event_recorder"
VERSION="0.1.0"
PLATFORMS="linux/amd64,linux/arm64,linux/arm/v7"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}Event Recorder - Docker Build (.sh) ${NC}"
echo -e "${BLUE}================================${NC}"
echo ""

# Check if docker buildx is available
if ! docker buildx version > /dev/null 2>&1; then
    echo -e "${RED}Error: docker buildx not found${NC}"
    echo "Install buildx: https://docs.docker.com/buildx/working-with-buildx/"
    exit 1
fi

# Parse arguments
BUILD_TYPE="${1:-local}"  # local, push, or test

case "$BUILD_TYPE" in
    local)
        echo -e "${GREEN}Building for local platform only...${NC}"
        cd ..
        docker build \
            --tag "${IMAGE_NAME}:latest" \
            --tag "${IMAGE_NAME}:${VERSION}" \
            --file event_recorder/Dockerfile \
            .
        echo -e "${GREEN}Build complete!${NC}"
        echo "Image: ${IMAGE_NAME}:latest"
        ;;

    push)
        echo -e "${GREEN}Building and pushing multi-platform images...${NC}"
        echo "Platforms: ${PLATFORMS}"
        echo "Image: ${IMAGE_NAME}:${VERSION}"
        echo ""

        # Create/use buildx builder
        if ! docker buildx inspect emon_builder > /dev/null 2>&1; then
            echo "Creating buildx builder..."
            docker buildx create --name emon_builder --use
        else
            echo "Using existing builder: emon_builder"
            docker buildx use emon_builder
        fi

        # Build and push
        cd ..
        docker buildx build \
            --platform "${PLATFORMS}" \
            --tag "${IMAGE_NAME}:latest" \
            --tag "${IMAGE_NAME}:${VERSION}" \
            --file event_recorder/Dockerfile \
            --push \
            .

        echo -e "${GREEN}Build and push complete!${NC}"
        echo "Images pushed:"
        echo "  - ${IMAGE_NAME}:latest"
        echo "  - ${IMAGE_NAME}:${VERSION}"
        ;;

    test)
        echo -e "${GREEN}Building test image (single platform)...${NC}"
        cd ..
        docker build \
            --tag "${IMAGE_NAME}:test" \
            --file event_recorder/Dockerfile \
            .

        echo -e "${GREEN}Running test container...${NC}"
        docker run --rm -it \
            -e MQTT_BROKER=mqtt \
            -v "$(pwd)/event_recorder/config_examples:/config:ro" \
            -v "$(pwd)/event_recorder/test_data:/data" \
            -p 5001:5000 \
            "${IMAGE_NAME}:test"
        ;;

    *)
        echo -e "${RED}Unknown build type: $BUILD_TYPE${NC}"
        echo ""
        echo "Usage: ./build.sh [local|push|test]"
        echo ""
        echo "  local  - Build for current platform only (default)"
        echo "  push   - Build multi-platform and push to Docker Hub"
        echo "  test   - Build and run test container"
        exit 1
        ;;
esac

echo ""
echo -e "${BLUE}================================${NC}"
echo -e "${GREEN}Done!${NC}"
echo -e "${BLUE}================================${NC}"
