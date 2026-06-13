# Branching Strategy and Changelog Management

This document outlines our Git branching strategy and how we maintain our changelog throughout the development lifecycle.

## Branching Model

We follow a simplified GitFlow branching model:

### Main Branches

- **main**: The production-ready branch containing released code
- **develop**: The integration branch for features that will go into the next release

### Supporting Branches

- **feature/xxx**: Feature branches for new development
- **bugfix/xxx**: Branches for fixing bugs
- **release/x.y.z**: Release preparation branches
- **hotfix/xxx**: Emergency fixes for production issues

## Workflow

### Feature Development

1. Create a feature branch from `develop`:
   ```bash
   git checkout develop
   git pull
   git checkout -b feature/my-new-feature
   ```

2. Implement your changes and update the changelog:
   ```bash
   # After implementing changes
   python scripts/update_changelog.py --type added "Added new feature X"
   
   # For bug fixes
   python scripts/update_changelog.py --type fixed "Fixed issue with Y"
   
   # For changes/improvements
   python scripts/update_changelog.py --type changed "Updated Z component"
   ```

3. Commit your changes:
   ```bash
   git add .
   git commit -m "feat: implement my new feature"
   ```

4. Push your feature branch:
   ```bash
   git push -u origin feature/my-new-feature
   ```

5. Create a pull request to merge into `develop`

### Preparing a Release

1. Create a release branch from `develop`:
   ```bash
   git checkout develop
   git pull
   git checkout -b release/x.y.z
   ```

2. Finalize the release by running the release script:
   ```bash
   python scripts/create_release.py x.y.z
   ```
   This will:
   - Update the CHANGELOG.md (move "Unreleased" to a dated version)
   - Update version numbers in key files
   - Create a commit with these changes

3. Create a pull request to merge the release branch into `main`

### Creating a Release

After the release branch is merged to `main`:

1. Tag and push the release:
   ```bash
   git checkout main
   git pull
   python scripts/create_release.py --push x.y.z
   ```

2. The GitHub Actions workflow will:
   - Build the distribution packages
   - Create a GitHub release with changelog notes
   - Publish the artifacts

> **Release test gate.** Pushing to a `release/**` branch automatically
> triggers `unit-tests.yml` and `integration-tests-new.yml`. The release
> PR (`release/x.y.z` → `main`) must not be merged until both workflows
> are green — every released version is guaranteed to have a passing full
> test suite.

## Changelog Management

We maintain a single `CHANGELOG.md` file at the root of the repository.

### Structure

The changelog follows this structure:
```markdown
# Changelog

## Version x.y.z (Unreleased)

### Added
- New features

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes

## Version 0.4.0 (2024-06-03)

### Added
- ...

...
```

### When to Update the Changelog

- **Feature branches**: Add entries to the "Unreleased" section when implementing features
- **Bugfix branches**: Add entries to the "Unreleased" section when fixing bugs
- **Release preparation**: The release script updates the changelog by:
  - Renaming "Unreleased" to the new version with the current date
  - Creating a new "Unreleased" section for future development

### Maintaining the Changelog

1. Use the `update_changelog.py` script to add entries:
   ```bash
   python scripts/update_changelog.py --type added "Added new feature X"
   python scripts/update_changelog.py --type fixed "Fixed bug in function Y"
   python scripts/update_changelog.py --type changed "Updated dependency Z"
   ```

2. Always add changelog entries as part of your pull request

3. Keep entries concise and focused on the "what" and "why", not the "how"

## Pull Request Process

1. Create a pull request from your feature branch to `develop`
2. Ensure all tests pass
3. Verify your changelog entries are correct
4. Get at least one code review approval
5. Merge using the "Squash and merge" option

## Hotfix Process

For urgent fixes to production:

1. Create a hotfix branch from `main`:
   ```bash
   git checkout main
   git pull
   git checkout -b hotfix/critical-fix
   ```

2. Fix the issue and update the changelog:
   ```bash
   python scripts/update_changelog.py --type fixed "Fixed critical issue with X"
   ```

3. Commit and push your changes:
   ```bash
   git add .
   git commit -m "fix: address critical issue"
   git push -u origin hotfix/critical-fix
   ```

4. Create a pull request to merge into `main`

5. After merging to `main`, also merge the changes back to `develop`:
   ```bash
   git checkout develop
   git pull
   git merge --no-ff hotfix/critical-fix
   git push
   ```

## Release Process Checklist

1. All features for the release are merged into `develop`
2. Create a release branch `release/x.y.z`
3. Run the release script to update the changelog and version
4. Create a pull request to merge into `main`
5. After merging, tag and push the release
6. Verify the GitHub Actions workflow completes successfully
7. Verify the GitHub release is created with the correct changelog
8. Merge the release branch back into `develop`