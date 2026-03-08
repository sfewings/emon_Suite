#!/bin/bash
# emon Docker Build Script
# Builds one or many Docker images with flexible platform and mode options
#
# Usage: ./build.sh [OPTIONS]
#   -m, --mode MODE         local | push | test  (default: local)
#   -c, --containers LIST   comma-separated names or 'all'  (default: all)
#   -p, --platforms LIST    local | amd64 | arm64 | arm32 | all  (default: local or all)
#   -h, --help

set -e

# ============================================================
# Container Definitions
# Edit image names and versions here
# ============================================================
ALL_CONTAINERS=(
    event_recorder
    settings_web
    serial_to_mqtt
    mqtt_to_influx
    mqtt_to_log
    gpsd_to_mqtt
    query_bom
)

DOCKERFILE_event_recorder="event_recorder/Dockerfile"
IMAGE_event_recorder="sfewings32/emon_event_recorder"
VERSION_event_recorder="0.1.0"

DOCKERFILE_settings_web="emon_settings_web/Dockerfile"
IMAGE_settings_web="sfewings32/emon_settings_web"
VERSION_settings_web="0.1.0"

DOCKERFILE_serial_to_mqtt="serialToMQTT.Dockerfile"
IMAGE_serial_to_mqtt="sfewings32/emon_serial_to_mqtt"
VERSION_serial_to_mqtt="latest"

DOCKERFILE_mqtt_to_influx="MQTTToInflux.Dockerfile"
IMAGE_mqtt_to_influx="sfewings32/emon_mqtt_to_influx"
VERSION_mqtt_to_influx="latest"

DOCKERFILE_mqtt_to_log="MQTTToLog.Dockerfile"
IMAGE_mqtt_to_log="sfewings32/emon_mqtt_to_log"
VERSION_mqtt_to_log="latest"

DOCKERFILE_gpsd_to_mqtt="GPSDToMQTT.Dockerfile"
IMAGE_gpsd_to_mqtt="sfewings32/emon_gpsd_to_mqtt"
VERSION_gpsd_to_mqtt="latest"

DOCKERFILE_query_bom="queryBOM.Dockerfile"
IMAGE_query_bom="sfewings32/emon_query_bom"
VERSION_query_bom="latest"

BUILDER_NAME="emon_builder"

# ============================================================
# Colors
# ============================================================
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Build context root = directory containing this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================
# Defaults
# ============================================================
MODE="local"
CONTAINERS_ARG="all"
PLATFORMS_ARG=""

# ============================================================
# Usage
# ============================================================
usage() {
    echo ""
    echo -e "${BLUE}emon Docker Build Script${NC}"
    echo ""
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -m, --mode MODE         Build mode (default: local)"
    echo "                            local  - build for current/specified platform, load to local Docker"
    echo "                            push   - build multi-platform and push to Docker Hub"
    echo "                            test   - build locally then run the container"
    echo "  -c, --containers LIST   Comma-separated container names or 'all' (default: all)"
    echo "  -p, --platforms LIST    Comma-separated platforms (default: 'local' for local/test, 'all' for push)"
    echo "                            local  - native host platform"
    echo "                            amd64  - linux/amd64"
    echo "                            arm64  - linux/arm64"
    echo "                            arm32  - linux/arm/v7"
    echo "                            all    - amd64 + arm64 + arm32  (push only)"
    echo "  -h, --help              Show this help"
    echo ""
    echo "Available containers:"
    for name in "${ALL_CONTAINERS[@]}"; do
        local img_var="IMAGE_${name}"
        printf "  %-22s  %s\n" "$name" "${!img_var}"
    done
    echo ""
    echo "Examples:"
    echo "  $(basename "$0")                                      # Build all containers locally"
    echo "  $(basename "$0") -m push                             # Build all and push multi-platform"
    echo "  $(basename "$0") -m push -c event_recorder           # Push event_recorder only"
    echo "  $(basename "$0") -m local -c settings_web,gpsd_to_mqtt"
    echo "  $(basename "$0") -m push -p arm64,arm32 -c serial_to_mqtt"
    echo "  $(basename "$0") -m test -c event_recorder"
    echo ""
}

# ============================================================
# Resolve comma-separated platform names -> docker platform string
# ============================================================
resolve_platforms() {
    local input="$1"
    local result=""

    IFS=',' read -ra parts <<< "$input"
    for part in "${parts[@]}"; do
        part="${part// /}"
        case "$part" in
            local) result="${result:+$result,}local"          ;;
            amd64) result="${result:+$result,}linux/amd64"    ;;
            arm64) result="${result:+$result,}linux/arm64"    ;;
            arm32) result="${result:+$result,}linux/arm/v7"   ;;
            all)   echo "linux/amd64,linux/arm64,linux/arm/v7"; return 0 ;;
            *)
                echo -e "${RED}Unknown platform: '$part'${NC}" >&2
                echo "Valid values: local, amd64, arm64, arm32, all" >&2
                return 1
                ;;
        esac
    done
    echo "$result"
}

# ============================================================
# Run test container (container-specific logic)
# ============================================================
run_test_container() {
    local name="$1"
    local image="$2"

    case "$name" in
        event_recorder)
            docker run --rm -it \
                -e MQTT_BROKER=mqtt \
                -v "${SCRIPT_DIR}/event_recorder/config_examples:/config:ro" \
                -v "${SCRIPT_DIR}/event_recorder/test_data:/data" \
                -p 5001:5000 \
                "${image}:test"
            ;;
        settings_web)
            docker run --rm -it \
                -p 5002:5000 \
                "${image}:test"
            ;;
        *)
            echo -e "${YELLOW}No specific test run configured for '$name'. Starting with default entrypoint...${NC}"
            docker run --rm "${image}:test" || true
            ;;
    esac
}

# ============================================================
# Build a single container
# ============================================================
build_container() {
    local name="$1"
    local dockerfile_var="DOCKERFILE_${name}"
    local image_var="IMAGE_${name}"
    local version_var="VERSION_${name}"

    local dockerfile="${!dockerfile_var}"
    local image="${!image_var}"
    local version="${!version_var}"

    if [ -z "$dockerfile" ]; then
        echo -e "${RED}Unknown container: '$name'${NC}"
        echo "Available: ${ALL_CONTAINERS[*]}"
        return 1
    fi

    # Build --tag arguments
    local tags="--tag ${image}:latest"
    if [ "$version" != "latest" ]; then
        tags="$tags --tag ${image}:${version}"
    fi

    echo -e "${BLUE}--- ${name} ---${NC}"
    echo "  Dockerfile: ${dockerfile}"
    echo -n "  Image:      ${image}:latest"
    [ "$version" != "latest" ] && echo "  +  ${image}:${version}" || echo ""
    echo ""

    case "$MODE" in
        local)
            if [ "$PLATFORMS" = "local" ]; then
                docker build \
                    --file "${SCRIPT_DIR}/${dockerfile}" \
                    $tags \
                    "${SCRIPT_DIR}"
            else
                # buildx --load requires a single platform
                local count
                count=$(echo "$PLATFORMS" | tr ',' '\n' | wc -l)
                if [ "$count" -gt 1 ]; then
                    echo -e "${RED}Error: 'local' mode can only load one platform at a time.${NC}"
                    echo "  Specified: $PLATFORMS"
                    echo "  Use 'push' mode for multi-platform builds."
                    return 1
                fi
                docker buildx build \
                    --platform "$PLATFORMS" \
                    --file "${SCRIPT_DIR}/${dockerfile}" \
                    $tags \
                    --load \
                    "${SCRIPT_DIR}"
            fi
            ;;

        push)
            docker buildx build \
                --platform "$PLATFORMS" \
                --file "${SCRIPT_DIR}/${dockerfile}" \
                $tags \
                --push \
                "${SCRIPT_DIR}"
            ;;

        test)
            if [ "$PLATFORMS" = "local" ]; then
                docker build \
                    --file "${SCRIPT_DIR}/${dockerfile}" \
                    --tag "${image}:test" \
                    "${SCRIPT_DIR}"
            else
                docker buildx build \
                    --platform "$PLATFORMS" \
                    --file "${SCRIPT_DIR}/${dockerfile}" \
                    --tag "${image}:test" \
                    --load \
                    "${SCRIPT_DIR}"
            fi
            echo ""
            echo -e "${GREEN}Running: ${name}${NC}"
            run_test_container "$name" "$image"
            ;;
    esac
}

# ============================================================
# Parse arguments
# ============================================================
while [[ $# -gt 0 ]]; do
    case "$1" in
        -m|--mode)        MODE="$2";           shift 2 ;;
        -c|--containers)  CONTAINERS_ARG="$2"; shift 2 ;;
        -p|--platforms)   PLATFORMS_ARG="$2";  shift 2 ;;
        -h|--help)        usage; exit 0 ;;
        *)
            echo -e "${RED}Unknown argument: $1${NC}"
            usage
            exit 1
            ;;
    esac
done

# Validate mode
case "$MODE" in
    local|push|test) ;;
    *)
        echo -e "${RED}Invalid mode: '$MODE'. Valid: local, push, test${NC}"
        exit 1
        ;;
esac

# Default platforms based on mode
if [ -z "$PLATFORMS_ARG" ]; then
    [ "$MODE" = "push" ] && PLATFORMS_ARG="all" || PLATFORMS_ARG="local"
fi

# Resolve platform string
PLATFORMS=$(resolve_platforms "$PLATFORMS_ARG") || exit 1

# Validate: local/test mode with 'all' platforms is not supported
if [ "$MODE" != "push" ] && [ "$PLATFORMS" = "linux/amd64,linux/arm64,linux/arm/v7" ]; then
    echo -e "${RED}Error: platform 'all' is only valid with push mode.${NC}"
    echo "Use -m push, or specify a single platform for local/test."
    exit 1
fi

# Resolve container list
if [ "$CONTAINERS_ARG" = "all" ]; then
    CONTAINER_LIST=("${ALL_CONTAINERS[@]}")
else
    CONTAINER_LIST=()
    IFS=',' read -ra PARTS <<< "$CONTAINERS_ARG"
    for part in "${PARTS[@]}"; do
        part="${part// /}"
        local_var="DOCKERFILE_${part}"
        if [ -z "${!local_var}" ]; then
            echo -e "${RED}Unknown container: '$part'${NC}"
            echo "Available: ${ALL_CONTAINERS[*]}"
            exit 1
        fi
        CONTAINER_LIST+=("$part")
    done
fi

# Setup buildx builder if needed
NEEDS_BUILDX=false
[ "$MODE" = "push" ] && NEEDS_BUILDX=true
[ "$PLATFORMS" != "local" ] && NEEDS_BUILDX=true

if $NEEDS_BUILDX; then
    if ! docker buildx version > /dev/null 2>&1; then
        echo -e "${RED}Error: docker buildx is not available.${NC}"
        exit 1
    fi
    if ! docker buildx inspect "$BUILDER_NAME" > /dev/null 2>&1; then
        echo "Creating buildx builder: $BUILDER_NAME"
        docker buildx create --name "$BUILDER_NAME" --use
    else
        docker buildx use "$BUILDER_NAME" > /dev/null 2>&1
    fi
fi

# ============================================================
# Banner
# ============================================================
echo ""
echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}  emon Docker Build${NC}"
echo -e "${BLUE}================================${NC}"
echo -e "  Mode:       ${GREEN}${MODE}${NC}"
echo -e "  Containers: ${GREEN}${CONTAINERS_ARG}${NC}  →  ${CONTAINER_LIST[*]}"
echo -e "  Platforms:  ${GREEN}${PLATFORMS_ARG}${NC}  →  ${PLATFORMS}"
echo -e "${BLUE}================================${NC}"
echo ""

# ============================================================
# Build loop
# ============================================================
PASS=()
FAIL=()

for container in "${CONTAINER_LIST[@]}"; do
    if build_container "$container"; then
        PASS+=("$container")
        echo -e "${GREEN}✓ ${container}${NC}"
    else
        FAIL+=("$container")
        echo -e "${RED}✗ ${container} FAILED${NC}"
    fi
    echo ""
done

# ============================================================
# Summary
# ============================================================
echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}  Build Summary${NC}"
echo -e "${BLUE}================================${NC}"

[ ${#PASS[@]} -gt 0 ] && echo -e "  ${GREEN}Passed (${#PASS[@]}):${NC} ${PASS[*]}"
[ ${#FAIL[@]} -gt 0 ] && echo -e "  ${RED}Failed (${#FAIL[@]}):${NC} ${FAIL[*]}"

echo -e "${BLUE}================================${NC}"
echo ""

if [ ${#FAIL[@]} -gt 0 ]; then
    exit 1
fi

echo -e "${GREEN}All done!${NC}"
