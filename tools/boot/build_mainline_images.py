#!/usr/bin/env python3
"""Build Android v4 boot and vendor_boot images for the SM7475 board.

The phone uses the standard Android v4 split layout: boot.img contains the
kernel and generic ramdisk, while vendor_boot.img contains the vendor ramdisk,
ramdisk table, bootconfig, and DTB. This tool keeps those sections from the
stock images and replaces only the requested kernel, generic ramdisk, and DTB.
It can also preserve the stock signed vendor_boot byte-for-byte.

Replacing the vendor_boot DTB area invalidates the OEM AVB signature, so a
replacement is stamped with a self-signed test footer instead (the bootloader
accepts a structurally valid footer; see README, "秒回 fastboot" section).
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile


PAGE = 4096
BOOT_HEADER = 1584
VENDOR_HEADER = 2128
ANDROID = b"ANDROID!"
VENDOR = b"VNDRBOOT"


def pages(size):
    return (size + PAGE - 1) // PAGE


def padded(data):
    return data + b"\0" * (pages(len(data)) * PAGE - len(data))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def section(data, offset, size):
    end = offset + size
    if end > len(data):
        raise ValueError(f"section exceeds input: {offset:#x}+{size:#x}")
    return data[offset:end]


def valid_dtb(data):
    return len(data) >= 40 and struct.unpack_from(">II", data) == (0xD00DFEED, len(data))


FDT_MAGIC = b"\xd0\x0d\xfe\xed"


def fdt_root_props(blob):
    """Collect the root node's properties from a raw FDT blob."""
    off_struct = struct.unpack_from(">I", blob, 8)[0]
    off_strings = struct.unpack_from(">I", blob, 12)[0]
    size_struct = struct.unpack_from(">I", blob, 36)[0]
    props = {}
    i, depth = off_struct, 0
    end = off_struct + size_struct
    while i < end:
        token = struct.unpack_from(">I", blob, i)[0]
        i += 4
        if token == 1:                          # FDT_BEGIN_NODE
            i = blob.index(b"\0", i) + 1
            if depth == 0:                      # root name is empty + padding
                i = (i + 3) & ~3
            depth += 1
        elif token == 2:                        # FDT_END_NODE
            depth -= 1
            if depth == 0:
                break
        elif token == 3:                        # FDT_PROP
            length, nameoff = struct.unpack_from(">II", blob, i)
            i += 8
            stop = off_strings + nameoff
            props[blob[stop:blob.index(b"\0", stop)]] = blob[i:i + length]
            i = (i + length + 3) & ~3
        elif token == 4:                        # FDT_NOP
            pass
        else:                                   # FDT_END, or garbage
            break
    return props


def fdt_root_u32(blob, name):
    value = fdt_root_props(blob).get(name)
    if not value:
        return None
    return [struct.unpack_from(">I", value, k)[0]
            for k in range(0, len(value), 4)]


def split_dtbs(region):
    """Locate each FDT in a concatenated blob as (offset, totalsize)."""
    found = []
    start = 0
    while True:
        offset = region.find(FDT_MAGIC, start)
        if offset < 0 or offset + 40 > len(region):
            return found
        found.append((offset, struct.unpack_from(">I", region, offset + 4)[0]))
        start = offset + 4


def replace_matching_dtb(region, dtb):
    """Swap only the DTB slot whose qcom,msm-id matches ours.

    The stock vendor_boot DTB area is not one blob: it starts with a small
    opaque prefix (7752 bytes here, holding a vendor ELF) followed by several
    concatenated DTBs - slot0 msm-id 0x21c, slot2 msm-id 0x24f - and the
    bootloader picks a slot by msm-id.  Overwriting the whole area with a
    single FDT, which is what this tool used to do, discards the prefix and
    every slot the board might have needed.  Keep all of that byte-for-byte
    and rewrite only our own slot.
    """
    mine = fdt_root_u32(dtb, b"qcom,msm-id")
    if not mine:
        raise ValueError("replacement DTB has no qcom,msm-id")
    slots = split_dtbs(region)
    for index, (offset, size) in enumerate(slots):
        if fdt_root_u32(region[offset:offset + size], b"qcom,msm-id") == mine:
            end = slots[index + 1][0] if index + 1 < len(slots) else len(region)
            return bytes(region[:offset]) + dtb + bytes(region[end:])
    raise ValueError(f"no stock DTB slot matches msm-id {mine}")


def stock_boot_layout(data):
    if len(data) < PAGE or data[:8] != ANDROID:
        raise ValueError("boot input is not an Android image")
    version = struct.unpack_from("<I", data, 40)[0]
    if version != 4 or struct.unpack_from("<I", data, 20)[0] != BOOT_HEADER:
        raise ValueError("boot input must use Android boot header v4")
    kernel_size, ramdisk_size, os_value = struct.unpack_from("<3I", data, 8)
    kernel = section(data, PAGE, kernel_size)
    ramdisk = section(data, PAGE + pages(kernel_size) * PAGE, ramdisk_size)
    cmdline = data[44:1580].split(b"\0", 1)[0].decode("ascii")
    return kernel, ramdisk, os_value, cmdline


def stock_vendor_layout(data):
    if len(data) < PAGE or data[:8] != VENDOR:
        raise ValueError("vendor_boot input is not an Android image")
    version, page_size = struct.unpack_from("<II", data, 8)
    if version != 4 or page_size != PAGE:
        raise ValueError("vendor_boot input must use v4 and 4096-byte pages")
    if struct.unpack_from("<I", data, 2096)[0] != VENDOR_HEADER:
        raise ValueError("unexpected vendor_boot header size")
    ramdisk_size = struct.unpack_from("<I", data, 24)[0]
    dtb_size = struct.unpack_from("<I", data, 2100)[0]
    table_size = struct.unpack_from("<I", data, 2112)[0]
    table_entries = struct.unpack_from("<I", data, 2116)[0]
    table_entry_size = struct.unpack_from("<I", data, 2120)[0]
    bootconfig_size = struct.unpack_from("<I", data, 2124)[0]
    if table_entry_size != 108 or table_size != table_entries * table_entry_size:
        raise ValueError("unsupported vendor ramdisk table")
    ramdisk_off = PAGE
    dtb_off = ramdisk_off + pages(ramdisk_size) * PAGE
    table_off = dtb_off + pages(dtb_size) * PAGE
    bootconfig_off = table_off + pages(table_size) * PAGE
    ramdisk = section(data, ramdisk_off, ramdisk_size)
    dtb = section(data, dtb_off, dtb_size)
    table = section(data, table_off, table_size)
    bootconfig = section(data, bootconfig_off, bootconfig_size)
    return bytearray(data[:PAGE]), ramdisk, dtb, table, bootconfig


def build_boot(mkbootimg, base_boot, kernel, ramdisk, cmdline, output):
    _, _, os_value, base_cmdline = stock_boot_layout(base_boot)
    if not cmdline:
        cmdline = base_cmdline
    # A v4 boot image may intentionally have an empty cmdline when the
    # vendor_boot bootconfig supplies it.  Do not invent a command line just
    # to satisfy the packer; callers can pass --cmdline for diagnostics.
    os_version = os_value >> 11
    os_version = f"{os_version >> 14}.{(os_version >> 7) & 127}.{os_version & 127}"
    patch = os_value & 2047
    patch = f"{2000 + (patch >> 4):04d}-{patch & 15:02d}"
    with tempfile.TemporaryDirectory(prefix="mainline-boot-") as temp_name:
        temp = Path(temp_name)
        kernel_file = temp / "kernel"
        ramdisk_file = temp / "ramdisk"
        packed = temp / "boot.img"
        kernel_file.write_bytes(kernel)
        ramdisk_file.write_bytes(ramdisk)
        subprocess.run([
            sys.executable, str(mkbootimg), "--header_version", "4",
            "--kernel", str(kernel_file), "--ramdisk", str(ramdisk_file),
            "--cmdline", cmdline, "--os_version", os_version,
            "--os_patch_level", patch, "--output", str(packed),
        ], check=True)
        result = packed.read_bytes()
    if result[:8] != ANDROID or struct.unpack_from("<I", result, 40)[0] != 4:
        raise ValueError("mkbootimg did not produce a v4 boot image")
    return result, cmdline


def build_vendor(base_vendor, dtb):
    header, ramdisk, old_dtb, table, bootconfig = stock_vendor_layout(base_vendor)
    if not valid_dtb(dtb):
        raise ValueError("DTB must contain exactly one complete FDT")
    region = replace_matching_dtb(old_dtb, dtb)
    struct.pack_into("<I", header, 2100, len(region))
    result = bytes(header) + padded(ramdisk) + padded(region) + padded(table) + padded(bootconfig)
    if len(result) > len(base_vendor):
        raise ValueError("replacement vendor_boot exceeds the input partition")
    return result


def publish(data, output, partition_size):
    if partition_size and len(data) > partition_size:
        raise ValueError(f"{output.name} exceeds partition size")
    if partition_size:
        data += b"\0" * (partition_size - len(data))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return data


def copy_payload(source, destination):
    """Copy a payload without failing when the input already is in output-dir."""
    if source.resolve() != destination.resolve():
        shutil.copyfile(source, destination)


def add_avb_footer(avbtool, image, partition_name, partition_size, key,
                   algorithm):
    """Add a structurally valid hash footer using an explicitly supplied key."""
    with tempfile.TemporaryDirectory(prefix="mainline-avb-") as temp_name:
        path = Path(temp_name) / f"{partition_name}.img"
        path.write_bytes(image)
        subprocess.run([
            str(avbtool), "add_hash_footer", "--image", str(path),
            "--partition_name", partition_name,
            "--partition_size", str(partition_size),
            "--algorithm", algorithm, "--key", str(key),
        ], check=True)
        return path.read_bytes()


def repack_with_magiskboot(magiskboot, base_image, kernel, ramdisk, dtb,
                           output, vendor):
    """Replace payloads while retaining the stock v4 header and AVB footer."""
    with tempfile.TemporaryDirectory(prefix="mainline-magiskboot-") as temp_name:
        temp = Path(temp_name)
        unpack_dir = temp / ("vendor" if vendor else "boot")
        unpack_dir.mkdir()
        template = unpack_dir / "template.img"
        template.write_bytes(base_image)
        unpack = subprocess.run([
            str(magiskboot), "unpack", str(template),
        ], cwd=unpack_dir, capture_output=True, text=True)
        if unpack.returncode not in (0, 3):
            raise RuntimeError(unpack.stderr or unpack.stdout)
        (unpack_dir / ("dtb" if vendor else "kernel")).write_bytes(
            dtb if vendor else kernel
        )
        if not vendor:
            (unpack_dir / "ramdisk.cpio").write_bytes(ramdisk)
        packed = temp / output.name
        subprocess.run([
            str(magiskboot), "repack", str(template), str(packed),
        ], cwd=unpack_dir, check=True)
        result = packed.read_bytes()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mkbootimg", type=Path,
                        help="AOSP mkbootimg.py for a newly constructed v4 boot image")
    parser.add_argument("--base-boot", type=Path, required=True)
    parser.add_argument("--base-vendor-boot", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--kernel-release", required=True)
    parser.add_argument("--ramdisk", type=Path, required=True)
    parser.add_argument("--dtb", type=Path, required=True)
    parser.add_argument("--dtbo", type=Path, required=True)
    parser.add_argument(
        "--dtbo-index", type=int, default=None,
        help="check this stock DTBO entry's external references before publishing",
    )
    parser.add_argument(
        "--preserve-vendor-boot", action="store_true",
        help="copy the base vendor_boot unchanged instead of replacing its DTB",
    )
    parser.add_argument(
        "--allow-unsigned-vendor-boot", action="store_true",
        help="explicitly allow a replacement vendor_boot without an AVB footer",
    )
    parser.add_argument(
        "--allow-unsigned-boot", action="store_true",
        help="explicitly allow a replacement boot.img without an AVB footer",
    )
    parser.add_argument("--avbtool", type=Path,
                        help="avbtool used when --boot-avb-key is supplied")
    parser.add_argument("--boot-avb-key", type=Path,
                        help="private key for a test/OEM boot AVB footer")
    parser.add_argument("--vendor-avb-key", type=Path,
                        help="private key for a replacement vendor_boot AVB footer")
    parser.add_argument(
        "--magiskboot", type=Path,
        help="magiskboot used to retain the stock v4 header/footer while replacing payloads",
    )
    parser.add_argument(
        "--preserve-stock-avb", action="store_true",
        help="repack both images with magiskboot and retain the stock AVB footer/key",
    )
    parser.add_argument(
        "--preserve-stock-boot-avb", action="store_true",
        help="repack boot.img with magiskboot and retain its stock AVB footer; keep vendor_boot byte-for-byte",
    )
    parser.add_argument("--boot-avb-algorithm", default="SHA256_RSA4096")
    project_root = Path(__file__).resolve().parents[3]
    parser.add_argument(
        "--output-dir", type=Path, default=project_root / "test",
        help="output directory (default: project-root/test; prior images there are replaced)",
    )
    parser.add_argument("--cmdline", default="")
    args = parser.parse_args()
    inputs = [args.mkbootimg, args.base_boot, args.base_vendor_boot,
              args.kernel, args.config, args.ramdisk, args.dtb, args.dtbo]
    boot_base = args.base_boot.read_bytes()
    vendor_base = args.base_vendor_boot.read_bytes()
    kernel = args.kernel.read_bytes()
    config = args.config.read_bytes()
    ramdisk = args.ramdisk.read_bytes()
    dtb = args.dtb.read_bytes()
    dtbo = args.dtbo.read_bytes()
    if args.preserve_stock_avb and args.preserve_stock_boot_avb:
        parser.error("--preserve-stock-avb and --preserve-stock-boot-avb are mutually exclusive")
    if not args.preserve_stock_avb and not args.preserve_stock_boot_avb \
            and not args.boot_avb_key and not args.allow_unsigned_boot:
        parser.error(
            "replacing boot.img removes its AVB footer; use --boot-avb-key "
            "or explicitly pass --allow-unsigned-boot"
        )
    if not args.preserve_stock_avb and not args.preserve_stock_boot_avb \
            and not args.preserve_vendor_boot \
            and not args.allow_unsigned_vendor_boot \
            and not args.vendor_avb_key:
        parser.error(
            "replacing vendor_boot removes its AVB footer; use "
            "--preserve-vendor-boot, --vendor-avb-key, or explicitly pass "
            "--allow-unsigned-vendor-boot"
        )
    if (args.preserve_stock_avb or args.preserve_stock_boot_avb) and not args.magiskboot:
        parser.error("--magiskboot is required when preserving a stock AVB footer")
    if args.dtbo_index is not None:
        checker = Path(__file__).with_name("check_dtbo_refs.py")
        subprocess.run([
            sys.executable, str(checker), "--dtb", str(args.dtb),
            "--stock-dtbo", str(args.dtbo), "--index", str(args.dtbo_index),
        ], check=True)
    if args.preserve_stock_avb:
        boot = repack_with_magiskboot(
            args.magiskboot, boot_base, kernel, ramdisk, dtb,
            args.output_dir / "boot.img", vendor=False,
        )
        vendor = repack_with_magiskboot(
            args.magiskboot, vendor_base, kernel, ramdisk, dtb,
            args.output_dir / "vendor_boot.img", vendor=True,
        )
        cmdline = args.cmdline
    elif args.preserve_stock_boot_avb:
        boot = repack_with_magiskboot(
            args.magiskboot, boot_base, kernel, ramdisk, dtb,
            args.output_dir / "boot.img", vendor=False,
        )
        vendor = vendor_base
        cmdline = args.cmdline
    else:
        boot, cmdline = build_boot(args.mkbootimg, boot_base, kernel, ramdisk,
                                   args.cmdline, args.output_dir / "boot.img")
        vendor = vendor_base if args.preserve_vendor_boot else build_vendor(vendor_base, dtb)
    if args.boot_avb_key and not args.preserve_stock_avb:
        if not args.avbtool:
            parser.error("--avbtool is required with --boot-avb-key")
        boot = add_avb_footer(args.avbtool, boot, "boot", len(boot_base),
                              args.boot_avb_key, args.boot_avb_algorithm)
    if args.vendor_avb_key and not args.preserve_stock_avb:
        if not args.avbtool:
            parser.error("--avbtool is required with --vendor-avb-key")
        if args.preserve_vendor_boot:
            parser.error("--vendor-avb-key cannot be used with --preserve-vendor-boot")
        vendor = add_avb_footer(args.avbtool, vendor, "vendor_boot",
                                len(vendor_base), args.vendor_avb_key,
                                args.boot_avb_algorithm)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for old_image in args.output_dir.glob("*.img"):
        old_image.unlink()
    for old_checksum in args.output_dir.glob("*.img.sha256"):
        old_checksum.unlink()
    for old_metadata in ("manifest.json", "payloads.sha256"):
        (args.output_dir / old_metadata).unlink(missing_ok=True)
    boot_path = args.output_dir / "boot.img"
    vendor_path = args.output_dir / "vendor_boot.img"
    boot = publish(boot, boot_path, len(boot_base))
    vendor = publish(vendor, vendor_path, len(vendor_base))
    dtbo_path = args.output_dir / "dtbo.img"
    shutil.copyfile(args.dtbo, dtbo_path)
    for source, name in ((args.kernel, "Image"), (args.config, "config"),
                         (args.ramdisk, "ramdisk.cpio.gz"),
                         (args.dtb, "sm7475-realme-gt-neo5-se.dtb")):
        copy_payload(source, args.output_dir / name)
    manifest = {
        "layout": "Android boot header v4; DTB in vendor_boot",
        "cmdline": cmdline,
        "kernel_release": args.kernel_release,
        "dtbo_index_checked": args.dtbo_index,
        "vendor_boot_mode": (
            "stock-header-footer" if args.preserve_stock_avb else
            "preserved-byte-for-byte" if args.preserve_stock_boot_avb else
            "preserved-base" if args.preserve_vendor_boot else
            "replacement-with-avb-footer" if args.vendor_avb_key else
            "replacement-unsigned"),
        "boot_avb_mode": (
            "stock-footer-preserved" if args.preserve_stock_avb else
            "stock-footer-preserved" if args.preserve_stock_boot_avb else
            "footer-with-supplied-key" if args.boot_avb_key else
            "unsigned-explicit" if args.allow_unsigned_boot else "none"),
        "vendor_boot_avb_mode": (
            "stock-footer-preserved" if args.preserve_stock_avb else
            "base-footer-preserved" if args.preserve_stock_boot_avb else
            "footer-with-supplied-key" if args.vendor_avb_key else
            "base-footer-preserved" if args.preserve_vendor_boot else
            "none"),
        "partition_bytes": {"boot": len(boot), "vendor_boot": len(vendor)},
        "payload_sha256": {
            "kernel": sha256(kernel), "boot_ramdisk": sha256(ramdisk),
            "dtb": sha256(dtb), "boot": sha256(boot), "vendor_boot": sha256(vendor),
            "dtbo": sha256(dtbo), "stock_boot": sha256(boot_base),
            "stock_vendor_boot": sha256(vendor_base), "config": sha256(config),
        },
        "inputs": {"kernel": str(args.kernel), "config": str(args.config),
                   "ramdisk": str(args.ramdisk),
                   "dtb": str(args.dtb), "dtbo": str(args.dtbo),
                   "base_boot": str(args.base_boot),
                   "base_vendor_boot": str(args.base_vendor_boot)},
        "preserved": ["vendor ramdisk", "vendor ramdisk table", "vendor bootconfig", "DTB load address", "dtbo input untouched"],
        "signing": ("stock boot and vendor_boot AVB footers preserved byte-for-byte"
                    if args.preserve_stock_avb else
                    "stock boot AVB footer preserved; vendor_boot preserved byte-for-byte"
                    if args.preserve_stock_boot_avb else
                    "base vendor_boot AVB footer preserved; boot footer made with supplied key"
                    if args.preserve_vendor_boot and args.boot_avb_key else
                    "boot and replacement vendor_boot footers made with supplied key"
                    if args.boot_avb_key and args.vendor_avb_key else
                    "boot footer made with supplied key; replacement vendor_boot has no AVB footer"
                    if args.boot_avb_key else
                    "replacement vendor_boot footer made with supplied key"
                    if args.vendor_avb_key else
                    "base vendor_boot AVB footer preserved byte-for-byte"
                    if args.preserve_vendor_boot else
                    "boot unsigned explicitly requested; AVB footer not generated"
                    if args.allow_unsigned_boot else
                    "unsigned; AVB footer not generated"),
        "validation": "v4 headers, payload sections, partition sizes and DTB FDT header checked",
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    payloads = (("kernel", "Image"), ("config", "config"),
                ("dtb", "sm7475-realme-gt-neo5-se.dtb"),
                ("boot_ramdisk", "ramdisk.cpio.gz"))
    (args.output_dir / "payloads.sha256").write_text("".join(
        f"{sha256((args.output_dir / name).read_bytes())}  {name}\n"
        for _, name in payloads
    ))
    for path, data in ((boot_path, boot), (vendor_path, vendor), (dtbo_path, dtbo)):
        (path.with_suffix(path.suffix + ".sha256")).write_text(f"{sha256(data)}  {path.name}\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
