# ConsumerOS v1

ConsumerOS is a Debian-based desktop operating system for people who want a
computer, not a Linux hobby. This repository builds an amd64 hybrid live ISO,
the installed operating system, and the native graphical tools that connect
updates, drivers, recovery, migration, application compatibility, backup, and
optional power-user features.

The v1 base is Debian 13 (trixie), GNOME 48 on Wayland, Flatpak with Flathub,
Calamares, Btrfs, Snapper, GRUB, and Debian's signed Secure Boot chain. XWayland
is installed for older applications and GNOME's X11 session remains available
where the hardware stack provides it.

## What is implemented

- A reproducible live/install ISO with BIOS and UEFI Secure Boot paths.
- A bottom taskbar, Super application menu, panel search control, centered
  running applications, app indicators, clock, notifications, and GNOME Quick
  Settings.
- Aurora Glass is the first-boot default, with three additional built-in dark
  neon wallpapers (Neon Spectrum, Velvet Rays, and Neon Circuit). The Welcome
  app exposes all four choices alongside a floating translucent taskbar and
  restrained glass surfaces. GNOME selects the monitor scale automatically,
  with fractional Wayland and native XWayland scaling enabled in Displays for
  high-DPI and mixed-DPI setups.
- A native System Hub for updates, drivers and firmware, applications, gaming,
  backups, recovery, privacy, developer mode, and system diagnostics.
- Btrfs `@`, `@home`, `@snapshots`, and `@swap` subvolumes. Offline package
  transactions create a pre-update snapshot and automatically select rollback
  when the package transaction fails.
- Stable and Current channels. Current adds Debian backports while retaining
  the stable Debian base; switching channels never converts the installation
  to Debian testing.
- A protected recovery partition containing the live root filesystem, kernel,
  and initramfs, plus a generated GRUB recovery entry.
- A live welcome screen with Try, Install, Repair, hardware validation, and
  accessibility controls.
- Windows application hand-off to the sandboxed Bottles Flatpak, with a local
  compatibility database and a confirmation surface before an installer runs.
- AppImage integration without exposing package formats in the launcher.
- Windows-user migration for files, wallpapers, fonts, supported browser
  bookmarks, and Steam library metadata, with conflict-safe copying.
- Firewall, AppArmor, portals, firmware updates, full-disk encryption in the
  installer, optional TPM tooling, and diagnostics opt-in (off by default).
- Optional one-click profiles for gaming, Windows apps, local AI, development,
  virtualization, and Snap. Optional profiles are not installed until chosen.

## Honest compatibility boundary

No operating system can guarantee every Windows game, anti-cheat driver,
printer, or vendor firmware on arbitrary hardware. ConsumerOS reports what it
can verify, keeps untested software marked untested, and delegates Windows
runtime isolation to Bottles/Wine/Proton rather than inventing another Wine
prefix manager.

The macOS provider is deliberately gated as a research preview. The v1 UI and
provider contract exist, but it will not claim that Apple services, DRM,
DriverKit, kernel extensions, or Metal applications work. Enabling it requires
an independently installed compatible runtime and an explicit warning.

## Build

The build runs in a pinned Debian container and does not install packages on
the host:

```bash
make validate
make package
make iso
make smoke
```

Artifacts are written to `.build/artifacts/`. The ISO build needs Docker,
roughly 25 GiB of temporary space, and network access to Debian mirrors. Build
parameters can be overridden without editing the project:

```bash
CONSUMEROS_ARCH=amd64 CONSUMEROS_MIRROR=https://deb.debian.org/debian make iso
```

See [architecture](docs/architecture.md), [security model](docs/security.md),
and the [release acceptance matrix](docs/release-acceptance.md) before shipping
an image to real hardware.
