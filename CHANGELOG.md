# Changes

## 0.1.0-beta.1

- Support the Japanese Windows 3.1 MYST 1.0J CD using a separately downloaded official ScummVM runtime.
- Let users choose any destination drive/folder; append MYSTJ exactly once and explain this at the top of setup.
- Validate all copied CD files and the official runtime ZIP by SHA-256.
- Keep runtime/configuration/saves dedicated to this installation; do not install old QuickTime.
- Register a per-user Windows Installed apps entry with two uninstall modes: keep settings/saves, or full removal.
- Preserve preferences and saves when reinstalling a recognized retained installation.
- Provide a right-click shortcut for the ScummVM save/load menu, alongside Ctrl+F5.
- Stage file placement, refuse unrelated nonempty folders/reparse points, and block removal while ScummVM is running.
- Package an explicit allowlist of own code and documentation only.

### Validation status

- CD detection: official ScummVM 2026.4.0 identifies the user's CD as Myst (Windows/Japanese).
- 2026-10-25: 22 isolated automated tests passed, including junction/traversal protection, changed-file preservation, cancellation, concurrent destination changes, and retained-data reinstall.
- A real-CD-data integration test passed: install, keep-settings removal, reinstall with saved data, then full removal. Tests use a temporary folder and fake registry.
- Actual installation, Windows Installed apps registration and its uninstall command were checked on the development PC.
- On Windows 11 x64 Japanese: the dedicated launcher starts the Japanese version; opening movies, linking-book entry, island movement, save-file creation and selecting the autosave from the load menu were observed.
- Both setup/uninstall choice screens and cancellation were visually checked. The live game installation was not removed during the integration tests.
- Audio output, manual save naming, full game completion, all puzzles/movies and other PCs remain unverified. Synthetic keyboard input was not reliable during UI testing; the right-click menu was verified.
