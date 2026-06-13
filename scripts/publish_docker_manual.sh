#!/bin/bash
# Manual Docker build and publish script
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
IMAGE_NAME="dblift"
VERSION="0.7.0-beta"

echo -e "${GREEN}=== DBLift Manual Docker Build & Publish ===${NC}"
echo

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running${NC}"
    exit 1
fi

# Step 1: Build the image
echo -e "${BLUE}📦 Step 1/5: Building Docker image...${NC}"
echo

docker build --platform linux/amd64 -t "${IMAGE_NAME}:${VERSION}" .

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Build failed${NC}"
    exit 1
fi

echo
echo -e "${GREEN}✅ Build successful${NC}"
echo

# Step 2: Test the image
echo -e "${BLUE}🧪 Step 2/5: Testing image...${NC}"
echo

echo "Testing --version:"
docker run --rm "${IMAGE_NAME}:${VERSION}" --version

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Version test failed${NC}"
    exit 1
fi

echo
echo -e "${GREEN}✅ Tests passed${NC}"
echo

# Step 3: Tag the image for registry
echo -e "${BLUE}🏷️  Step 3/5: Tagging image for registry...${NC}"
echo

# Tag with version
docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${VERSION}"
docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:v${VERSION}"
docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest"

# Extract major.minor version (0.7.0-beta -> 0.7)
MAJOR_MINOR=$(echo "${VERSION}" | sed -E 's/([0-9]+\.[0-9]+).*/\1/')
docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR_MINOR}"

# Extract major version (0.7.0-beta -> 0)
MAJOR=$(echo "${VERSION}" | sed -E 's/([0-9]+).*/\1/')
docker tag "${IMAGE_NAME}:${VERSION}" "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR}"

echo "Created tags:"
echo "  - ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${VERSION}"
echo "  - ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:v${VERSION}"
echo "  - ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR_MINOR}"
echo "  - ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR}"
echo "  - ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest"

echo
echo -e "${GREEN}✅ Tagging complete${NC}"
echo

# Step 4: Login to GitHub Container Registry
echo -e "${BLUE}🔐 Step 4/5: Login to GitHub Container Registry...${NC}"
echo
echo "You will need a GitHub Personal Access Token (PAT) with 'write:packages' scope"
echo "Create one at: https://github.com/settings/tokens/new?scopes=write:packages"
echo

read -p "Do you want to login now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Enter your GitHub Personal Access Token:"
    docker login ${REGISTRY} -u ${REPO_OWNER}
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Login failed${NC}"
        echo
        echo "To login manually:"
        echo "  echo YOUR_PAT | docker login ${REGISTRY} -u ${REPO_OWNER} --password-stdin"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Login successful${NC}"
    echo
    
    # Step 5: Push the image
    echo -e "${BLUE}🚀 Step 5/5: Pushing images to registry...${NC}"
    echo
    
    docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${VERSION}"
    docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:v${VERSION}"
    docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR_MINOR}"
    docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR}"
    docker push "${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest"
    
    echo
    echo -e "${GREEN}✅ Push complete!${NC}"
    echo
    echo -e "${GREEN}=== Success! ===${NC}"
    echo
    echo "Images published to:"
    echo "  🐳 ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest"
    echo "  🐳 ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:v${VERSION}"
    echo "  🐳 ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR_MINOR}"
    echo
    echo "Test the published image:"
    echo "  docker pull ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest"
    echo "  docker run --rm ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest --version"
    echo
else
    echo
    echo -e "${YELLOW}⏸️  Build complete but NOT published${NC}"
    echo
    echo "To login and push manually:"
    echo
    echo "1. Create GitHub Personal Access Token:"
    echo "   https://github.com/settings/tokens/new?scopes=write:packages"
    echo
    echo "2. Login to GitHub Container Registry:"
    echo "   echo YOUR_PAT | docker login ${REGISTRY} -u ${REPO_OWNER} --password-stdin"
    echo
    echo "3. Push images:"
    echo "   docker push ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${VERSION}"
    echo "   docker push ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:v${VERSION}"
    echo "   docker push ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR_MINOR}"
    echo "   docker push ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:${MAJOR}"
    echo "   docker push ${REGISTRY}/${REPO_OWNER}/${IMAGE_NAME}:latest"
    echo
fi

# Show local image
echo "Local images:"
docker images | grep "${IMAGE_NAME}"
echo

