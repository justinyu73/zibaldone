# macOS installation

Supported release: Apple Silicon (`aarch64`). Intel Mac is not currently a
published target.

## Fresh install

1. Open the latest GitHub Release.
2. Download `Video.Intake.App_<version>_aarch64.dmg`.
3. Open the DMG and drag **Video Intake App** to **Applications**.
4. Open the app from Applications.
5. First launch shows **"Video Intake App" 已損毀，無法打開** — this is
   Gatekeeper's wording for a quarantined app without Apple notarization, not
   actual corruption (verified in practice 2026-07-05: Control-click Open and
   Privacy & Security "Open Anyway" do NOT clear this variant). After confirming
   the DMG came from this project's GitHub Release, remove the quarantine flag
   for this app only:

   ```bash
   xattr -r -d com.apple.quarantine "/Applications/Video Intake App.app"
   ```

6. Open the app and complete the in-app first-run setup.

The updater artifact has the project's Tauri updater signature. The app has no
Apple Developer ID signing or notarization, so Gatekeeper flags the first
install; in-app updates afterwards are unaffected. The permanent fix is Apple
Developer Program signing + notarization in `release.yml` (Tauri supports it
natively via `APPLE_CERTIFICATE`/`APPLE_ID` secrets) — pending a paid Apple
Developer account. Keep the `xattr` command scoped to this app path; do not
run blanket quarantine removal.

## First run

- Grant access only to the note vault and media files intentionally selected.
- Start with the free/local route. Provider API keys are optional.
- Confirm the Settings page shows the backend as connected.
- Use preview before the first real note write.

## Upgrade

Use **Settings -> Version and updates** for a signed in-app update. For a manual
upgrade, quit the app, open the new DMG, and replace the app in Applications.
The selected note vault is external and must remain untouched.

## Uninstall

Quit the app and move **Video Intake App** from Applications to Trash.

The external note vault is user data and must not be removed. The local app
configuration may remain in the user's home directory; remove it manually only
when intentionally clearing API keys and preferences.

## Acceptance checklist

- DMG opens and the app can be copied to Applications.
- The first launch reaches the setup flow after the documented Gatekeeper path.
- First-run setup can finish without an API key.
- An update preserves settings and the external vault.
- Removing the app preserves the external vault.
