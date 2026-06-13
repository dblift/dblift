#!/bin/bash
# Helper script for managing changelog with git-cliff

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if git-cliff is installed
if ! command -v git-cliff &> /dev/null; then
    echo -e "${RED}Error: git-cliff is not installed${NC}"
    echo "Install it with: brew install git-cliff (macOS) or see .github/CHANGELOG_GUIDE.md"
    exit 1
fi

# Function to display help
show_help() {
    echo -e "${BLUE}DBLift Changelog Management Script${NC}"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  preview       Preview unreleased changes without updating file"
    echo "  update        Update CHANGELOG.md with unreleased changes"
    echo "  full          Regenerate full CHANGELOG.md from git history"
    echo "  release       Prepare changelog for a new release (requires version tag)"
    echo "  check         Check recent commits for conventional format"
    echo "  help          Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 preview                    # Preview what would be added"
    echo "  $0 update                     # Add unreleased changes to CHANGELOG.md"
    echo "  $0 release v0.3.0-beta       # Prepare changelog for v0.3.0-beta release"
}

# Function to preview unreleased changes
preview_unreleased() {
    echo -e "${BLUE}Previewing unreleased changes...${NC}"
    git cliff --unreleased
}

# Function to update changelog with unreleased changes
update_changelog() {
    echo -e "${BLUE}Updating CHANGELOG.md with unreleased changes...${NC}"

    # Backup current changelog
    cp CHANGELOG.md CHANGELOG.md.backup

    # Update changelog
    if git cliff --unreleased --prepend CHANGELOG.md; then
        echo -e "${GREEN}✓ CHANGELOG.md updated successfully${NC}"
        echo -e "${YELLOW}Note: Backup saved as CHANGELOG.md.backup${NC}"
        rm CHANGELOG.md.backup
    else
        echo -e "${RED}✗ Failed to update CHANGELOG.md${NC}"
        mv CHANGELOG.md.backup CHANGELOG.md
        exit 1
    fi
}

# Function to regenerate full changelog
regenerate_full() {
    echo -e "${BLUE}Regenerating full CHANGELOG.md from git history...${NC}"

    # Backup current changelog
    cp CHANGELOG.md CHANGELOG.md.backup

    # Regenerate full changelog
    if git cliff -o CHANGELOG.md; then
        echo -e "${GREEN}✓ CHANGELOG.md regenerated successfully${NC}"
        echo -e "${YELLOW}Note: Backup saved as CHANGELOG.md.backup${NC}"
    else
        echo -e "${RED}✗ Failed to regenerate CHANGELOG.md${NC}"
        mv CHANGELOG.md.backup CHANGELOG.md
        exit 1
    fi
}

# Function to prepare changelog for release
prepare_release() {
    local version=$1

    if [ -z "$version" ]; then
        echo -e "${RED}Error: Version tag required${NC}"
        echo "Usage: $0 release v0.3.0-beta"
        exit 1
    fi

    # Validate version format
    if ! [[ $version =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9]+)?$ ]]; then
        echo -e "${RED}Error: Invalid version format${NC}"
        echo "Expected format: v0.3.0 or v0.3.0-beta"
        exit 1
    fi

    echo -e "${BLUE}Preparing changelog for release ${version}...${NC}"

    # Check if tag already exists
    if git tag -l | grep -q "^${version}$"; then
        echo -e "${YELLOW}Warning: Tag ${version} already exists${NC}"
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    # Backup current changelog
    cp CHANGELOG.md CHANGELOG.md.backup

    # Generate changelog with the new tag
    if git cliff --tag "$version" -o CHANGELOG.md; then
        echo -e "${GREEN}✓ CHANGELOG.md updated for ${version}${NC}"
        echo ""
        echo -e "${YELLOW}Next steps:${NC}"
        echo "1. Review CHANGELOG.md"
        echo "2. git add CHANGELOG.md"
        echo "3. git commit -m \"chore(release): update changelog for ${version}\""
        echo "4. git tag -a ${version} -m \"Release ${version}\""
        echo "5. git push origin ${version}"
    else
        echo -e "${RED}✗ Failed to prepare release changelog${NC}"
        mv CHANGELOG.md.backup CHANGELOG.md
        exit 1
    fi
}

# Function to check recent commits
check_commits() {
    echo -e "${BLUE}Checking recent commits for conventional format...${NC}"
    echo ""

    local unconventional=0

    # Get last 10 commits
    while IFS= read -r commit; do
        message=$(echo "$commit" | cut -d' ' -f2-)

        # Check if commit follows conventional format
        if [[ $message =~ ^(feat|fix|docs|style|refactor|perf|test|chore|ci|revert)(\(.+\))?!?:\ .+ ]]; then
            echo -e "${GREEN}✓${NC} $message"
        else
            echo -e "${RED}✗${NC} $message"
            ((unconventional++))
        fi
    done < <(git log -10 --pretty=format:"%h %s")

    echo ""
    if [ $unconventional -eq 0 ]; then
        echo -e "${GREEN}All recent commits follow conventional format!${NC}"
    else
        echo -e "${YELLOW}Found $unconventional commits not following conventional format${NC}"
        echo -e "${YELLOW}See .github/CHANGELOG_GUIDE.md for conventional commit examples${NC}"
    fi
}

# Main script logic
case "${1:-help}" in
    preview)
        preview_unreleased
        ;;
    update)
        update_changelog
        ;;
    full)
        regenerate_full
        ;;
    release)
        prepare_release "$2"
        ;;
    check)
        check_commits
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo -e "${RED}Error: Unknown command '$1'${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac
