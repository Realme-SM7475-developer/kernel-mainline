# Linux 6.18 mainline for Realme GT Neo5 SE (Qualcomm SM7475)

本仓库在 Linux 6.18 主线内核基础上，为 **真我 GT Neo5 SE（RMX3700，Qualcomm
SM7475 / Snapdragon 7+ Gen 2）** 做早期 bring-up 适配，并提供一条命令即可完成
**内核编译 + Android 启动链镜像生成**的构建脚本。

> 当前阶段是**早期 bring-up / 诊断阶段**：目标是先让内核带着 `simplefb`
> 在屏幕上打印出日志，便于在没有串口的情况下观察 dmesg 滚动。
> 该适配尚**未完成真机稳定开机验证**，请仅在已解锁、可随时用原厂 dump 回滚的
> 机器上测试。

## 目录结构

| 路径 | 说明 |
| ---- | ---- |
| `arch/arm64/configs/sm7475.config` | **本机专用编译配置（单独文件）**，与 `arch/arm64/configs/defconfig` 合并使用，不污染通用配置 |
| `arch/arm64/boot/dts/qcom/sm7475.dtsi` | SM7475 SoC 设备树 |
| `arch/arm64/boot/dts/qcom/sm7475-realme-gt-neo5-se.dts` | 本机设备树，含 bootloader 遗留 framebuffer（simplefb） |
| `arch/arm64/boot/dts/qcom/sm7475-realme-gt-neo5-se-simplefb-overlay.dts` | 在完整 vendor DTB 上叠加 simplefb 的 overlay |
| `drivers/pinctrl/qcom/pinctrl-cape.*` | Cape(SM7475) TLMM pinctrl 驱动 |
| `drivers/clk/qcom/gcc-sm8450.c` | 复用 SM8450 GCC 并加入 Cape/SM7475 支持 |
| `tools/build-sm7475.sh` | **构建入口脚本**（编译内核 + 生成 boot/vendor_boot） |
| `tools/boot/build_mainline_images.py` | Android v4 boot/vendor_boot 封装工具 |

## 依赖

脚本默认使用本机已安装的 AOSP 工具链，可用环境变量覆盖：

- clang/LLVM：`clang-r574158`（Android clang 21）
  `/home/yukino/project/android/los23.2/prebuilts/clang/host/linux-x86/clang-r574158`
- `mkbootimg.py`：`/home/yukino/project/android/los23.2/system/tools/mkbootimg/mkbootimg.py`
- `avbtool`：`/home/yukino/project/android/los23.2/prebuilts/kernel-build-tools/linux-x86/bin/avbtool`
- 原厂 dump（镜像母本）：`../mainline/prebulit/{boot_a.img,vendor_boot_a.img,dtbo_a.img}`

> **路径空格说明**：Linux kbuild 明确拒绝含空格的源码路径
> （`Makefile`: *source directory cannot contain spaces or colons*）。
> 本仓库路径含空格，因此 `tools/build-sm7475.sh` 会先把源码 `rsync` 到无空格的
> 编译目录（默认 `~/.cache/sm7475-build/linux`）再编译，每次运行自动同步改动；
> 最终镜像仍写入含空格的 `out` 目录。

## 构建

```sh
# 一键：同步源码 + 合并配置 + 编译内核&DTB + 打包镜像
tools/build-sm7475.sh

# 只编译内核与 DTB
tools/build-sm7475.sh kernel

# 只打包（复用已有内核产物）
tools/build-sm7475.sh package

# 打开配置菜单
tools/build-sm7475.sh menuconfig
```

输出目录：`/home/yukino/project/Realme gtneo5se/out`

- `boot.img`：Android boot header v4，含主线内核 + 空 generic ramdisk
- `vendor_boot.img`：沿用原厂 vendor ramdisk / ramdisk table / bootconfig，
  仅替换 DTB 区域为本机主线 DTB，并附带 AVB footer
- `dtbo.img`：原厂 DTBO 副本
- `Image` / `config` / `sm7475-realme-gt-neo5-se.dtb` / `ramdisk.cpio.gz` /
  `manifest.json` / `payloads.sha256`

AVB 测试密钥首次构建时生成到 `out/keys/`（本机 RSA-4096，**非**原厂私钥，
仅适用于已解锁设备）。

## 启动链与 simplefb

本机使用标准 **Android boot header v4** 分离方案：

- 内核 `Image` 放在 `boot.img`；
- DTB 放在 `vendor_boot.img` 的 DTB 区域；
- 设备的命令行为 bootconfig 提供。

`arch/arm64/configs/sm7475.config` 中与屏幕日志相关的关键项：

```
CONFIG_FB=y
CONFIG_SYSFB=y
CONFIG_SYSFB_SIMPLEFB=y
CONFIG_FB_SIMPLE=y
CONFIG_FRAMEBUFFER_CONSOLE=y
# CONFIG_DRM_SIMPLEDRM is not set   # 避免 simpledrm 抢占同一块显存
```

设备树 `chosen` 中描述 bootloader 留下的扫描缓冲，由 `simplefb` 接管，
配合 `console=tty0` 即可在屏幕上看到 `Linux version ...` 与 dmesg 滚动。

## 测试与回滚

手机已解锁并连接 adb 时，可将 `out/` 中的镜像刷入 A 槽：

```sh
fastboot flash boot         out/boot.img
fastboot flash vendor_boot  out/vendor_boot.img
fastboot flash dtbo         out/dtbo.img
fastboot reboot
```

出问题用原厂 dump 恢复：

```sh
fastboot flash boot         ../mainline/prebulit/boot_a.img
fastboot flash vendor_boot  ../mainline/prebulit/vendor_boot_a.img
fastboot flash dtbo         ../mainline/prebulit/dtbo_a.img
fastboot flash vbmeta       ../mainline/prebulit/vbmeta_a.img
fastboot set_active a
fastboot reboot
```

启动后观察屏幕是否出现 `Linux version` 与 `simplefb` 相关日志；
若仍重启，可用 `pstore`（配置中已开启）做进一步取证。
