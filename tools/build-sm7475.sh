#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
#
# SM7475 / Realme GT Neo5 SE 主线内核构建脚本
# ---------------------------------------------------------------------------
# 作用：
#   1. 使用本机专用配置 arch/arm64/configs/sm7475.config（与 arm64 defconfig 合并），
#      不污染通用配置；
#   2. 编译 arm64 内核（clang/LLVM）与该机器的 DTB；
#   3. 生成符合 Android 启动链的 boot.img、vendor_boot.img 与 dtbo.img
#      （Android boot header v4：内核在 boot.img，DTB 在 vendor_boot.img
#      的 DTB 区域）；
#   4. 所有产物统一输出到 <项目根>/out。
#
# 关于 dtbo：原厂 dtbo 的 overlay 依赖原厂 base DTB 的 /__symbols__，mainline
# DTB 没有这些符号，bootloader 应用 overlay 会 FDT_ERR_NOTFOUND 失败并直接
# 回落 fastboot。所以这里改为打包一个与本机匹配的空 overlay
# （tools/boot/sm7475-dtbo-overlay.dts），保证启动链能走通。
#
# 关于路径空格：Linux kbuild 明确拒绝含空格的源码路径
# （Makefile: "source directory cannot contain spaces or colons"）。
# 本仓库路径 "Realme gtneo5se/LInux 6.18" 含空格，所以脚本会先把源码
# rsync 到无空格的编译目录（默认 ~/.cache/sm7475-build/linux）再编译，
# 每次运行都会同步改动；最终镜像仍写到含空格的 out 目录。
#
# 用法：
#   tools/build-sm7475.sh              # 同步+配置+编译+打包
#   tools/build-sm7475.sh menuconfig   # 打开配置菜单
#   tools/build-sm7475.sh kernel       # 只同步+配置+编译内核/DTB
#   tools/build-sm7475.sh package      # 只打包（复用已有内核产物）
#   tools/build-sm7475.sh sync         # 只同步源码
#
# 可用环境变量覆盖：OUT_DIR BUILD_ROOT JOBS CLANG_DIR MKBOOTIMG AVBTOOL
#                   MKDTBOIMG BASE_BOOT BASE_VENDOR_BOOT DTBO_PARTITION_SIZE
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KERNEL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$KERNEL_ROOT/.." && pwd)"

OUT_DIR="${OUT_DIR:-$PROJECT_ROOT/out}"
BUILD_ROOT="${BUILD_ROOT:-$HOME/.cache/sm7475-build}"
BUILD_SRC="${BUILD_SRC:-$BUILD_ROOT/linux}"
JOBS="${JOBS:-$(nproc)}"
ARCH="${ARCH:-arm64}"

# AOSP/Android 工具链与打包工具（可用环境变量覆盖）
CLANG_DIR="${CLANG_DIR:-/home/yukino/project/android/los23.2/prebuilts/clang/host/linux-x86/clang-r574158}"
MKBOOTIMG="${MKBOOTIMG:-/home/yukino/project/android/los23.2/system/tools/mkbootimg/mkbootimg.py}"
AVBTOOL="${AVBTOOL:-/home/yukino/project/android/los23.2/prebuilts/kernel-build-tools/linux-x86/bin/avbtool}"
MKDTBOIMG="${MKDTBOIMG:-/home/yukino/project/android/los23.2/system/libufdt/utils/src/mkdtboimg.py}"

# 原厂 dump：作为 boot/vendor_boot 的封装母本，沿用其 vendor ramdisk/table/bootconfig
BASE_BOOT="${BASE_BOOT:-$PROJECT_ROOT/mainline/prebulit/boot_a.img}"
BASE_VENDOR_BOOT="${BASE_VENDOR_BOOT:-$PROJECT_ROOT/mainline/prebulit/vendor_boot_a.img}"
# 原厂 dtbo：其 3 条 dt_table_entry 会被逐字节保留，显示管线才不会被 bootloader 关掉
BASE_DTBO="${BASE_DTBO:-$PROJECT_ROOT/mainline/prebulit/dtbo_a.img}"

# dtbo 分区实际大小（0x1800000 = 24 MiB），打包时补齐，避免只覆盖分区开头
DTBO_PARTITION_SIZE="${DTBO_PARTITION_SIZE:-25165824}"

DTBO_OVERLAY="$KERNEL_ROOT/tools/boot/sm7475-dtbo-overlay.dts"

# 内核命令行：写进 boot 头（v4）。注意 arm64 内核实际是从 DTB /chosen/bootargs
# 取 cmdline，而该字段会被 bootloader 用 bootconfig 覆盖，所以这里写的内容
# 往往不生效；真正生效的是 sm7475.config 里的 CONFIG_CMDLINE(_FORCE)。
# 这里保持一致，便于查看。
CMDLINE="${CMDLINE:-console=tty0 console=ttyMSM0,115200n8 loglevel=8 ignore_loglevel clk_ignore_unused regulator_ignore_unused}"

BOARD="sm7475-realme-gt-neo5-se"
O_DIR="$BUILD_ROOT/kbuild"
KEY_DIR="$OUT_DIR/keys"
FRAGMENT_REL="arch/$ARCH/configs/sm7475.config"

export ARCH
export PATH="$CLANG_DIR/bin:$PATH"
MAKE=(make -C "$BUILD_SRC" LLVM=1 O="$O_DIR")

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
need() { [ -e "$1" ] || die "缺少文件: $1"; }

need "$KERNEL_ROOT/$FRAGMENT_REL"
need "$CLANG_DIR/bin/clang"
need "$MKBOOTIMG"
need "$AVBTOOL"
need "$MKDTBOIMG"
need "$BASE_BOOT"
need "$BASE_VENDOR_BOOT"
need "$DTBO_OVERLAY"
mkdir -p "$OUT_DIR" "$BUILD_ROOT"

# ---------------------------------------------------------------------------
# 0. 源码同步到无空格目录
# ---------------------------------------------------------------------------
sync_source() {
	log "同步源码 -> 无空格编译目录 $BUILD_SRC"
	mkdir -p "$BUILD_SRC"
	rsync -a --delete --exclude='/.git' "$KERNEL_ROOT/" "$BUILD_SRC/"
}

# ---------------------------------------------------------------------------
# 1. 配置：defconfig 作为基线，叠加 sm7475.config 差异
# ---------------------------------------------------------------------------
configure() {
	log "合并配置: defconfig + $FRAGMENT_REL"
	"${MAKE[@]}" defconfig
	( cd "$BUILD_SRC" && ARCH="$ARCH" LLVM=1 \
	    scripts/kconfig/merge_config.sh -m -O "$O_DIR" "$O_DIR/.config" "$FRAGMENT_REL" )
	"${MAKE[@]}" olddefconfig
	log "配置文件: $O_DIR/.config"
}

# ---------------------------------------------------------------------------
# 2. 编译内核与 DTB
# ---------------------------------------------------------------------------
build_kernel() {
	log "编译内核 (clang: "$("$CLANG_DIR/bin/clang" --version | head -1)")"
	"${MAKE[@]}" -j"$JOBS" Image dtbs
	log "内核镜像: $O_DIR/arch/$ARCH/boot/Image"
	log "设备树:   $O_DIR/arch/$ARCH/boot/dts/qcom/$BOARD.dtb"
}

# ---------------------------------------------------------------------------
# 3. 打包 Android boot.img / vendor_boot.img
# ---------------------------------------------------------------------------
make_keys() {
	mkdir -p "$KEY_DIR"
	[ -f "$KEY_DIR/boot.key" ] || {
		log "生成本机 AVB 测试密钥 (RSA-4096) -> $KEY_DIR"
		openssl genrsa -out "$KEY_DIR/boot.key" 4096
	}
	[ -f "$KEY_DIR/vendor.key" ] || openssl genrsa -out "$KEY_DIR/vendor.key" 4096
}

make_ramdisk() {
	# boot.img 的 generic ramdisk：空 cpio（真正的 ramdisk 在 vendor_boot.img 里）
	local cpio="$BUILD_ROOT/empty-ramdisk.cpio"
	[ -f "$cpio" ] || python3 - "$cpio" <<-'PY'
	import sys, pathlib
	out = pathlib.Path(sys.argv[1])
	# newc (070701) 头：magic + 13 个 8 位十六进制字段
	#   ino mode uid gid nlink mtime filesize devmajor devminor rdevmajor
	#   rdevminor namesize check
	# namesize 必须等于文件名字节数，否则 cpio 解析器读到空文件名直接报错。
	name = b"TRAILER!!!\0"
	fields = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, len(name), 0]
	blob = b"070701" + b"".join(b"%08X" % f for f in fields) + name
	blob += b"\0" * ((4 - len(blob) % 4) % 4)
	out.write_bytes(blob + b"\0" * ((512 - len(blob) % 512) % 512))
	PY
	gzip -9 -c "$cpio" > "$OUT_DIR/ramdisk.cpio.gz"
	echo "$OUT_DIR/ramdisk.cpio.gz"
}

make_dtbo() {
	# 实测两条硬性要求：
	#  1) dtbo 分区必须带 AVB footer，否则 bootloader 直接拒绝引导（秒回 fastboot）；
	#  2) 往原厂 entry 里追加 fragment 不会被应用，所以这里把 3 条原厂
	#     dt_table_entry **逐字节保留**，再把我们自己的 overlay 作为**额外第 4 条
	#     entry** 追加进去（往 /chosen 注入 simple-framebuffer）。
	#     保留原厂 entry 是为了让显示管线不被 bootloader 关掉（否则变黑屏）。
	local key="$KEY_DIR/boot.key"
	need "$key"
	need "$BASE_DTBO"
	local out="$BUILD_ROOT/dtbo.img"
	log "生成 dtbo（3 条原厂 entry + 我们的 overlay entry）-> $out"
	python3 "$BUILD_SRC/tools/boot/dtbo_add_framebuffer.py" \
		--stock-dtbo "$BASE_DTBO" \
		--mkdtboimg "$MKDTBOIMG" \
		--avbtool "$AVBTOOL" \
		--key "$key" \
		--partition-size "$DTBO_PARTITION_SIZE" \
		--append-entry-dts "$DTBO_OVERLAY" \
		--output "$out" >/dev/null
	echo "$out"
}

package() {
	local image="$O_DIR/arch/$ARCH/boot/Image"
	local dtb="$O_DIR/arch/$ARCH/boot/dts/qcom/$BOARD.dtb"
	need "$image"
	need "$dtb"
	make_keys
	local ramdisk dtbo krel
	ramdisk="$(make_ramdisk)"
	dtbo="$(make_dtbo)"
	krel="$(cat "$O_DIR/include/config/kernel.release" 2>/dev/null || echo unknown)"

	log "打包 Android v4 镜像 -> $OUT_DIR（母本: 原厂 dump）"
	# vendor_boot 保持原厂逐字节一致：该机 bootloader 拒绝任何 vendor_boot
	# DTB 替换（哪怕只换其中一份 DTB 也会秒回 fastboot），所以用
	# --preserve-vendor-boot，并且不能再给它加自签 footer。
	python3 "$BUILD_SRC/tools/boot/build_mainline_images.py" \
		--mkbootimg "$MKBOOTIMG" \
		--base-boot "$BASE_BOOT" \
		--base-vendor-boot "$BASE_VENDOR_BOOT" \
		--kernel "$image" \
		--config "$O_DIR/.config" \
		--kernel-release "$krel" \
		--ramdisk "$ramdisk" \
		--dtb "$dtb" \
		--dtbo "$dtbo" \
		--cmdline "$CMDLINE" \
		--preserve-vendor-boot \
		--avbtool "$AVBTOOL" \
		--boot-avb-key "$KEY_DIR/boot.key" \
		--output-dir "$OUT_DIR" >/dev/null
	log "完成，产物："
	ls -lh "$OUT_DIR"/boot.img "$OUT_DIR"/vendor_boot.img "$OUT_DIR"/dtbo.img
}

case "${1:-all}" in
	sync)       sync_source ;;
	menuconfig) sync_source; configure; "${MAKE[@]}" menuconfig ;;
	kernel)     sync_source; configure; build_kernel ;;
	package)    package ;;
	all|"")     sync_source; configure; build_kernel; package ;;
	*)          die "未知参数: $1" ;;
esac
