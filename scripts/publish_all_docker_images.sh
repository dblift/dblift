#!/bin/bash
# Manual Docker build and publish script for BOTH images
# Use this when GitHub Actions minutes are exhausted

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
REGISTRY="ghcr.io"
REPO_OWNER="cmodiano"
VERSION="0.7.0-beta"

echo -e "${GREEN}=== DBLift Manual Docker Build & Publish (Both Images) ===${NC}"
echo

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running${NC}"
    exit 1
fi

# Build both images
IMAGES=("dblift" "dblift-validation")
DOCKERFILES=("Dockerfile" "Dockerfile.validation")

for i in "${!IMAGES[@]}"; do
    IMAGE_NAME="${IMAGES[$i]}"
    DOCKERFILE="${DOCKERFILES[$i]}"
    
    echo -e "${BLUE}📦 Building ${IMAGE_NAME}...${NC}"
    echo "   Using: ${DOCKERFILE}"
    echo
    
    docker build --platform linux/amd64 -f "${DOCKERFILE}" -t "${IMAGE_NAME}:${VERSION}" .
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Build failed for ${IMAGE_NAME}${NC}"
        exit 1
    fi
    
    echo
    echo -e "${GREEN}✅ ${IMAGE_NAME} built successfully${NC}"
    
    # Get size
    SIZE=$(docker images "${IMAGE_NAME}:${VERSION}" --format "{{.Size}}")
    echo -e "${GREEN}📊 Size: ${SIZE}${NC}"
    echo
    
    # Test the image
    echo -e "${BLUE}🧪 Testing ${IMAGE_NAME}...${NC}"
    
    if [ "${IMAGE_NAME}" == "dblift" ]; then
        docker run --rm "${IMAGE_NAME}:${VERSION}" --version
    else
        docker run --rm "${IMAGE_NAME}:${VERSION}" validate-sql --help > /dev/null
    fi
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Test failed for ${IMAGE_NAME}${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ ${IMAGE_NAME} tests passed${NC}"
    echo
    echo "---"
    echo
done

# Tag all images for registry
echo -e "${BLUE}🏷️  Tagging images for registry...${NC}"
echo

for IMAGE_NAME in "${IMAGES[@]}"; do
    # Extract version components
    MAJOR_MINOR=$(echo "${VERSION}" | sed -E 's/([0-9]+\.[0-9]+).*/\1/')
    MAJOR=$(echo "${VERSION}" | sed -E 's/([0-9]+).*/\1/')
    
    # Tag with version variations
    docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${VERSION}"
    docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:v${VERSION}"
    docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR_MINOR}"
    docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR}"
    docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest"
    
    echo "${IMAGE_NAME} tags created:"
    echo "  - ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest"
    echo "  - ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:v${VERSION}"
    echo "  - ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR_MINOR}"
    echo
done

echo -e "${GREEN}✅ All images built and tagged${NC}"
echo

# Login prompt
echo -e "${BLUE}🔐 Login to GitHub Container Registry...${NC}"
echo
echo "You need a GitHub Personal Access Token (PAT) with these scopes:"
echo "  ✅ write:packages"
echo "  ✅ read:packages"
echo "  ✅ repo (if repository is private)"
echo
echo "Create one at: https://github.com/settings/tokens/new"
echo

read -p "Do you want to login and push now? (y/n): " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Enter your GitHub Personal Access Token:"
    docker login ${REGISTRY} -u ${REPO_OWNER}
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Login failed${NC}"
        echo
        echo "Common issues:"
        echo "  1. Token doesn't have 'write:packages' scope"
        echo "  2. Token expired"
        echo "  3. Wrong username"
        echo
        echo "To fix: Create new token at https://github.com/settings/tokens/new"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Login successful${NC}"
    echo
    
    # Push all images
    echo -e "${BLUE}🚀 Pushing images to registry...${NC}"
    echo
    
    for IMAGE_NAME in "${IMAGES[@]}"; do
        echo "Pushing ${IMAGE_NAME}..."
        docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${VERSION}"
        docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:v${VERSION}"
        docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR_MINOR}"
        docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR}"
        docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest"
        echo -e "${GREEN}✅ ${IMAGE_NAME} pushed${NC}"
        echo
    done
    
    echo
    echo -e "${GREEN}=== Success! All Images Published ===${NC}"
    echo
    echo "Full image (691MB):"
    echo "  🐳 ${REGISTRY}/${REPO_OWNER}/dblift:latest"
    echo "  docker run --rm -v \$(pwd):/workspace ${REGISTRY}/${REPO_OWNER}/dblift:latest migrate"
    echo
    echo "Validation image (~250MB, 60% smaller):"
    echo "  🐳 ${REGISTRY}/${REPO_OWNER}/dblift-validation:latest"
    echo "  docker run --rm -v \$(pwd):/workspace ${REGISTRY}/${REPO_OWNER}/dblift-validation:latest"
    echo
    echo "Next steps:"
    echo "  1. Make packages public: https://github.com/users/${REPO_OWNER}/packages"
    echo "  2. Update dblift-demo repository"
    echo
else
    echo
    echo -e "${YELLOW}⏸️  Images built but NOT published${NC}"
    echo
    echo "To publish later, run:"
    echo "  ./dblift_package/scripts/publish_docker_manual.sh"
    echo
fi

# Show local images
echo "Local images:"
docker images | grep -E "dblift|SIZE"
echo

