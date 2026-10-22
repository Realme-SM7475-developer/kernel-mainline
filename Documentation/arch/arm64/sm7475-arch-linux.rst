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

Adreno 725 hardware rendering
----------------------------

The SM7475 GPU is advertised by this phone's stock DT as Adreno725v1,
chip ID ``0x07030002``. The stock ``gen7_4_0`` description shares the A730
clock-gating/protection tables, SQE/GMU firmware and 2 MiB GMEM. The GPU
catalog now recognizes that real revision. The board describes its GPU,
GMU, Cape-compatible GPUCC and independent Adreno SMMU, with the seven
stock 220--580 MHz OPPs. GPUCC is built in; display and touch parameters
are unchanged. The marble tree was used as a reference, together with
this phone's stock sources and DT.

Two existing A7xx initialization faults required fixes:

* With the LLCC node disabled, slice lookup discarded the valid CX_MISC
  mapping. GMU resume then dereferenced ``ERR_PTR(-EINVAL)`` while reading
  TCM retention. A7xx now retains this mapping independently of LLCC and
  rejects actual mapping failures during probe.
* A730 has no IFPC-only register list. The power-up list builder now
  checks for that optional list and sets its length to zero when absent.

Firmware is taken from this phone's read-only ``super/vendor_a`` image.
Do not use firmware signed for a different device. Install the extracted
files as root::

  install -Dm644 /path/to/stock/firmware/a730_sqe.fw \
    /usr/lib/firmware/qcom/a730_sqe.fw
  install -Dm644 /path/to/stock/firmware/gmu_gen70000.bin \
    /usr/lib/firmware/qcom/gmu_gen70000.bin
  install -Dm644 /path/to/stock/firmware/a730_zap.elf \
    /usr/lib/firmware/qcom/sm7475/realme/gt-neo5-se/a730_zap.mbn
  sync

The last command deliberately installs the **stock .elf** under the DT's
monolithic ``.mbn`` filename. Its header and hash match the stock split
``.mdt/.b01/.b02`` image. The separate stock file named ``a730_zap.mbn``
has different authentication metadata and was rejected by PAS with -22.
The accepted ELF SHA256 is
``3daf6095cacd7eabfaa14b7be7ef0b89d3f9a1dc057ec5df80b417727330d5eb``.
No signature or firmware partition is modified; firmware is not included
in this repository.

Install ``mesa-utils`` and optionally ``vulkan-tools vulkan-freedreno``.
After configuring the existing software Plasma session, copy
``tools/boot/sm7475-arch/setup-plasma-mobile-gpu`` onto the phone and run it
as root. It checks that GBM/EGL reports FD725, adds a hardware session and
selects it for SDDM. It does not restart the running desktop. Use a timed
recovery before the first switch::

  systemd-run --unit=sm7475-gpu-desktop-rollback --on-active=180s \
    /usr/local/libexec/sm7475-restore-software-plasma
  systemctl stop sddm
  loginctl terminate-user alarm
  systemctl start sddm

Terminating the old graphical user session prevents a lingering KWin from
retaining the previous rendering environment. This logs out that user.
After verifying the screen, cancel the timer and retain graphical boot::

  systemctl stop sm7475-gpu-desktop-rollback.timer
  systemctl set-default graphical.target

Recovery over SSH/ACM is
``/usr/local/libexec/sm7475-restore-software-plasma``. The original software
session and Xfce recovery remain available.

Default tiled rendering is now validated; the hardware session clears
``FD_MESA_DEBUG`` and ``IR3_SHADER_DEBUG`` rather than forcing linear
allocations. The earlier corruption was observed in a boot where PAS
rejected the separate stock MBN and the accepted ELF was installed and
retried without rebooting. With the accepted ELF present from boot,
the same kernel and Mesa pass the original default-allocation gradient.
This also passes after another normal reboot with the workaround removed.
The evidence points to state left by the failed authentication/hot retry;
no particular residual register or hardware tiling defect has been proven.

If authentication has failed during the current boot, install the accepted
signed ELF, sync and reboot before testing hardware rendering. The setup
helper refuses a boot whose log contains the firmware initialization
error. An EGL renderer string or a small uniform-color test alone does not
establish correct rendering. Changing GMEM base, macrotile mode or shader
precision is not required by the successful default tests.

Hardware validation, 2026-10-21, with Mesa 26.2.5:

* Native Freedreno and Zink/Turnip pass the original 1024x1024
  coordinate-gradient readback, with shader caches disabled and no
  FD/IR3 debugging overrides. The test checks five clear colors and a
  grid of gradient samples at seven-pixel intervals with tolerance one.
* A coordinate-coded 1024x1024 CPU texture upload/readback matches all
  pixels with default allocations and with linear allocations. Sampling
  that texture into an explicitly linear render target also matches.
* KWin reports DRM/EGL, ``freedreno`` and ``FD725``. Its scanout buffer
  uses the QCOM compressed modifier ``0x500000000000001`` at 1240x2772.
  Desktop screenshots are clean with default allocations.
* Native Vulkan Wayland presentation through Turnip renders vkcube
  correctly in a captured frame, and the 1800-frame run exits normally.
  Turnip reports Adreno 725 and Vulkan 1.4.354. OpenGL 4.6 and OpenGL ES
  3.2 are exposed by the native driver.
* A normal ``systemctl reboot`` retains the default hardware desktop.
  Both native and Zink gradient comparisons pass again. GMU 4.0.7 starts
  without authentication errors, Oops or new GPU faults. Systemd is
  ``running`` with zero failed units; touch initializes automatically.
  No diagnostic module or preload override is used.

The two clean firmware boots are
``01e797a0-a645-46b6-a51e-358ee14cd058`` and
``5382b279-c629-4ac5-a3c4-472fdb97a6a4``. The installed kernel and matching
``out-gpu-reglist-fixed-20261021`` image trio are unchanged by this
userspace configuration correction. The pre-existing single early MDSS
fault remains with normal display. After the default-allocation reboot,
the user separately confirmed normal physical screen and touch while
checking the app drawer, swipes and an application. This confirmation
covers the default tiled/compressed session without ``notile``.

Evidence and firmware hashes are under ``archlinuxarm/gpu/``; the default
allocation retest is in its ``tiling/`` subdirectory, including
``reboot-api-readback.txt``, ``reboot-validation.txt`` and
``vulkan-active.png``. These tests do not establish Vulkan conformance,
arbitrary game compatibility or system suspend/resume. The verified
built-in touch image trio in ``out-touch-release-20261021`` remains the
display/touch rollback.

Additional GPU regression testing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A bounded stability run on 2026-10-21 used the same kernel, signed firmware
and default hardware session, without ``notile`` or shader overrides.
Boot ID was ``c6c3cb93-1617-46a8-a7f3-b06b07b01e54``. The run completed:

* All 33 glmark2 ES2 Wayland load scenes in 333 seconds and all 13 vkmark
  Wayland scenes in 130 seconds. These exercise textures, filtering,
  shading, buffer updates, terrain, shadows and presentation. Completion
  is a stability result, not a pixel-correctness assertion for every frame.
* Eighteen native Freedreno/Zink 1024x1024 gradient readbacks: six cycles
  per driver with idle gaps, followed by both drivers with devfreq bounds
  locked at each of 220, 364 and 580 MHz. All comparisons passed.
* GPU and GMU runtime status both sampled as suspended and later active;
  rendering continued without GPU resets or timeouts. The original
  ``simple_ondemand`` governor and 220--580 MHz bounds were restored.
* Over the 487-second telemetry interval, battery temperature was
  32.1--37.3 degrees Celsius. This is the BQ28Z610 battery sensor; no GPU
  temperature sensor was exposed. The test did not reach its 43-degree
  battery stop threshold.

The compositor resized the glmark2 Wayland window to 1239x2598 regardless
of the requested size. Do not compare its score to a standard 800x600
result. Short validation controls also overlapped part of the load run.
A vkmark screenshot showed a clean textured cube.

Pixel validation requires more care than accepting the process exit
status: glmark2 exits zero even when its reference comparisons fail.
Using Xwayland with an off-screen 800x600 target removed the resize issue.
The installed glmark2 2023.01 then produced these results:

============================ ======= ======= =======
Path                         Success Failure Unknown
============================ ======= ======= =======
Native desktop OpenGL        27      0       6
Native GLES                  21      6       6
Zink GLES                    21      6       6
llvmpipe GLES                27      0       6
Native GLES, highp control   27      0       6
============================ ======= ======= =======

The six GLES mismatches are one conditionals, two function and three loop
reference checks. Disabling the shader cache and testing
``IR3_SHADER_DEBUG=nofp16`` did not remove them. The highp control adds
``precision highp float;`` only to copies of the three corresponding
fragment shader data files; the installed package and normal session
remain unchanged. A command-line precision override was also tried but
did not alter the shaders generated by the validation suite, so it is
not evidence of a highp comparison.

The controls establish a precision-sensitive reference difference. They
do not establish a GLES specification violation or a completed compiler
fix. Retain this result when describing application compatibility; the
basic desktop and original gradient successes do not imply that every
shader reference test passes. Six scenes have no reference validation
and are reported as unknown, not passed. Full GL/Vulkan conformance and
arbitrary games have not been tested.

System suspend was not attempted: no RTC wake device is exposed and the
user reports that the power key does not work. Runtime autosuspend of the
GPU is distinct from whole-system suspend/resume. Fix and verify a wake
source before attempting that test. Detailed logs, the bounded runner,
telemetry and comparison controls are in ``archlinuxarm/gpu/stability/``.

After the load run, an agent-requested normal reboot produced boot ID
``dde053ec-1954-4a73-b0ff-694b0fe38030``. Native and Zink gradient readbacks
passed again without shader overrides or the shader cache. KWin resumed
automatically on FD725 with compressed scanout; systemd was running with
zero failed units. Touch initialized at 0.557 seconds. No GPU timeout,
authentication error or Oops was observed. The kernel, boot partitions
and normal GPU session settings were not changed by this test run.

Physical power and volume keys
------------------------------

This board's factory overlay places ``KEY_POWER`` and ``KEY_VOLUMEUP``
under PMK8350 ``pon_hlos@1300`` as ``pwrkey`` and ``resin``. They use
SPMI interrupts 0/0x13/7 and 0/0x13/6, respectively, with both edges.
Volume down is a separate ``gpio-keys`` input on PMIC GPIO6. The disabled
``vol_up`` GPIO node references that same GPIO6; enabling it would not
supply the missing physical volume-up key. Do not copy marble's resin
key code: that board uses it for volume down, while this phone uses
volume up.

The missing keys were caused by ``CONFIG_POWER_RESET_QCOM_PON=m`` with
no matching modules installed on the persistent Arch root. The PON
parent remained unbound and therefore never populated its key children,
even though ``CONFIG_INPUT_PM8941_PWRKEY=y`` was already enabled. Only
the independent volume-down device appeared in the input list.

Loading an unmodified qcom-pon module built against the running kernel
immediately registered ``pmic_pwrkey`` and ``pmic_resin``. Event capture
recorded 18 complete power press/release pairs, 18 volume-up pairs and
eight volume-down pairs, with no stuck key or repeat event. The desktop
power action was temporarily inhibited during the first capture; a
lack of screen response during that interval did not mean input was
missing. After restoring PowerDevil and removing the temporary inhibitor,
the user confirmed normal power-key screen off and on. Panel ID and
power status remained normal during those display cycles.

The release fragment now builds both the PON parent and its input driver
in. The merged configuration changes only ``POWER_RESET_QCOM_PON`` from
module to built-in. There is no new key driver or DT change. The existing
factory PM8998-compatible parent is supported by the upstream PON driver;
its PMK8350-compatible children select the Gen3 input implementation.
No reset reason mapping or reboot-to-bootloader support was added.

The matching ``out-keys-release-20261021`` boot/vendor_boot/dtbo images
passed AVB and payload checks. The DTB and all parsed vendor_boot payload
sections match the previously working GPU release byte for byte,
including the userdata bootstrap. The previous GPU image trio remains
the rollback. Evidence is in ``archlinuxarm/keys/``. Built-in release
startup and ordinary-reboot results must be recorded separately from
the manual module test above.

The built-in kernel is 6.18.0 #1, built at 22:52:01 CST on 2026-10-21.
On initial boot ``bb8923ad-5986-4c2f-a844-cd35baaf7378``, power and
volume-up inputs registered at 0.443 and 0.444 seconds. An agent-requested
ordinary reboot produced ``2db9cf14-77d9-47ac-b881-6a3cc8d909a4`` and the
two inputs registered again at 0.447 and 0.448 seconds. No manual module
load or userspace startup helper was needed; lsmod was empty. The power
key's wakeup attribute was enabled. Systemd was running with zero failed
units, S3910 initialized, and the native GPU gradient passed after reboot.
Input event numbering changes with the earlier PMIC input registration;
identify touchscreen and keys by device name/udev rather than a fixed
event number.

After the built-in reboot, event capture recorded two complete power
press/release pairs, four volume-up pairs and four volume-down pairs,
without repeats or missing releases. The user confirmed all three keys,
normal screen off/on, and touch after screen-on. This is a separate
confirmation from the earlier manual-module test. The finite capture
ended naturally; temporary desktop inhibitors are gone and PowerDevil
is restored. No diagnostic module is auto-loaded.

QCA6490 Wi-Fi bring-up
---------------------

The 2026-10-22 first-test images boot on the phone. PCIe enumerates the
17cb:1103 endpoint at 0000:01:00.0 over a Gen2 x1 link. ath11k identifies
WCN6855 hw2.1, chip ID 0x12, board ID 0xff and SoC ID 0x400c1211. The
distribution firmware starts and scanning finds both 2.4 and 5 GHz access
points. Post-root initialization survives an ordinary reboot, and WPA2
association, DHCP, DNS and HTTPS have succeeded on a 5 GHz network.
The HTTPS request explicitly binds the WLAN interface, with a wireless
source address, so USB sharing cannot account for that result. A weak
initial signal produced retries and disconnects; range and sustained
throughput are not established by this bring-up test. During a short
connected run, ten gateway pings had no loss; five HTTPS requests had one
eight-second connection timeout followed by four successes. A second
ordinary reboot automatically restored the saved network and the same
generated MAC address; WLAN DNS and HTTPS passed again. Systemd reported
no failed units and the display session remained active. Neither 2.4 GHz
association nor system suspend/resume has been tested.

The stock Senna DT describes QCA6490 on PCIe0, using the WCN6855 PCI ID
17cb:1103. The new board include describes the single-lane controller,
PCIe NoC, ITS MSI mapping and SMMU streams 0x1c00/0x1c01. It caps the link
at Gen2 and uses the stock PERST/CLKREQ/WAKE pins 94/95/96. The GCC consumes
the PHY pipe-clock output as in the upstream SM8450 topology.

The Cape PHY uses QSERDES v6 rather than the SM8450 v5 tuning. The new
SM8475 Gen3x1 PHY description was taken from the local marble reference,
then checked against this phone's stock ``qcom,phy-sequence``. All 79
address/value tuning pairs match; three additional stock writes are the
common power/reset/start controls handled by the PHY framework. Existing
compatibles are unchanged. The binding document and selected PHY DTB
node pass dt-schema validation, and the PHY patch and board include pass
checkpatch without errors or warnings.

The WCN6855 power sequencer uses WLAN/BT/SWCTRL/XO pins 80/81/82/204 and
RPMh supplies S10B, S11B, S12B, S1C and S2E. Voltage constraints follow this
phone's CNSS requested ranges, rather than inactive PMIC reset defaults.
The shared antenna switch on L7E is held at 2.8 V during bring-up. The PHY
reuses the already validated L5B 0.88 V and L10C 1.2 V supplies. Bluetooth
operation is not enabled or validated by this Wi-Fi candidate.

PHY, power sequencing, PCI power control, ath11k PCI, MHI, cfg80211,
mac80211 and rfkill are built in because the Arch root has no matching
6.18 module tree. The existing display, GPU, touch and key configuration
is retained. ``out-wifi-20261022`` contains the matching first-test image
trio; AVB, SHA256, embedded Image and padded selected DTB checks passed.
Vendor ramdisk, table, bootconfig and userdata bootstrap remain identical
to the key release. DTBO content is unchanged apart from re-signing.

The factory overlay has obsolete symbol exports that standard libfdt
rejects. For offline checks only, those exports were removed from a copy;
the resulting merge retains the new PCIe, PMU and GCC clock definitions.
The actual flash input retains the original factory entries. Hardware
enumeration was verified separately after flashing the matching trio.

Arch already has the distribution's WCN6855 hw2.0/hw2.1 firmware. The
phone's own ``modem_a/image/qca6490`` files were also copied read-only to
``/root/sm7475-wifi-stock`` for comparison, without replacing the installed
ath11k firmware. The distribution board-2.bin contains an exact entry for
PCI subsystem 17cb:0108, chip ID 18 and board ID 255, which is the identity
observed on this phone. Its board payload is not identical to the archived
stock files. This test does not establish stock-equivalent RF calibration
or antenna performance. Firmware and credentials must stay out of Git.

The built-in driver probes before switch_root, when amss.bin is not yet
available. Run ``tools/boot/sm7475-arch/setup-wifi`` as root on the phone
after installing ``linux-firmware-atheros``, ``wireless-regdb``, ``iw``,
``wpa_supplicant`` and ``networkmanager``. It installs a post-root oneshot
service before NetworkManager. The service retries only the unbound
17cb:1103 endpoint and waits for its wireless PHY; an already bound
adapter is left attached. It also reloads the signed regulatory database
that cfg80211 could not access before root. No firmware is embedded in
the small bootstrap ramdisk.

The installer preserves USB as unmanaged by NetworkManager so networkd
continues to provide SSH access. It enables NetworkManager; select the
network and enter its password in Plasma settings. Credentials stay on
the phone and must not enter source or diagnostic logs. The distribution
board data exposes a shared 00:03:7f default MAC address; the installer
selects NetworkManager stable-ssid addresses for ath11k connections to
avoid using that shared address. The generated local address persists
for the same network on this installation. See the NetworkManager
``802-11-wireless.cloned-mac-address`` documentation for the policy.
Existing profiles with an explicit address retain their own setting.

Evidence, image hashes and the known-good key/GPU rollback hashes are in
``archlinuxarm/wifi/``. Flash only the matching a-slot image trio, then
reset/check slot retry state. Preserve userdata. The final verified boot
ID is ``46983792-67cf-4fe0-9ca3-b8cb786ed951``; evidence includes
``final-reboot-validation.json``, ``firmware-selection.json``,
``wlan-stability.jsonl`` and ``gateway-check.txt``. Early amss.bin errors
remain expected with this bootstrap; the post-root service must finish
successfully and register the PHY. Old display-stream SMMU faults before
MDSS reset remain observable; no Wi-Fi stream 0x1c01 fault was observed.

Kernel stability audit (2026-10-22)
----------------------------------

The Wi-Fi kernel was inspected without reflashing or changing driver
parameters. Boot ID ``46983792-67cf-4fe0-9ca3-b8cb786ed951`` remained
unchanged throughout. No kernel Oops/panic, RCU stall, bad-page report,
ext4 error or runtime lockup was observed in the captured log. Both
pstore locations were empty. This is a limited bring-up check, not a
long-duration stability qualification.

Outstanding kernel integration issues, in priority order:

* CPU power and thermal management is incomplete. The running config has
  ``CONFIG_ARM_QCOM_CPUFREQ_HW`` disabled and no cpufreq policies or CPU0
  cpuidle states are registered. TSENS is built in, but the live tree has
  no matching TSENS node; the only thermal zone is the BQ28Z610 battery.
  CPU/GPU die temperatures and kernel CPU cooling have not been verified.
  Sustained multicore stress was therefore not attempted. Battery
  temperature must not be presented as a measurement of CPU temperature.
* DISPCC emits ``disp_cc_mdss_mdp_clk_src: rcg didn't update its
  configuration`` from ``clk_rcg2_shared_init`` during registration.
  Display operation later succeeds, but the early update timeout remains
  unresolved. Do not merely suppress the WARN or change the previously
  validated MDSS clock-before-reset order to hide it.
* SPMI PMIC probes fail with -EIO at SIDs 5 and 9. The live tree also
  contains two enabled children for each of SIDs 8 and 9 under the same
  arbiter (pm8010 and pm8010i/j names), causing -EEXIST. The duplicate DT
  descriptions are confirmed; the physical cause of each failed access
  still requires comparison with the actual board wiring.
* Ten early display-stream SMMU faults (0x2800/0x2c00) occur before MDSS
  reset in this boot. None recurred during the checks. They are distinct
  from the Wi-Fi endpoint stream 0x1c01.
* Wi-Fi was deauthenticated by the AP with reason 6
  (CLASS2_FRAME_FROM_NONAUTH_STA) during the bounded checks, then
  reauthenticated and associated in less than a second. No ath11k
  firmware crash was logged. Driver, AP and RF causes are not separated
  by this event; connectivity still needs longer testing.

The taint value is 516, consisting of CPU_OUT_OF_SPEC (4) and WARN (512),
not an Oops taint. The CPU feature log differs by bit 24 of MMFR1,
corresponding to SpecSEI on the heterogeneous cores; this tree marks that
field STRICT/HIGHER_SAFE. This is not evidence by itself of damaged CPUs
or memory corruption. Both the feature variation and the DISPCC/SPMI
warnings also appear in the saved pre-Wi-Fi key-release logs.

Two additional problems are outside kernel crash handling. Coredump
records from the preceding boot show two plasmashell SIGSEGVs at
21:14/21:15, with the inspected stack in
``NetworkManager::WirelessSetting::mode`` and ``libplasmanm_internal``.
No coredump belongs to the audited boot. The user document portal is
failed because /dev/fuse is absent: FUSE is configured as a module, but
only a distribution 7.2.11 module tree is installed for the running 6.18
kernel. Provide a matching module set or build the required support in;
do not load modules from the other kernel. System services have no failed
units, which does not include this failed user service.

The finite checks passed: a brief SHA256 calculation pinned to each of
CPUs 0-7; one 64 MiB memtester iteration pinned to CPU0 (about 41 seconds);
a 64 MiB temporary ext4 file written and read with aligned O_DIRECT and
matching SHA256; and native Freedreno plus Zink/Turnip 1024-square GPU
readbacks. The temporary data file was removed. A further read-only
4 MiB direct read of userdata did not increase SCSI error counters;
existing nonzero counters alone are not a disk-failure diagnosis.
Battery temperature during the checks was 32.4-32.6 C. No new WARN or
memory/storage/GPU fault appeared; taint remained 516. The new kernel
messages were the Wi-Fi deauthentication/reassociation described above.
GPU and GMU later both returned to runtime-suspended state.

Evidence is under ``archlinuxarm/kernel-audit-20261022/``: running config,
full kernel and user logs, live DT inventory, coredump stack, before/after
kernel log, finite-test script/results and direct-I/O counter comparison.
Soft-lockup/hung-task detectors and KASAN/KFENCE are disabled in this
build, so absence of their reports is not proof that latent defects do
not exist. System suspend, long full-load runs, RF qualification and
charging/thermal protection remain unverified. Prioritize CPU frequency
and die thermal/cooling integration before expanding sustained stress.

CPU frequency, thermal, clock and FUSE repair
--------------------------------------------

The first repair trio, ``out-stability-20261022``, booted successfully as
``496f7f44-d157-4c96-afa5-ef598c37d68c``. The user confirmed normal display
and touch. CPU policies, die thermal zones, FUSE and the document portal
are registered; the MDP clock warning and duplicate PMIC registration
errors disappeared. The follow-up ``out-stability-release-20261022`` uses
the same Image and additionally disables unpopulated PMIC nodes. Its
hardware boot and ordinary restart checks are pending.

The board include uses EPSS at 0x17d91000/0x17d92000/0x17d93000 and TSENS
TM/SROT windows 0xc263000/0xc222000 and 0xc265000/0xc223000. Addresses,
interrupts, frequency domains and sensor wiring were compared with this
phone's factory tree. EPSS and TSENS use the shared SM8450-compatible IP
layouts. Private mainline labels keep factory overlays away from these
controller definitions. No hand-written voltage or frequency table is
installed: the cpufreq driver reads the firmware-programmed hardware LUT.

CPUs 0-3, 4-6 and 7 use domains 0, 1 and 2. Fifteen thermal zones cover
four little cores, the six middle-core sensors, three prime-core sensors
and two GPU sensors. Passive and critical thresholds follow the upstream
SM8450 defaults: CPU passive 90 C (2 C hysteresis), GPU passive 85 C
(1 C hysteresis), and critical 110 C (1 C hysteresis).
Cooling maps bind CPU sensors to their frequency domain and GPU sensors
to the existing devfreq cooling device. Polling complements TSENS IRQs.
Live TSENS readings are plausible and vary with load. All three CPU
policies were forced briefly to their lowest and middle LUT entries,
then restored. Register-reported frequencies and SHA256 timings changed
accordingly. The LUT ranges are 300-1804.8 MHz (CPUs 0-3),
633.6-2496 MHz (4-6), and 787.2-2918.4 MHz (7).

Each CPU-domain cooling map and the GPU cooling map was tested with a
short software temperature emulation below the critical threshold.
Cooling state changed 0 to 1, then back to 0 after clearing emulation.
All emulated temperatures were cleared and frequency limits restored.
This checks the control path, not physical high-temperature protection
or factory-equivalent sensor calibration.

FUSE is built in so the document portal can access /dev/fuse without a
matching module installation. The config delta from the Wi-Fi release is
only ARM_QCOM_CPUFREQ_HW disabled to y and FUSE_FS m to y. Required thermal
and cooling options were already enabled. The board predeclares the two
empty factory pm8010i@8/pm8010j@9 aliases as disabled, retaining the full
pm8010@8/@9 descriptions. Their disabled state survives the offline
factory overlay merge. A stock SoCinfo module built against this exact kernel was loaded only
to read the firmware SMEM inventory, then unloaded. The inventory lists
PMK8350, PM8350, PM8350C, PM8350B, PMR735A, PM8450 and one PM8010.
Together with the responding SID8 PM8010 and failed SID5/SID9 probes,
this identifies the unpopulated PMR735B and second PM8010 descriptions.
The follow-up release marks pmr735b@5 and pm8010@9 disabled rather than
hiding failures in the SPMI driver. No diagnostic module is auto-loaded.

The full clean build, image AVB/payload checks, source/cache comparison,
selected cpufreq/TSENS/thermal-zone schemas and thermal include checkpatch
passed. The TSENS schema check requires its thermal-sensor and nvmem
schema dependencies; an isolated invocation without them is not a valid
failure of the board description. Offline merging still sanitizes only
obsolete symbol exports in a copy of the factory overlay. Flash entries
are unchanged. Vendor header, ramdisk, table, bootconfig and userdata
bootstrap match the working Wi-Fi release byte for byte. Panel, GPU, touch, keys and command line remain unchanged. The
Ukee-specific MDP clock source now uses the existing shared no-init-park
operations, retaining the boot parent during registration while keeping
normal rate/enable/disable handling. This follows the same approach as
upstream dispcc-eliza commit 2ef00630c5c0, with scope restricted to Ukee.
The MDP update warning disappeared on the first repair boot and display
operation was confirmed. The MDSS clock-before-reset order is unchanged.

The working ``out-wifi-20261022`` trio has been rehashed as rollback.
Preserve userdata and flash only the matching candidate trio. Evidence is
under ``archlinuxarm/stability-fix-20261022/``. One pre-reset SMMU display-stream fault and the CPU feature taint remain.
The prior Plasma network-component crashes are separate userspace work.
The first repair boot also passed one 64 MiB memtester iteration, a
64 MiB O_DIRECT ext4 round trip and native/Zink GPU readbacks in about
40 seconds. Die temperature peaked at 49.5 C, battery at 33.7 C, and no
new kernel message appeared during that run. This is still a bounded
check rather than long-load or whole-system suspend qualification.
