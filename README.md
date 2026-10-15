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
| `tools/build-sm7475.sh` | **构建入口脚本**（编译内核 + 生成 boot/vendor_boot/dtbo） |
| `tools/boot/build_mainline_images.py` | Android v4 boot/vendor_boot 封装工具 |
| `tools/boot/sm7475-dtbo-overlay.dts` | 本机 dtbo 用的空 overlay（绕过原厂 `/__symbols__` 依赖，见下文） |

## 依赖

脚本默认使用本机已安装的 AOSP 工具链，可用环境变量覆盖：

- clang/LLVM：`clang-r574158`（Android clang 21）
  `/home/yukino/project/android/los23.2/prebuilts/clang/host/linux-x86/clang-r574158`
- `mkbootimg.py`：`/home/yukino/project/android/los23.2/system/tools/mkbootimg/mkbootimg.py`
- `avbtool`：`/home/yukino/project/android/los23.2/prebuilts/kernel-build-tools/linux-x86/bin/avbtool`
- `mkdtboimg.py`：`/home/yukino/project/android/los23.2/system/libufdt/utils/src/mkdtboimg.py`
- 原厂 dump（镜像母本）：`../mainline/prebulit/{boot_a.img,vendor_boot_a.img}`

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

- `boot.img`：Android boot header v4，含主线内核 + 空 generic ramdisk，并带
  本机 cmdline（`console=tty0 ...`，见 `CMDLINE` 环境变量）
- `vendor_boot.img`：**与原厂逐字节一致**（`--preserve-vendor-boot`）。该机
  bootloader 拒绝任何 vendor_boot DTB 替换，详见下文
- `dtbo.img`：由 `tools/boot/sm7475-dtbo-overlay.dts` 现场编译、并加 AVB
  footer 封装（24 MiB）。它把 `simple-framebuffer` 注入原厂 base DTB 的
  `/chosen`，是屏幕上能看到日志的关键
- `Image` / `config` / `sm7475-realme-gt-neo5-se.dtb` / `ramdisk.cpio.gz` /
  `manifest.json` / `payloads.sha256`

AVB 测试密钥首次构建时生成到 `out/keys/`（本机 RSA-4096，**非**原厂私钥，
仅适用于已解锁设备）。

## 启动链与 simplefb

本机使用标准 **Android boot header v4** 分离方案：

- 内核 `Image` 放在 `boot.img`；
- DTB 由 bootloader 取自 `vendor_boot.img` 的 DTB 区域（原厂）；
- 命令行由 boot 头 cmdline + vendor_boot bootconfig + bootloader 追加项合成。

`arch/arm64/configs/sm7475.config` 中与屏幕日志相关的关键项：

```
CONFIG_FB=y
CONFIG_SYSFB=y
CONFIG_SYSFB_SIMPLEFB=y
CONFIG_FB_SIMPLE=y
CONFIG_FRAMEBUFFER_CONSOLE=y
# CONFIG_DRM_SIMPLEDRM is not set   # 避免 simpledrm 抢占同一块显存
```

`dtbo` overlay 往原厂 `/chosen` 注入 bootloader 留下的扫描缓冲描述，
由 `simplefb` 接管；配合 boot 头里的 `console=tty0`，即可在屏幕上看到
`Linux version ...` 与 dmesg 滚动。

## 刷入后「秒回 fastboot」：bootloader 的三条硬性要求

本机 bootloader 校验很严，实测踩到下面三点，任意一条不满足都会**直接放弃
引导、秒回 fastboot**（每次失败还会把槽位标成 unbootable，见第四点）。

### 1) dtbo 分区必须带 AVB footer

`add_hash_footer` 生成的 footer 只要结构合法即可（实测用本机自签测试密钥也
能通过），但**完全没有 footer 的 dtbo 会被拒绝**。`make_dtbo()` 因此用
`avbtool` 生成 dtbo，与 boot/vendor_boot 一致。

### 2) vendor_boot 的 DTB 区域必须与原厂逐字节一致

原厂 `vendor_boot` 的 DTB 区域是 **3 份首尾相接的 DTB**（msm-id 分别
`0x21c` / … / `0x24f`）。实测：**只要替换其中任意一份（哪怕换成同 msm-id、
合法、带 `__symbols__` 的 DTB）都会秒回 fastboot**；而保留原厂内容、仅重签
footer 则能正常引导。所以脚本用 `--preserve-vendor-boot`，
`out/vendor_boot.img` 与原厂完全一致。

> 结论：本机**无法**用自建 DTB 替换 vendor_boot 里的设备树。内核需要的额外
> 节点改由 dtbo overlay 注入（见下一点）。自建的
> `sm7475-realme-gt-neo5-se.dtb` 仍会被打包进 `out/` 供离线分析，但不参与
> 真机启动。

### 3) overlay 的 fragment 必须用 `target = <&symbol>`

原厂 base DTB 顶层带 `__symbols__`（1439 个符号）。实测 `target-path = "/"`
**不被支持**，必须写成 `target = <&label>`，由 bootloader 查 `__symbols__`
解析。原厂 base DTB 里有 `chosen = "/chosen"`，故
`tools/boot/sm7475-dtbo-overlay.dts` 用 `target = <&chosen>` 把
`simple-framebuffer` 注入 `/chosen`。

### 4) 槽位 unbootable 循环

mainline 内核没有 Android 用户态，无法把槽位标记为「成功引导」，bootloader
在数十秒后用看门狗复位并**把该槽标成 `slot-unbootable`**；此后
`fastboot reboot` 不再尝试引导，直接回 fastboot。所以**每次刷完都要先**
`fastboot set_active a` 清标记再 `fastboot reboot`。用
`fastboot getvar slot-unbootable:a` 可确认（须为 `no` 才引导）。

> 另：刷入失败时若 `fastboot getvar` / `oem device-info` 卡住不返回但
> `fastboot devices` 仍能列出设备，是 fastboot 控制通道坏了，**拔插 USB**即可。

## 测试与回滚

手机已解锁并连接 adb 时，可将 `out/` 中的镜像刷入 A 槽。**三个都要刷**：

```sh
fastboot flash boot         out/boot.img
fastboot flash vendor_boot  out/vendor_boot.img
fastboot flash dtbo         out/dtbo.img
# 关键：清掉槽位的 unbootable 标记，否则 bootloader 根本不会尝试引导，直接进 fastboot
fastboot set_active a
fastboot reboot
```

> **「秒回 fastboot」常见原因：槽位被标记为 unbootable**
> 一次引导失败后，bootloader 会累减 `slot-retry-count`，用尽后把该槽标为
> `slot-unbootable`。此后无论刷什么都**不再尝试引导**，`fastboot reboot` 会
> 立刻回到 fastboot。用 `fastboot getvar slot-unbootable:a` 可确认；
> 执行 `fastboot set_active a` 会清掉该标记（必要时两个槽都清一遍）。
> 若 `fastboot getvar`/`oem device-info` 卡住不返回但 `fastboot devices` 仍能
> 列出设备，说明 fastboot 控制通道坏了，**重新插拔 USB 线**即可。

出问题用原厂 dump 恢复（同样要 `set_active a` 清标记）：

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

> 注：`boot.img` 的 generic ramdisk 是一个**合法的空 cpio**（只有 `TRAILER!!!`），
> 真正内容在 `vendor_boot` 里。早期版本的生成脚本漏填了 newc 头的 `namesize`
> 字段，产出的是**非法 cpio**（`cpio -tv` 报“文件名为空”），现已修复。
