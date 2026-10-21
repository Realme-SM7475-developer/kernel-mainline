.. SPDX-License-Identifier: GPL-2.0-only

Arch Linux ARM bootstrap on the Realme GT Neo5 SE
===============================================

The opt-in bootstrap uses the existing Android v4 boot/vendor_boot/dtbo
layout and the verified SM7475 display kernel. The default RAM mode downloads
a pinned Arch Linux ARM AArch64 rootfs over a dedicated USB Ethernet link
and extracts it onto a 4 GiB tmpfs. No partition is formatted or used to store the rootfs.
The installation and its changes are lost when the device reboots.

An optional persistent mode boots an installed ext4 root on userdata
automatically. It requires an explicitly authorized destructive installation,
described below. It does not download or extract a rootfs at boot.

Before installation, storage inspection found a 16 MiB metadata partition
and no directly recognizable plaintext filesystem on userdata. This does not imply that
userdata is empty. Keep the working three-image rollback set intact.

Prerequisites
-------------

Obtain the generic AArch64 archive and its detached signature from an
Arch Linux ARM mirror. The published build-system signing fingerprint is
``68B3537F39A313B3E574D06777193F152BDBE6A6``; the builder verifies that exact
signer using an isolated GnuPG home. See:

* https://archlinuxarm.org/platforms/armv8/generic
* https://archlinuxarm.org/about/downloads
* https://archlinuxarm.org/about/package-signing

The host needs Python 3.11 or newer, GnuPG, readelf and an AArch64 static
BusyBox with configfs, networking, chroot, switch_root and mount applets.
Supply an Ed25519 SSH public key. Keep its private key outside the source
tree and image directories.

Build and package
-----------------

Run from the kernel source tree, substituting local input paths::

  python3 tools/boot/sm7475-arch/build_initramfs.py \
    --rootfs /path/ArchLinuxARM-aarch64-latest.tar.gz \
    --signature /path/ArchLinuxARM-aarch64-latest.tar.gz.sig \
    --signing-key /path/archlinuxarm-build-key.asc \
    --busybox /path/busybox.static \
    --ssh-public-key /path/id_ed25519.pub \
    --output-dir /path/arch-bootstrap

The builder obtains bsdtar and its exact shared libraries from the signed
archive. The device uses that bsdtar to preserve ownership, permissions,
ACLs and extended attributes when extracting the rootfs. The archive's
SHA256 is embedded in the ramdisk and checked again before extraction.
Only the SSH public key is embedded. The ramdisk must fit the original
22589876-byte vendor ramdisk region.

Reuse the matching, already-built Image, config and DTB::

  OUT_DIR=/path/arch-images \
  INITRAMFS_IMAGE=/path/arch-bootstrap/arch-initramfs.cpio.gz \
    tools/build-sm7475.sh package

Preserve the existing AVB keys in the new output's keys directory. With
``INITRAMFS_IMAGE`` unset, packaging keeps the existing diagnostic ramdisk
generator and its USB shell. Verify all image hashes, AVB, embedded kernel,
DTB and ramdisk before flashing the matching three images to slot a.

USB link and first boot
-----------------------

The gadget keeps an ACM rescue console and adds CDC ECM:

* Host MAC: ``02:74:75:00:00:01``; address ``192.168.77.1/24``.
* Device MAC: ``02:74:75:00:00:02``; address ``192.168.77.2/24``.
* Linux host interface normally appears as ``enx027475000001``.

A host NetworkManager profile can provide Internet sharing on this link::

  nmcli connection add type ethernet ifname enx027475000001 \
    con-name sm7475-arch-usb connection.permissions user:"$USER" \
    connection.autoconnect no 802-3-ethernet.mac-address 02:74:75:00:00:01 \
    ipv4.method shared ipv4.addresses 192.168.77.1/24 \
    ipv4.never-default yes ipv6.method disabled
  nmcli connection up sm7475-arch-usb

Serve the signed archive from the dedicated host address::

  python3 -m http.server 8080 --bind 192.168.77.1 --directory /path/downloads

After the bootstrap boots, run ``arch-prepare`` on the USB serial shell.
It downloads and verifies the archive, extracts the RAM rootfs, configures
USB networking and key-only SSH, generates SSH host keys and validates the
native programs. Temporary dev/proc/sys binds are removed after this check.
Run ``arch-boot`` to request the PID 1 handoff. The initramfs moves its API
mounts, including the configured gadget, into the new root and executes
``switch_root /newroot /sbin/init``. The Arch system has an independent ACM
rescue-shell service in addition to SSH.

Verify ``/proc/1/exe``, ``/etc/os-release``, systemd service states, SSH and
HTTPS after handoff. A successful chroot alone is not a systemd boot.
SSH host keys are regenerated with each RAM installation. Normal Arch
kernel packages in the rootfs do not replace the Android boot images;
continue using the matching custom kernel and its modules/firmware.

Initialize the package keyring after each fresh RAM installation::

  pacman-key --init
  pacman-key --populate archlinuxarm

Device validation, 2026-10-21
----------------------------

The final image set in ``out-arch-bootstrap-release-20261021`` boots with
``/proc/1/exe`` pointing to ``/usr/lib/systemd/systemd``. Systemd reports
``running`` with zero failed units; sshd, systemd-networkd and the ACM
rescue-shell service are active. SSH key authentication, serial commands,
HTTPS and package-keyring initialization pass. The user reports tty1 on
the phone. The RAM root uses about 2.1 GiB, leaving about 4.7 GiB available
on this 8 GiB device. This verifies a console system, not a graphical
desktop or a persistent installation.

The first handoff exposed two bootstrap bugs. Interactive ash ignores
SIGTERM, so the final init records and terminates its actual serial child
before deleting the old root. The Arch rescue binary must keep basename
``busybox`` for applet dispatch. Both fixes are present in the final image
and were verified through a complete flash, rootfs preparation and handoff
without manual patching. Temporary dev/proc/sys binds during preparation
also let systemd and ssh-keygen inspect their expected API filesystems.

Evidence is under the project ``archlinuxarm/`` directory, especially
``arch-bootstrap-release-validation.json``, ``arch-release-systemd-validation.txt``,
``arch-release-serial-validation.txt`` and ``arch-release-pacman-network.txt``.

Recovery
--------

The bootstrap waits for an explicit ``arch-boot`` request and provides a
serial shell before switching root. Reboot returns to that bootstrap and
requires downloading the RAM rootfs again. To restore the earlier pure
diagnostic environment, use the device keys to enter fastboot and flash
the saved normal-display boot_a/vendor_boot_a/dtbo_a set together, then
select slot a and reboot. Linux ``reboot bootloader`` remains unsupported.

Optional persistent userdata root
---------------------------------

This mode replaces Android userdata with ext4. Formatting destroys Android
user data, including apps, photos and files. Obtain explicit agreement to
that loss and back up anything needed before executing the installer.
Restoring stock boot images does not restore erased Android user data.
The partition table, metadata and other Android partitions are not changed.

Run the inspection first, inside the working RAM-root Arch system. Obtain
the GPT PARTUUID and exact byte size from that device, rather than copying
another phone's values::

  bash install-userdata PARTUUID SIZE_BYTES

Inspection is read-only. The installer checks the UUID, userdata label,
size, mount state and device-mapper holders and requires a tmpfs source root
with systemd as PID 1. Only after the destructive operation is authorized::

  bash install-userdata PARTUUID SIZE_BYTES --erase-userdata

The script formats only that existing partition, then copies the running
Arch RAM installation, preserving ACLs, extended attributes, packages,
SSH host keys and configuration. API mounts, temporary files and changing
logs are excluded. Do not install packages or change files during copying.
It writes an ext4 UUID-based fstab, validates systemd and sshd, writes an
installation marker and checks the unmounted filesystem. Failure requires
inspection before retrying; a retry with the erase flag formats again.
The current RAM system stays running throughout installation.

Build the bootstrap as above with the additional option::

  --root-partuuid PARTUUID

Package and validate the matching boot/vendor_boot/dtbo set. Keep the RAM
bootstrap image set separately for recovery. This initramfs automatically
finds the exact userdata partition by GPT PARTUUID, mounts it as ext4,
checks its installation marker and init executable, then switches to
systemd. No HTTP server or rootfs download is needed for persistent boot.
An absent or invalid installation leaves the ACM rescue shell available;
the initramfs never formats a partition. In that shell, ``arch-prepare``
retries mounting userdata and ``arch-boot`` requests the handoff.

Persistent device validation, 2026-10-21
--------------------------------------

After explicit authorization to erase Android user data, the installer
completed on the existing 238174662656-byte userdata partition. All five
e2fsck phases passed. A read-only remount verified the installation marker,
fstab, core executables, USB configuration and SSH identity against the
running RAM installation. The partition table was not changed.

The matching ``out-arch-userdata-20261021`` boot/vendor_boot/dtbo set passed
AVB and payload checks and was flashed to slot a. The kernel, config and
DTB match the normal-display version. The first automatic boot mounted
``/dev/sda14`` as the writable ext4 root and ran systemd as PID 1. A
controlled ``systemctl reboot`` then produced a different boot ID and
preserved a witness file written before reboot. The SSH identity also
remained unchanged. No manual rootfs preparation was needed on either boot.

Both boots reported systemd ``running`` without failed units, with sshd,
systemd-networkd and the ACM rescue shell active. SSH, serial commands and
HTTPS passed. The root had about 216 GiB free and the phone had about
6.8 GiB of available RAM after boot. The framebuffer console became ready
within about 0.72 seconds; the user confirmed normal screen output.

Evidence is in ``archlinuxarm/userdata-install.txt``,
``userdata-install-readback.txt``, ``userdata-image-validation.json``,
``userdata-first-boot.txt``, ``userdata-first-serial.txt`` and
``userdata-reboot-validation.txt``. These checks establish persistent
console boot; touch, GPU acceleration, wireless and phone power management
still require separate bring-up. Keep the RAM bootstrap and diagnostic
rollback images; restoring them does not undo the userdata formatting.

Xfce desktop with software rendering
-----------------------------------

The persistent Arch root can run Xfce on the existing DPU/DSI display even
while GPU acceleration is unavailable. Copy ``tools/boot/sm7475-arch/setup-desktop``
onto the phone and run it from the native Arch root shell::

  bash setup-desktop --install-packages
  systemctl start lightdm

The installer performs a full package upgrade, installs Xorg, LightDM,
the Xfce session, fonts and standard user directories, and configures local
automatic login as the unprivileged ``alarm`` user. It leaves SSH key
authentication and the ACM rescue service intact. The working kernel and
Android boot images are not replaced by these userspace changes.

Xorg uses modesetting on ``/dev/dri/card0`` with ``AccelMethod=none``, a
shadow framebuffer and a software cursor. Both LightDM and its session
set ``LIBGL_ALWAYS_SOFTWARE=1``; the initial Xfce profile disables window
compositing and uses 192 DPI. Screen blanking is disabled because touch
input is not available to wake the screen. Subsequent runs preserve the
user's existing Xfce settings.

The present kernel does not enable Landlock. With pacman 7.1 the optional
package installation adds ``DisableSandboxFilesystem`` to pacman.conf;
the download user, syscall sandbox and required package signatures remain
enabled. Review that compatibility setting after adding Landlock support.
On a slow mirror, pacman's ``--disable-download-timeout`` option can allow
large downloads to complete without discarding already cached packages.

After verifying the desktop, enable automatic graphical startup::

  systemctl enable lightdm
  systemctl set-default graphical.target

To return to the console over SSH or the USB serial rescue shell::

  systemctl disable --now lightdm
  systemctl set-default multi-user.target
  chvt 1

The setup must give the user ownership of every configuration parent
directory. Giving ownership only to the final xfconf directory leaves
root-owned parents, prevents Xfce from saving settings and can make the
panel and desktop exit. The script explicitly configures these parents
and checks their writability as ``alarm`` before continuing.

The device passed a controlled reboot into ``graphical.target`` with
LightDM enabled and automatic login to Xfce. Xorg, xfce4-session, xfwm4,
xfce4-panel and xfdesktop remained running as expected; the desktop clients
run as ``alarm``. RandR reported 1240x2772 on DSI-1, compositing was disabled,
192 DPI was active and both screen blanking and DPMS were disabled. The
captured X root window shows the wallpaper, desktop icons and program bars.
The user confirmed normal output on the phone's physical screen. The native
kernel remains 6.18.0 and the root remains userdata/ext4.

Systemd reported ``running`` with zero failed units; SSH, USB networking,
the serial rescue service and HTTPS still passed after reboot. Available
RAM was about 6.3 GiB and the root had about 214 GiB free. Evidence and a
desktop screenshot are under ``archlinuxarm/desktop/``, especially
``reboot-validation.txt``, ``Xorg.0.log`` and ``desktop.png``. The X server's
GPU probes may still report missing GPU errors; this validates software
desktop rendering, not GPU acceleration. Touch input remains unavailable.

References:

* https://man.archlinux.org/man/extra/xorg-server/modesetting.4.en
* https://wiki.freedesktop.org/www/Software/LightDM/CommonConfiguration/
* https://docs.xfce.org/xfce/xfce4-session/start

Plasma Mobile on Wayland
-----------------------

The optional Plasma Mobile setup retains the verified Xfce installation
as a recovery session. From the persistent Arch phone, copy and run
``tools/boot/sm7475-arch/setup-plasma-mobile``::

  bash setup-plasma-mobile --install-packages

This requires the ``setup-desktop`` Xfce fallback to have been configured
first. It installs Plasma Mobile, settings, QMLKonsole, SDDM and diagnostic
utilities. It prepares an SDDM automatic Wayland login as ``alarm`` and
leaves display-manager selection unchanged until explicitly switched.
SDDM's greeter uses the known Xorg path; the selected user session is
native Wayland on DRM.
No kernel build, boot image replacement or userdata formatting is involved.

The session forces KWin's DRM device to ``/dev/dri/card0`` and uses Mesa
llvmpipe with ``kms_swrast``. KWin 6.8's DRM backend advertises only OpenGL
compositing, so ``KWIN_COMPOSE=O2`` selects its software GL path; the old
QPainter override is unsuitable for this version. Qt Quick uses
``QT_QUICK_BACKEND=rhi`` and ``QSG_RHI_BACKEND=opengl`` on the same software
renderer. Using ``QT_QUICK_BACKEND=software`` instead left the application
drawer blank: its masks and shader effects need the GL scene graph.

The setup skips the initial wizard, disables automatic locking, idle
screen dimming/off and automatic suspend because touch input is not yet
available. It keeps the networkd-managed USB gadget outside any future
NetworkManager management. These are bring-up settings to review after
touch and power management become available.

For the first switch, schedule a timed Xfce recovery before stopping the
working display manager::

  systemd-run --unit=sm7475-mobile-rollback --on-active=180s \
    /usr/local/libexec/sm7475-restore-xfce
  systemctl stop lightdm
  systemctl start sddm

After verifying the mobile shell and applications, cancel the timer and
enable the new display manager for subsequent boots::

  systemctl stop sm7475-mobile-rollback.timer
  systemctl disable lightdm
  systemctl enable sddm
  systemctl set-default graphical.target

To restore Xfce over SSH or the ACM root shell::

  /usr/local/libexec/sm7475-restore-xfce

Device validation, 2026-10-21: Plasma Mobile/KWin 6.8.0, SDDM 0.21.0 and
Mesa 26.2.5 booted with KWin reporting DRM, EGL and llvmpipe (LLVM 23.1.3).
The shell identified itself as ``org.kde.plasma.mobileshell``. Its app
drawer displayed application icons and QMLKonsole ran successfully. The
native display remained 1240x2772; the mobile preset used scale 3. A
controlled reboot retained automatic SDDM login and the RHI configuration,
with systemd ``running`` and no failed units. SSH, ACM commands, USB
networking and HTTPS passed. The user confirmed normal physical display.

The kernel remains the existing 6.18.0 build and the root remains
userdata/ext4. Available RAM was about 4.8 GiB, with about 211 GiB of free
disk space. This is CPU rendering; GPU acceleration and touch are still
unavailable. Diagnostic screenshots and logs are under
``archlinuxarm/plasma-mobile/``, particularly ``reboot-validation.txt``,
``reboot-support-info.txt``, ``reboot-outputs.txt`` and
``reboot-serial-validation.txt``.

Wayland socket names are not fixed: this session used ``wayland-1``.
When running graphical diagnostics through SSH, obtain WAYLAND_DISPLAY
from the actual session environment rather than assuming ``wayland-0``.

References:

* https://archlinuxarm.org/packages/aarch64/plasma-mobile
* https://github.com/KDE/kwin/blob/v6.8.0/src/backends/drm/drm_backend.cpp
* https://doc.qt.io/qt-6/qtquick-visualcanvas-adaptations-software.html

Battery telemetry bring-up
-------------------------

The ADSP/PMIC GLINK reference is ``iLtanaka/linux-marble`` at commit
``c9f87aac17d306786d1d15f67d8bdd226770e27a``. This phone additionally has
an AP-connected external gauge: stock DTBO entry 0 declares a gauge at
QUP0 SE0 (0x980000), address 0x55, with ``qcom,batt_bq28z610``. Its pins
are GPIO0/1, function qup0, at 100 kHz. Use the mainline ``ti,bq28z610``
driver for battery readings; do not copy Marble's battery design values,
Xiaomi authentication messages or shifted property IDs.

The first ADSP-only hardware test booted successfully and registered
power supplies, but its battery reported ``QCOMMBATT01``, fixed 50%, 4 V,
25 degrees C and zero full capacity/current. These are not validated
battery readings. The PMIC GLINK node now references the external gauge
with ``qcom,external-fuel-gauge``; the battery manager omits its firmware
battery supply and still exposes USB supply telemetry. This avoids
combining a placeholder battery with the physical battery in UPower.
An attempted UPOWER_IGNORE udev rule did not work with UPower 1.91.5;
it was removed and is not part of the setup.

``sm7475-realme-gt-neo5-se-battery.dtsi`` describes the gauge, GENI I2C,
GPI DMA, IPCC, AOSS QMP, ADSP SMP2P, PAS remoteproc and GLINK edge. Stock
GPI DMA uses 0x900000, interrupts 244-255, mask 0x7e and SMMU stream
0x5b6. The ADSP carveout is 40 MiB at 0x85700000, matching this phone's
stock DT and ABL fixups; its original node path is retained. The copied
downstream PMIC GLINK and log instances are disabled to avoid binding
the mainline singleton twice. USB retains peripheral mode.

The in-kernel PD mapper uses the SM8350 domain table, including
``msm/adsp/charger_pd`` at QMI instance 74, checked against the phone's
``battmgr.jsn``. ABL replaces root model/compatibles with Ukee MTP, Senna
and ``qcom,ukee``, so the mapper recognizes that stock identity too.
The board fragment builds these dependencies in because the persistent
Arch root has no modules matching the custom 6.18 kernel.

On the persistent Arch phone, copy and run
``tools/boot/sm7475-arch/setup-battery``::

  bash setup-battery

The script mounts ``modem_a`` read-only, checks the ELF32 segment files
and charger service mapping, then copies ``adsp2.mdt``, its segments and
``battmgr.jsn`` into
``/usr/lib/firmware/qcom/sm7475/realme/gt-neo5-se/``. Copied bytes are
checked and recorded in SHA256SUMS. Firmware is device-specific and is
not included in the repository. No firmware partition is changed.

``sm7475-adsp.service`` starts the matching offline remoteproc after
userdata is mounted, retrying the early request that precedes
switch_root. It leaves an already running processor alone and reports
unexpected states instead of forcing a restart. Notification requests
use the battery manager request mutex, and supply-change events after
startup refresh earlier ``-EAGAIN`` reads.

The setup also installs ``/etc/tmpfiles.d/sm7475-battery.conf`` to set
``/sys/module/bq27xxx_battery/parameters/poll_interval`` to 15 seconds.
The gauge has no interrupt on this board, and its default active polling
interval is 360 seconds. The shorter interval refreshes battery status
without requiring diagnostic reads. It only changes telemetry polling;
it does not program charging controls or gauge calibration.

Hardware validation, 2026-10-21: the external gauge reported 54%, about
7.71 V, 30.8-31.6 degrees C, 947 mAh remaining and 1778 mAh full capacity.
UPower exposed one battery, sourced from BQ28Z610; the placeholder
``qcom-battmgr-bat`` was absent. A Plasma Mobile screenshot showed 54%
in the status bar and the user confirmed the physical display.

A controlled reboot retained the BQ28Z610 battery, automatic ADSP startup
and the 54% desktop indication. Systemd was running with no failed units;
SDDM, UPower, SSH, networkd and the ACM rescue shell were active. USB
networking, HTTPS and actual ACM battery reads passed. The userdata
root and desktop configuration were retained. No I2C timeouts or gauge
read errors were observed. The known single pre-reset MDSS SMMU fault
on stream 0x2800 remains, with normal display.

Evidence is under ``archlinuxarm/battery/``, including
``gauge-image-validation.json``, ``gauge-first-boot.txt``,
``gauge-upower.txt``, ``gauge-desktop.png``,
``gauge-reboot-validation.txt`` and ``gauge-reboot-serial.txt``.
The USB supply reported online while the battery reported a small
net discharge; do not infer validated battery charging from USB online.
No gauge calibration, authentication or fast charge controls are
programmed. Full charging, protection and thermal management still
need separate validation. Before returning to the older kernel without
ADSP support, disable ``sm7475-adsp.service`` to avoid a missing-device
service failure; it does not block the existing desktop recovery path.

A subsequent USB-A charger/A-C cable test, with the connection secured,
detected VBUS up to 5.216 V. All 40 samples still reported discharging:
neither instantaneous nor average battery current became positive, and
UPower stayed in state 2. The initial test with a loose charger connection
is inconclusive. Thus absence of a charging icon currently agrees with
the gauge, rather than establishing a Plasma display bug. Stock boot
logs and charger source additionally contain charge-enable, input-current
and temperature-control operations that this telemetry setup does not
implement. See ``archlinuxarm/charging/plug-test-tight.jsonl`` and
``charging-status-audit.json``. USB online must not be converted into a
synthetic battery Charging state.

The 15-second polling configuration was verified live and after a
controlled reboot. The new boot retained systemd running, zero failed
units, the userdata root, SDDM, UPower, SSH and the ADSP startup service.
The battery still truthfully reported discharging. This change fixes
refresh latency; it does not claim to enable battery charging.

S3910 touchscreen
=================

The S3910 touchscreen is built in and initializes automatically before
userspace. Plasma Mobile taps, swipes and two-finger contacts work after
reboot. The committed configuration selects GENI SPI and
``TOUCHSCREEN_SYNAPTICS_S3910=y``; no module installation or startup
service is needed.

The Senna stock DT and Android logs identify the controller on QUP0 SE4
SPI at 0x990000, GPIO16-19, mode 0 and up to 12 MHz. GPIO20 is active-low
reset and GPIO21 is a level-low interrupt. VDD is PM8350C L3 at 3.008 V;
VDDIO is PM8450 L4 at 1.8 V, gated by GPIO97 driven high. The vendor driver
ignores the active-low flag on its legacy enable1v8_gpio property and
explicitly drives a physical high level.

Three pieces are needed in addition to the SPI controller node:

* ``synaptics-s3910`` implements SPI TouchComm v1 using the on-device
  application firmware. It uses heap-backed transfer buffers, 0xff read
  dummy bytes, bounded continuation reads and command responses, and
  slot-based multitouch. Limits and contact count come from application
  information. The RAM report has an object count followed by eight bytes
  per active object. There is no firmware erase/write/commit operation.
* Cape's GPIO function must use ``MSM_GPIO_PIN_FUNCTION(gpio)``. Without
  the GPIO function flag, generic pinmux rejects the touch regulator's
  own GPIO97 request after selecting its GPIO pinctrl state. The unused
  stock camera ``/soc/gpio-regulator@0`` is disabled to avoid a separate
  GPIO97 conflict; revisit that shared pin when adapting cameras.
* QUP0 needs SMMU stream 0x5a3 for payload DMA. GPI0 uses the separate
  stream 0x5b6 for its rings. Both values match this phone's stock DT and
  SM8450. GENI SPI maps buffers through the QUP wrapper device. Without
  its mapping, the first nine-byte SPI read failed to return and the
  device restarted. Adding it enabled both the startup and continuation
  reads. The original GENI SPI driver is retained without diagnostic
  changes.

Hardware validation, 2026-10-21: the application identifies as
S3910PA0B0-15.2, build 4284627, with coordinates 0..12399 / 0..27719,
ten slots and a 128-byte report configuration. Udev reports
``ID_INPUT_TOUCHSCREEN=1``. The user confirmed normal Plasma taps and
swipes; evdev captured 937 frames, two simultaneous contacts and 35
complete release frames, with all coordinates in range, during the
initial module test. A user-initiated reboot during capture was recorded
as manual, and the same module worked again after that reboot.

The final built-in kernel is 6.18.0 #5, built on 2026-10-21 at 20:55:19
CST. Its initial boot registered the touchscreen at 0.735 seconds. An
agent-requested normal systemctl reboot registered it again at 0.656
seconds, without any module load command; the user confirmed touch
operation after this reboot. Boot IDs were
``d843b1c0-c764-4754-9bcf-5852ec2af63d`` and
``f805639c-d6da-4233-90d1-9d45e9a8e4c2``. Systemd was running with no failed
units; SDDM, UPower, SSH, networkd and ADSP startup were active. Real
battery telemetry remained available. No touch packet errors, SPI
timeouts or new QUP/GPI SMMU faults were observed. The known single early
MDSS stream 0x2800 fault remains with normal display.

The matching a-slot images are ``out-touch-release-20261021``. Their AVB,
SHA256, embedded kernel/DTB and unchanged userdata-bootstrap checks
passed. The release DTB is byte-identical to the working module-test DTB.
Only the touchscreen configuration changes from module to built-in.
Driver checkpatch passed without errors or warnings. The binding YAML
was parsed, but full dt-schema validation and system suspend/resume
validation have not been performed.

Evidence is in ``archlinuxarm/touch/``: ``release-image-validation.json``,
``flash-release.txt``, ``release-first-boot.txt``, ``release-reboot.txt``,
``release-reboot-events.jsonl`` and ``release-event-summary.json``.
Temporary diagnostic modules are kept outside the module search path
and are not auto-loaded. The normal battery/desktop rollback remains
``out-battery-gauge-20261021``. Flash only a matching boot/vendor_boot/dtbo
trio, then set slot a active and check retry/unbootable state before
reboot. Do not format or reinstall userdata.
