# Repository Git Workflow

This rule defines the strict Git and GitHub workflow for the `pimp-empires` project now that direct push access is available for the main repository (`upstream`).

## Small & Quick Fixes
For trivial bug fixes, UI tweaks, and simple changes:
1. Work directly on the local `main` branch.
2. Commit your changes.
3. Push directly to the live repository's main branch:
   ```bash
   git push upstream main
   ```

## Larger Features & Refactors
For significant features, large refactors, or anything requiring substantial testing and review:
1. Create a dedicated feature branch from `main`:
   ```bash
   git checkout -b feature/<feature-name>
   ```
2. Commit your work to the feature branch.
3. Push the feature branch directly to the main repository:
   ```bash
   git push upstream feature/<feature-name>
   ```
4. Open a Pull Request on GitHub against `main`. Use `gh pr create` with an appropriate title and body.

**Note:** Always ensure your local `main` branch is in sync with `upstream/main` before starting new work.
