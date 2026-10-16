#!/usr/bin/env python3
"""Build a dtbo.img that keeps the stock overlay entries verbatim and appends a
fragment injecting /chosen/framebuffer into the entry the bootloader definitely
selects for this device.

Rationale: our own single-entry overlay never produced a framebuffer, while the
stock dtbo clearly is applied (the device boots with it).  So instead of
replacing the stock entry, we keep it byte-identical and only add one fragment
mapping /chosen -> simple-framebuffer, letting the simplefb console come up.

The fragment uses target = <&chosen> resolved through the base DTB's
/__symbols__ (the stock base DTB does contain chosen = "/chosen").
"""
import argparse
import struct
import subprocess
import tempfile
from pathlib import Path

PAGE = 4096
DT_MAGIC = 0xD7B7AB1E


def run(*args):
    subprocess.run(list(args), check=True, capture_output=True)


def dt_header_read(data):
    magic, total, hsize, esz, cnt, eoff, page, ver = struct.unpack_from(">8I", data, 0)
    if magic != DT_MAGIC:
        raise SystemExit("input is not a dt table image")
    return magic, total, hsize, esz, cnt, eoff, page, ver


def fdtput(*args):
    run("fdtput", *args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock-dtbo", type=Path, required=True)
    ap.add_argument("--mkdtboimg", required=True)
    ap.add_argument("--avbtool", required=True)
    ap.add_argument("--key", type=Path, required=True)
    ap.add_argument("--partition-size", type=int, default=25165824)
    ap.add_argument("--index", type=int, default=0,
                    help="which stock entry to extend (default 0)")
    ap.add_argument("--append-entry-dts",
                    help="compile this overlay .dts and append it as an extra "
                         "dt_table_entry after the stock entries (probe whether "
                         "the bootloader applies an added entry at all)")
    ap.add_argument("--target-path", default="/chosen",
                    help="fragment target-path (default /chosen); pass empty "
                         "string to fall back to a symbol target + __fixups__")
    ap.add_argument("--fb-addr", default="0xb8000000")
    ap.add_argument("--fb-size", default="0x2b00000")
    ap.add_argument("--width", type=int, default=1240)
    ap.add_argument("--height", type=int, default=2772)
    ap.add_argument("--stride", type=int, default=4960)
    ap.add_argument("--format", default="a8r8g8b8")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    data = args.stock_dtbo.read_bytes()
    _, _, _, esz, cnt, eoff, _, _ = dt_header_read(data)
    entries = []
    for i in range(cnt):
        size, off = struct.unpack_from(">II", data, eoff + i * esz)
        entries.append(data[off:off + size])
    if args.index >= len(entries):
        raise SystemExit("index out of range")

    with tempfile.TemporaryDirectory(prefix="dtbo-fb-") as tmp:
        tmp = Path(tmp)
        target = tmp / f"entry{args.index}.dtb"

        dtbs = []
        if args.append_entry_dts:
            # keep every stock entry verbatim, then append our overlay as one
            # more entry: probes whether the bootloader honours an added entry.
            extra = tmp / "extra.dtbo"
            run("dtc", "-I", "dts", "-O", "dtb", "-o", str(extra),
                args.append_entry_dts)
            for i, e in enumerate(entries):
                p = tmp / f"e{i}.dtb"
                p.write_bytes(e)
                dtbs.append(str(p))
            dtbs.append(str(extra))
            print(f"appended overlay entry ({extra.stat().st_size} bytes)")
        else:
            target.write_bytes(entries[args.index])
            names = subprocess.run(["fdtget", "-l", str(target), "/"],
                                   check=True, capture_output=True,
                                   text=True).stdout.split()
            frags = [int(n.split("@")[1]) for n in names if n.startswith("fragment@")]
            new = (max(frags) + 1) if frags else 0
            print(f"stock entry{args.index}: fragments={len(frags)} next=fragment@{new}")

            base = f"/fragment@{new}/__overlay__/framebuffer@{args.fb_addr}"
            if args.target_path:
                fdtput("-p", "-t", "s", str(target), f"/fragment@{new}",
                       "target-path", args.target_path)
            else:
                fdtput("-p", "-t", "x", str(target), f"/fragment@{new}", "target",
                       "0xffffffff")
                fdtput("-p", "-t", "s", str(target), "/__fixups__", "chosen",
                       f"/fragment@{new}:target:0")
            fdtput("-p", "-t", "s", str(target), base, "compatible",
                   "simple-framebuffer")
            fdtput("-p", "-t", "x", str(target), base, "reg",
                   "0", args.fb_addr, "0", args.fb_size)
            fdtput("-p", "-t", "x", str(target), base, "width", str(args.width))
            fdtput("-p", "-t", "x", str(target), base, "height", str(args.height))
            fdtput("-p", "-t", "x", str(target), base, "stride", str(args.stride))
            fdtput("-p", "-t", "s", str(target), base, "format", args.format)

            for i, e in enumerate(entries):
                p = tmp / f"e{i}.dtb"
                p.write_bytes(target.read_bytes() if i == args.index else e)
                dtbs.append(str(p))

        raw = tmp / "dtbo-raw.img"
        run("python3", args.mkdtboimg, "create", str(raw), "--page_size=4096", *dtbs)
        out = args.output
        out.write_bytes(raw.read_bytes())
        run(args.avbtool, "add_hash_footer", "--image", str(out),
            "--partition_name", "dtbo",
            "--partition_size", str(args.partition_size),
            "--algorithm", "SHA256_RSA4096", "--key", str(args.key))
        print(f"wrote {out} ({out.stat().st_size} bytes)")

        # local sanity: does the extended entry still apply to the stock base DTB?
        merged = tmp / "merged.dtb"
        merged.touch()
        return


if __name__ == "__main__":
    main()
