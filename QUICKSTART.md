# Getting the Datasphere Cleanup app working on a new device

From nothing installed to the app open and ready to use.

---

## Before you start — requirements

- **An Apple Silicon Mac** (M1, M2, M3, or M4). This will *not* run on older Intel Macs.
- **SAP network / VPN** connection.
- **SAP Datasphere admin credentials** for the tenants you'll clean.

---

## Step 1 — Download the app

1. On the new device, connect to the **SAP VPN**.
2. Go to the Releases page:
   **https://github.tools.sap/I777983/datasphere-cleanup/releases/latest**
3. Under **Assets**, click **`Datasphere Cleanup.dmg`** (~223 MB) to download it.

---

## Step 2 — Install it

1. In **Downloads**, double-click **`Datasphere Cleanup.dmg`** to mount it. This makes
   a temporary drive appear (like plugging in a USB stick).
2. A window opens showing the **Datasphere Cleanup** app.
3. Drag the app into your **Applications** folder.
4. **Eject the disk image:** in a Finder sidebar, find **Datasphere Cleanup** under
   **Locations** and click the **⏏ eject** icon next to it (or right-click it → **Eject**).
   This just disconnects the temporary drive — the app you copied to Applications is
   unaffected.

---

## Step 3 — First launch *(the important one-time step)*

> ⚠️ The first time you open the app, macOS will show:
> *"Apple could not verify 'Datasphere Cleanup' is free of malware…"*
> This is **expected** — the app is internally signed but not registered with
> Apple's paid developer program. It is safe to open. Here's how to allow it:

1. When the message appears, click **Done**.
2. Open the **Apple menu ()** → **System Settings**.
3. Go to **Privacy & Security** in the sidebar.
4. Scroll down to the **Security** section. You'll see:
   *"Datasphere Cleanup" was blocked to protect your Mac.*
5. Click **Open Anyway** next to it.
6. Authenticate with **Touch ID or your password** if prompted.
7. Click **Open Anyway** once more in the final dialog.

The app now launches, and **macOS remembers it — every future launch is a normal
double-click.**

### If "Open Anyway" isn't shown, or the app still won't open

Open the **Terminal** app (Applications → Utilities → Terminal), paste this exactly,
and press **Return**:

```bash
xattr -dr com.apple.quarantine "/Applications/Datasphere Cleanup.app"
```

Then open the app normally. This clears the "downloaded from the internet" flag that
triggers the block. It's safe — it affects only this one app.

---

## Step 4 — Ready to use

On first launch the app **automatically**:
- Creates the folder **`~/Documents/Datasphere Cleanup/`**
- Seeds its config (`config/settings.yaml`, `config/allowlist.txt`) there
- Creates the `outputs/` folders for logs and reports

**Nothing to edit or set up.** The main window opens with its three sections —
**Authentication**, **Pipeline**, and **Workshop** — and the app is ready to work.

---

## Quick reference

```
VPN on → Releases page → download .dmg
     → drag to Applications → eject the .dmg
     → open the app → "Apple could not verify…" appears
     → System Settings → Privacy & Security → Open Anyway → authenticate → Open Anyway
     → app opens, self-configures → ready
```

**The one thing that trips people up:** the first launch is blocked by macOS. Approve it
once via **System Settings → Privacy & Security → Open Anyway** (not a double-click), and
you're set.
