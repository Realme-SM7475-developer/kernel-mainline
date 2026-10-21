#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build an opt-in Arch bootstrap using a signed AArch64 rootfs."""
import argparse
import gzip
import hashlib
import json
import posixpath
import re
import stat
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

SIGNER = "68B3537F39A313B3E574D06777193F152BDBE6A6"
HERE = Path(__file__).resolve().parent


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def newc(entries):
    out = bytearray()
    for ino, (name, mode, data) in enumerate(
            entries + [("TRAILER!!!", 0, b"")], 1):
        encoded = name.encode() + b"\0"
        fields = [ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(encoded), 0]
        out += b"070701" + b"".join(b"%08X" % field for field in fields)
        out += encoded
        out += b"\0" * (-len(out) % 4)
        out += data
        out += b"\0" * (-len(out) % 4)
    out += b"\0" * (-len(out) % 512)
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("rootfs", "signature", "signing-key", "busybox", "ssh-public-key",
                   "output-dir"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--rootfs-url", default=(
        "http://192.168.77.1:8080/ArchLinuxARM-aarch64-latest.tar.gz"))
    parser.add_argument("--root-partuuid", default="",
                        help="Automatically boot an installed userdata root with this GPT UUID")
    args = parser.parse_args()
    if args.root_partuuid and not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", args.root_partuuid):
        parser.error("root-partuuid must be a lowercase GPT UUID")
    key = args.ssh_public_key.read_text().strip()
    if not key.startswith("ssh-ed25519 ") or "\n" in key:
        parser.error("Supply a single Ed25519 public key, never a private key")
    if not re.fullmatch(r"http://192\.168\.77\.1:8080/[A-Za-z0-9_.-]+", args.rootfs_url):
        parser.error("The bootstrap server must be on the dedicated USB link")

    entries = {}

    def add(name, mode, data=b""):
        for parent in reversed(Path(name).parents):
            if str(parent) != ".":
                entries.setdefault(str(parent), (stat.S_IFDIR | 0o755, b""))
        entries[name] = (mode, data)

    with tempfile.TemporaryDirectory(prefix="sm7475-arch-") as work:
        work = Path(work)
        gpg = work / "gnupg"
        gpg.mkdir(mode=0o700)
        command = ["gpg", "--homedir", str(gpg), "--batch"]
        subprocess.run(command + ["--import", str(args.signing_key)], check=True,
                       capture_output=True)
        verified = subprocess.run(command + ["--status-fd", "1", "--verify",
                                  str(args.signature), str(args.rootfs)],
                                  capture_output=True, text=True, check=True)
        if not re.search(r"^\[GNUPG:\] VALIDSIG " + SIGNER + r" ",
                         verified.stdout, re.M):
            raise RuntimeError("Rootfs signature is not from the published ARM build key")

        candidates = {}
        unpacked_bytes = 0
        with tarfile.open(args.rootfs, "r|gz") as archive:
            for member in archive:
                name = member.name.removeprefix("./")
                if member.isfile():
                    unpacked_bytes += member.size
                if (name != "usr/bin/bsdtar" and not
                        re.fullmatch(r"usr/lib/[^/]+\.so(?:\.[^/]+)?", name)):
                    continue
                candidates[name] = member
                if member.isfile():
                    target = work / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
        if unpacked_bytes > 3800 * 1024 * 1024:
            raise RuntimeError("Rootfs exceeds the RAM-root size budget")

        selected = set()

        def include(name):
            if name in selected:
                return
            selected.add(name)
            member = candidates[name]
            if member.issym() or member.islnk():
                target = (member.linkname.lstrip("/") if member.linkname.startswith("/")
                          or member.islnk() else posixpath.join(
                              posixpath.dirname(name), member.linkname))
                target = posixpath.normpath(target)
                include(target)
                if member.issym():
                    add("bootstrap/" + name, stat.S_IFLNK | 0o777,
                        member.linkname.encode())
                else:
                    add("bootstrap/" + name, stat.S_IFREG | member.mode,
                        (work / target).read_bytes())
                return
            dynamic = subprocess.check_output(["readelf", "-d", "--wide", str(work / name)],
                                              text=True)
            for dependency in re.findall(r"\(NEEDED\).*?\[([^]]+)\]", dynamic):
                include("usr/lib/" + dependency)
            add("bootstrap/" + name, stat.S_IFREG | member.mode, (work / name).read_bytes())

        include("usr/bin/bsdtar")
        include("usr/lib/ld-linux-aarch64.so.1")

    add("bin/busybox", stat.S_IFREG | 0o755, args.busybox.read_bytes())
    for source, target in (("init", "init"), ("usb-network.sh", "bin/arch-usb-network"),
                           ("arch-prepare", "bin/arch-prepare"), ("arch-boot", "bin/arch-boot"),
                           ("arch-mount-userdata", "bin/arch-mount-userdata")):
        subprocess.run(["sh", "-n", str(HERE / source)], check=True)
        add(target, stat.S_IFREG | 0o755, (HERE / source).read_bytes())
    digest = sha256(args.rootfs)
    config = (f"ROOTFS_URL='{args.rootfs_url}'\nROOTFS_SHA256='{digest}'\n"
              f"BUILD_EPOCH={int(time.time())}\nROOT_PARTUUID='{args.root_partuuid}'\n")
    add("etc/arch-bootstrap.conf", stat.S_IFREG | 0o644, config.encode())
    add("etc/arch-authorized-key", stat.S_IFREG | 0o600, (key + "\n").encode())
    for directory in ("dev", "proc", "sys", "run", "newroot", "tmp"):
        add(directory, stat.S_IFDIR | (0o1777 if directory == "tmp" else 0o755))
    ordered = [(name, mode, data) for name, (mode, data) in sorted(
        entries.items(), key=lambda entry: (entry[0].count("/"), entry[0]))]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "arch-initramfs.cpio.gz"
    output.write_bytes(gzip.compress(newc(ordered), compresslevel=9, mtime=0))
    if output.stat().st_size > 22589876:
        raise RuntimeError("Bootstrap exceeds the stock vendor ramdisk region")
    manifest = {"rootfs_sha256": digest, "rootfs_unpacked_bytes": unpacked_bytes,
                "rootfs_signer": SIGNER, "initramfs_sha256": sha256(output),
                "bootstrap_files": sorted(selected), "rootfs_url": args.rootfs_url,
                "root_partuuid": args.root_partuuid,
                "root_mode": "userdata" if args.root_partuuid else "ram"}
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
