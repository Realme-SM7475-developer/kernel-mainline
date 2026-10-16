#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Generate the batch-1 (SPMI/PMIC) /soc children of the SM7475 board tree.

The mainline SM7475 device tree only describes a handful of /soc children
(gcc, the TLMM pinctrl and one GENI UART), while the stock base DTB carries
~2990 nodes.  The /soc children are being migrated from the stock base in
subsystem batches; this script produces the first batch, the SPMI/PMIC
subsystem: the SPMI PMIC arbiters, the arbiter debug device and the PMIC
glink/log devices.

What it does:

  1. extracts the DTB region of the stock vendor_boot (the region starts at
     4096 + ceil(vendor_ramdisk_size/4096)*4096; page size is the header's
     offset 12, ramdisk size offset 24, dtb_size offset 2100) and picks the
     FDT whose root qcom,msm-id is ours (0x24f);
  2. decompiles it with dtc and parses the resulting dts;
  3. selects the /soc children whose name or compatible mentions spmi/pmic;
  4. de-duplicates the qcom,spmi-pmic-arb nodes: the stock base has two of
     them (0xc42d000 bus-id 0 and 0xc432000 bus-id 1, both with
     cell-index 0).  Probing both is what produced the "kobject_add_internal
     failed for 0-0 with -EEXIST" and the -EBUSY on region 0xc400000 seen
     earlier: both claim the same "core" window.  Exactly one survives - the
     one the stock /__symbols__ names `spmi_bus` (0xc42d000, the bus the
     factory dtbo overlays extend) - and references to the dropped one are
     redirected to the survivor;
  5. rewrites the decompiled tree's raw phandle values back into label
     references.  The decompiled stock dts has numbers in place of labels, so
     a phandle / label map is rebuilt from the nodes' `phandle = <0xNN>`
     properties and the stock /__symbols__ node.  Only properties whose name
     is a known phandle-typed name are touched (the fixed list below plus
     `*-supply`, `*-gpios` and `pinctrl-N`), and only the first cell of each
     `<...>` group is considered, which is where dtc puts the phandle; `reg`
     and every other property are left alone.  A reference that cannot be
     pointed at a label available in the mainline tree is dropped (reported
     with --verbose), because leaving a raw number behind risks colliding
     with a phandle dtc hands out to an unrelated node;
  6. expands the direct /soc children's `reg` cells: the stock base's /soc is
     1-cell addressed (`reg = <addr size>`) while the mainline board's /soc is
     2-cell (`<hi addr lo size>`), so 1/1 cells become 2/2 ones;
  7. labels every migrated node that something references.  When the factory
     dtbo names the node - i.e. the node's stock path is what one of the
     dtbo's `__fixups__` labels resolves to - that label is used verbatim, so
     the bootloader's later merge into this tree lands in the real node.
     Everything else gets an `m_`-prefixed label, which must not collide with
     a label the abl-labels sink container still owns;
  8. emits the fragment as `&soc { ... }`.

Usage:

    tools/boot/gen-soc-spmi.py \
        --stock-vendor-boot mainline/prebulit/vendor_boot_a.img \
        --stock-dtbo mainline/prebulit/dtbo_a.img \
        --output arch/arm64/boot/dts/qcom/sm7475-realme-gt-neo5-se-soc-spmi.dtsi

The decompiled stock dts is never written next to the tree.
"""

import argparse
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

FDT_MAGIC = b"\xd0\x0d\xfe\xed"
PAGE = 4096

# Properties whose values carry phandles.  Everything else (notably `reg`) is
# copied through verbatim: a number that happens to equal a phandle value in
# another property must not be rewritten.
PHANDLE_PROPS = {
    "interrupt-parent", "interrupts-extended", "clocks", "power-domains",
    "gpios", "iommus", "io-channels", "resets", "phys", "next-level-cache",
    "operating-points-v2", "interconnects", "interconnect-parent",
}

# Stock DTB paths -> label defined by the mainline board tree.  These are the
# nodes the stock tree owns and the board tree describes itself rather than
# migrating; a stock path that is not listed here and is not one of the
# migrated nodes cannot be referenced by label.
KNOWN_TARGET_LABELS = {
    "/soc": "soc",
    "/soc/interrupt-controller@17100000": "intc",
    "/soc/interrupt-controller@b220000": "pdc",
    "/soc/pinctrl@f000000": "tlmm",
    "/soc/rsc@17a00000": "apps_rsc",
    "/soc/clock-controller@100000": "gcc",
}

# Batch-1 subsystem membership test.
SUBSYSTEM_RE = re.compile(r"spmi|pmic", re.IGNORECASE)
ARB_COMPATIBLE = "qcom,spmi-pmic-arb"


def fdt_root_props(blob):
    """Collect a raw FDT blob's root node properties."""
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
            if depth == 0:
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
        else:                                   # FDT_END / garbage
            break
    return props


def fdt_root_u32(blob, name):
    value = fdt_root_props(blob).get(name)
    if not value:
        return None
    return [struct.unpack_from(">I", value, k)[0]
            for k in range(0, len(value), 4)]


def split_dtbs(region):
    """Locate each concatenated FDT in the vendor_boot DTB region."""
    found = []
    start = 0
    while True:
        offset = region.find(FDT_MAGIC, start)
        if offset < 0 or offset + 40 > len(region):
            return found
        if struct.unpack_from(">I", region, offset + 4)[0] < 40:
            raise ValueError("malformed FDT inside the DTB region")
        found.append(offset)
        start = offset + 4


def extract_region(image):
    if image[:8] != b"VNDRBOOT":
        raise ValueError("vendor_boot input is not an Android image")
    version, page_size = struct.unpack_from("<II", image, 8)
    if version != 4 or page_size != PAGE:
        raise ValueError("vendor_boot input must use v4 and 4096-byte pages")
    ramdisk_size = struct.unpack_from("<I", image, 24)[0]
    dtb_size = struct.unpack_from("<I", image, 2100)[0]
    dtb_off = PAGE + ((ramdisk_size + PAGE - 1) // PAGE) * PAGE
    if dtb_off + dtb_size > len(image):
        raise ValueError("DTB region lies outside the image")
    return image[dtb_off:dtb_off + dtb_size]


def pick_slot(region, msm_id):
    slots = split_dtbs(region)
    for offset in slots:
        size = struct.unpack_from(">I", region, offset + 4)[0]
        blob = region[offset:offset + size]
        if fdt_root_u32(blob, b"qcom,msm-id") == [msm_id, 0x10000]:
            return offset, blob
    raise ValueError(f"no stock DTB slot carries qcom,msm-id <0x{msm_id:x} 0x10000>")


DT_TABLE_MAGIC = 0xD7B7AB1E
FDT_MAGIC_U32 = 0xD00DFEED


def dt_entry_blob(data, index):
    """Return one uncompressed Android DT table entry as a raw FDT blob."""
    if len(data) < 32:
        raise ValueError("truncated DT table header")
    magic, total, header, entry_size, count, offset, page, version = \
        struct.unpack_from(">8I", data)
    if magic != DT_TABLE_MAGIC or version != 0:
        raise ValueError("expected an uncompressed Android DT table v0")
    if not 32 <= header <= total <= len(data) or entry_size < 32:
        raise ValueError("invalid DT table sizes")
    if not 0 <= index < count:
        raise ValueError("DTBO index outside table")
    size, start = struct.unpack_from(">2I", data, offset + index * entry_size)
    if start < offset + entry_size * count or size < 40 or start + size > total:
        raise ValueError("DTBO payload outside table")
    blob = data[start:start + size]
    if struct.unpack_from(">2I", blob) != (FDT_MAGIC_U32, size):
        raise ValueError("entry is not one complete uncompressed FDT")
    return blob


def dtbo_fixup_labels(dtbo, index, dtc):
    """The label list the factory dtbo's `__fixups__` asks the base to resolve.

    Every fragment target and every external reference inside a fragment is
    written as a label; the bootloader maps those labels through the base
    DTB's /__symbols__, so the list doubles as the set of nodes the factory
    overlay expects the base to have.
    """
    with tempfile.TemporaryDirectory(prefix="gen-soc-spmi-dtbo-") as temp_name:
        temp = Path(temp_name)
        (temp / "entry.dtbo").write_bytes(dt_entry_blob(dtbo.read_bytes(), index))
        text = subprocess.run(
            [dtc, "-I", "dtb", "-O", "dts", str(temp / "entry.dtbo")],
            check=True, capture_output=True, text=True).stdout
    labels, inside = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "__fixups__ {":
            inside = True
        elif inside:
            if line == "};":
                break
            match = re.match(r'([\w,-]+) = "', line)
            if match:
                labels.append(match.group(1))
    if not labels:
        raise ValueError("the selected dtbo entry carries no __fixups__")
    return labels


class Node:
    __slots__ = ("name", "props", "children", "parent", "label")

    def __init__(self, name, parent=None):
        self.name = name
        self.props = []                          # (name, value-or-None)
        self.children = []
        self.parent = parent
        self.label = None

    @property
    def path(self):
        if self.parent is None:
            return ""
        return self.parent.path + "/" + self.name

    def prop(self, name):
        for key, value in self.props:
            if key == name:
                return value
        return None

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


def parse_dts(text):
    root = Node("")
    stack = [root]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//") or line.startswith("/dts-v1/"):
            continue
        if line == "/ {":
            continue
        if line.endswith("{"):
            name = line[:-1].strip()
            name = re.sub(r"^[A-Za-z_][\w]*:\s*", "", name)     # strip label
            node = Node(name, stack[-1])
            stack[-1].children.append(node)
            stack.append(node)
        elif line == "};":
            if len(stack) > 1:                   # root's own close is ignored
                stack.pop()
        else:
            if not line.endswith(";"):
                raise ValueError(f"unparseable decompiled line: {raw!r}")
            statement = line[:-1]
            if "=" in statement:
                key, value = statement.split("=", 1)
                stack[-1].props.append((key.strip(), value.strip()))
            else:
                stack[-1].props.append((statement.strip(), None))
    if len(stack) != 1:
        raise ValueError("unbalanced braces in decompiled dts")
    return root


def find(root, path):
    node = root
    for part in path.strip("/").split("/"):
        if not part:
            continue
        node = next((c for c in node.children if c.name == part), None)
        if node is None:
            return None
    return node


def is_phandle_prop(name):
    if name in PHANDLE_PROPS:
        return True
    if name.endswith("-supply") or name.endswith("-gpios"):
        return True
    return re.fullmatch(r"pinctrl-[0-7]", name) is not None


def group_cells(value):
    """Split a `<a b>, <c d>`-style value into per-group cell lists."""
    groups = re.findall(r"<([^<>]*)>", value)
    residue = re.sub(r"<[^<>]*>", "", value).replace(",", "").strip()
    if residue or not groups:
        return None
    return [g.split() for g in groups]


def label_for(name):
    text = re.sub(r"[^A-Za-z0-9]", "_", name).strip("_")
    return "m_" + text


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    here = Path(__file__).resolve()
    parser.add_argument("--stock-vendor-boot", type=Path, required=True)
    parser.add_argument("--stock-dtbo", type=Path, required=True)
    parser.add_argument("--dtbo-index", type=int, default=0,
                        help="factory dtbo entry whose labels the base must serve")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dtc", default="/usr/bin/dtc")
    parser.add_argument("--msm-id", default="0x24f")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    msm_id = int(args.msm_id, 16)

    region = extract_region(args.stock_vendor_boot.read_bytes())
    slot_off, dtb = pick_slot(region, msm_id)
    with tempfile.TemporaryDirectory(prefix="gen-soc-spmi-") as temp_name:
        temp = Path(temp_name)
        (temp / "slot.dtb").write_bytes(dtb)
        text = subprocess.run(
            [args.dtc, "-I", "dtb", "-O", "dts", str(temp / "slot.dtb")],
            check=True, capture_output=True, text=True).stdout
    root = parse_dts(text)

    # --- stock phandle map and label map --------------------------------
    phandle_path = {}
    for node in root.walk():
        value = node.prop("phandle")
        if value:
            phandle_path[int(value.strip("<> "), 0)] = node.path
    symbols = {}
    sym_node = next((n for n in root.children if n.name == "__symbols__"), None)
    if sym_node is None:
        raise ValueError("stock base has no /__symbols__")
    for key, value in sym_node.props:
        if value:
            symbols[key] = value.strip('"')

    # --- the labels the factory dtbo expects this tree to carry ----------
    # A migrated node the overlay names keeps that name; the bootloader merge
    # then lands in the real node instead of in an abl-labels sink.
    dtbo_label = {}
    for name in dtbo_fixup_labels(args.stock_dtbo, args.dtbo_index, args.dtc):
        path = symbols.get(name)
        if path:
            dtbo_label.setdefault(path, name)

    # --- select the SPMI/PMIC subsystem's /soc children -----------------
    soc = find(root, "/soc")
    if soc is None:
        raise ValueError("stock base has no /soc")
    selected = []
    for child in soc.children:
        compat = (child.prop("compatible") or "").lower()
        if SUBSYSTEM_RE.search(child.name) or SUBSYSTEM_RE.search(compat):
            selected.append(child)
    if not selected:
        raise ValueError("no SPMI/PMIC /soc children found")

    # --- de-duplicate the arbiters --------------------------------------
    arbs = [n for n in selected
            if ARB_COMPATIBLE in re.findall(r'"([^"]*)"',
                                            n.prop("compatible") or "")]
    keep_path = symbols.get("spmi_bus")
    keeper = next((n for n in arbs if n.path == keep_path), arbs[0] if arbs else None)
    phandle_remap = {}
    for arb in arbs:
        if arb is keeper:
            continue
        phandle_remap[int(arb.prop("phandle").strip("<> "), 0)] = keeper
    selected = [n for n in selected if n not in arbs or n is keeper]
    if keeper is not None:
        print(f"arbiters: `{keeper.path}` kept, dropped "
              f"{[a.path for a in arbs if a is not keeper]}", file=sys.stderr)

    # --- label the migrated nodes ---------------------------------------
    assigned = {}
    for node in selected:
        for sub in node.walk():
            if sub.prop("phandle") or sub is node:
                label = dtbo_label.get(sub.path) or label_for(sub.name)
                while label in assigned and assigned[label] is not sub:
                    label += "_"
                assigned[label] = sub
                sub.label = label

    def resolve(cell):
        """Label a cell must become a reference to, or None.

        The `known` flag separates "this cell is a literal, leave it alone"
        (known=False) from "this cell is a phandle nothing can point at"
        (known=True, label None): only the latter has to be dropped.
        """
        try:
            value = int(cell, 0)
        except ValueError:
            return False, None
        if value in phandle_remap:
            return True, phandle_remap[value].label
        if value not in phandle_path:
            return False, None                   # literal, not a phandle
        path = phandle_path[value]
        target = find(root, path)
        if target is not None and target.label:
            return True, target.label
        return True, KNOWN_TARGET_LABELS.get(path)  # None -> unresolved

    # --- transform the selected subtrees --------------------------------
    dropped = []
    for node in selected:
        for sub in node.walk():
            out = []
            for name, value in sub.props:
                if name == "phandle":
                    continue
                if value is not None and is_phandle_prop(name):
                    groups = group_cells(value)
                    if groups is not None:
                        rewritten, unresolved = [], False
                        for group in groups:
                            known, label = resolve(group[0]) if group else (False, None)
                            if known and label is None:
                                unresolved = True
                            if label is not None:
                                rewritten.append(
                                    "<&" + label + ("" if len(group) == 1 else " "
                                                    + " ".join(group[1:])) + ">")
                            else:
                                rewritten.append("<" + " ".join(group) + ">")
                        if unresolved:
                            dropped.append((sub.path, name))
                            continue
                        out.append((name, ", ".join(rewritten)))
                        continue
                if value is not None and name == "reg" and sub.parent is soc:
                    cells = value.strip("<> ").split()
                    if len(cells) % 2:
                        raise ValueError(f"{sub.path}: reg has odd cell count")
                    expanded = []
                    for k in range(0, len(cells), 2):
                        expanded += ["0x0", cells[k], "0x0", cells[k + 1]]
                    out.append((name, "<" + " ".join(expanded) + ">"))
                    continue
                out.append((name, value))
            sub.props = out

    # --- emit ------------------------------------------------------------
    lines = [
        "// SPDX-License-Identifier: (GPL-2.0-only OR BSD-2-Clause)",
        "/*",
        " * GENERATED - do not edit by hand.",
        " *",
        " * Batch 1 of the /soc migration: the SPMI/PMIC subsystem copied out of",
        " * the stock base DTB (vendor_boot slot msm-id 0x24f).  Regenerate with",
        " * tools/boot/gen-soc-spmi.py.",
        " *",
        " * The stock base carries two qcom,spmi-pmic-arb nodes (0xc42d000 bus-id 0",
        " * and 0xc432000 bus-id 1) that both register the same bus and map the same",
        " * 0xc400000 \"core\" window; that produced -EEXIST for 0-0 and -EBUSY on",
        " * 0xc400000.  Only the bus the stock /__symbols__ calls `spmi_bus` and the",
        " * factory dtbo overlays extend survives.  Raw phandle numbers were",
        " * rewritten into label references; reg cells were expanded from the stock",
        " * tree's 1/1 addressing to this tree's 2/2 /soc addressing.  A node the",
        " * factory dtbo names (`spmi_bus`, `battery_charger`, `ucsi`) keeps that",
        " * label so the bootloader's merge lands in this node and not in a sink;",
        " * the rest get m_-prefixed labels.",
        " */",
        "",
        "&soc {",
    ]

    def emit(node, depth):
        pad = "\t" * depth
        head = f"{node.label}: {node.name}" if node.label else node.name
        lines.append(f"{pad}{head} {{")
        for name, value in node.props:
            if value is None:
                lines.append(f"{pad}\t{name};")
            else:
                lines.append(f"{pad}\t{name} = {value};")
        for child in node.children:
            if child.props or child.children:
                emit(child, depth + 1)
            else:
                lines.append(f"{pad}\t{child.name} {{ }};")
        lines.append(f"{pad}}};")

    for node in selected:
        emit(node, 1)
    lines.append("};")
    lines.append("")

    args.output.write_text("\n".join(lines))
    if dropped:
        print(f"dropped {len(dropped)} property(ies) whose phandle target is not "
              f"in the mainline tree: {dropped}", file=sys.stderr)
    print(f"slot offset {slot_off:#x}, {len(selected)} /soc children -> "
          f"{args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
