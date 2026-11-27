# Installing on the end user's Mac

**Requires:** a Mac with Apple silicon (M1 or newer) and macOS 14 Sonoma or newer.
Check via Apple menu → *About This Mac*: *Chip* should say "Apple M…".

## 1. Build (on your own Mac)

```bash
./scripts/build_app.sh
```

This produces `dist/Anonimiseren.zip` (~47 MB).

## 2. Transfer and install

1. Copy `Anonimiseren.zip` to the target Mac (AirDrop, USB stick) and double-click to unzip.
2. Drag **Anonimiseren** into the **Applications** folder.
3. The app is not notarized by Apple, so macOS blocks it the first time. Remove the quarantine
   flag once in Terminal (you do this, not the end user):

   ```bash
   xattr -dr com.apple.quarantine /Applications/Anonimiseren.app
   ```

   Without Terminal: open the app once, click *Done*, go to *System Settings → Privacy &
   Security*, scroll down and click **Open Anyway** next to "Anonimiseren".
4. Open the app and do the first start yourself. The deduce cache is prebuilt into the app, so
   it is ready within seconds. (macOS may take up to a minute on the very first launch while it
   checks the app.) While a file is processed, the window shows which page is being read.
5. If macOS asks whether Anonimiseren may access the *Documents* folder, click **Allow** — the
   results are stored there.
6. Keep the app in the Dock: right-click its Dock icon → *Options* → *Keep in Dock*.

## 3. Fill in the personal details (important)

In the app: menu **Anonimiseren → Mijn gegevens bewerken…** (`⌘ ,`). The file opens in TextEdit.
Fill in the patient's name, initials, date of birth (used when `data_vervangen` is on),
names of family members and regular doctors, address and patient numbers, then save. A filled-in example: [`tests/sample-settings.toml`](tests/sample-settings.toml).

The file lives at `~/Documents/Anonimiseren/mijn-gegevens.toml`. Changes apply immediately;
no restart needed.

## 4. Instructions for the end user (Dutch, to pass on)

> 1. Sleep een brief (Word, PDF, scan of foto) op het **Anonimiseren**-icoon in het Dock,
>    of in het venster van de app.
> 2. Na een paar seconden opent Finder met het nieuwe bestand al geselecteerd:
>    *"… (geanonimiseerd).docx"*.
> 3. Sleep dát bestand naar Claude.
>
> Alle resultaten staan in **Documenten → Anonimiseren → Geanonimiseerd**.

## Updating

Build a new version, replace the app in *Applications* and repeat step 3 of "Transfer and
install". The personal details are kept, as they live in *Documents*.
