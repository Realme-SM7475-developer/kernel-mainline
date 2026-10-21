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
