# Windows installation

Supported release: Windows x64.

## Fresh install

1. Open the latest GitHub Release.
2. Download `Video.Intake.App_<version>_x64-setup.exe`.
3. Run the installer and keep the default per-user destination unless a
   different location is required.
4. If SmartScreen appears, confirm that the file came from this project's
   GitHub Release, choose **More info**, then **Run anyway**.
5. Launch **Video Intake App** and complete the in-app first-run setup.

The updater artifact is cryptographically signed by the project updater key.
This is not Windows Authenticode signing, so Windows may still show an unknown
publisher warning.

## First run

- Select an existing Obsidian-compatible vault root or an empty folder reserved
  for notes.
- Start with the free/local route. Provider API keys are optional.
- Confirm the Settings page shows the backend as connected before processing a
  source.
- Use a preview or dry-run before the first real note write.

## Upgrade

Use **Settings -> Version and updates**. The app downloads a signed updater
artifact, stops only its own FastAPI sidecar, installs the update, and restarts.
If an update fails, the current installation and external note vault should
remain available.

For a manual upgrade, close the app and run the newer setup executable over the
existing installation. Do not delete the note vault.

## Uninstall

Use **Settings -> Apps -> Installed apps -> Video Intake App -> Uninstall**.

Uninstalling the program must not delete:

- the externally selected note vault;
- notes, audio, or attachments stored in that vault;
- optional local model files outside the application directory.

The user configuration under the home directory may remain so a reinstall can
reuse settings. Remove it manually only when intentionally clearing local API
keys and app preferences.

## Acceptance checklist

- Installer completes without leaving a locked sidecar process.
- Start-menu entry launches one app and one owned sidecar.
- First-run setup can finish without an API key.
- An update preserves settings and the external vault.
- Uninstall removes the app but preserves the external vault.
