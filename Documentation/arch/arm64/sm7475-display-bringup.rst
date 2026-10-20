================================
GT Neo5 SE display bring-up notes
================================

Device: realme GT Neo5 SE / RMX3700, SM7475, Senna NT37705 panel.

Verified on hardware, 2026-10-20
==============================

The kernel boots to the USB ACM root shell with MSM DRM, DSI-1 and
msmdrmfb registered. The active mode is 1240x2772 at 144 Hz, using two
DSC encoders. Panel reads over the command FIFO return ID 77 05 01 and
power mode 0x9c. Console text and RGB colour bars are visible.

Display quality is still being debugged. Correcting DSC SCR1 parameters
and grouping two slices per DSI packet removes the large vertical stripe
artifacts, but black is still raised to grey and text edges are distorted.
This is a bring-up checkpoint, not a claim of correct display output.

The DSC 1.2 latency calculation also includes the input pipeline, output
buffer and multiplexing budget. This programs three initial lines on
this panel instead of the legacy DSC 1.1 estimate of two. Device reads
confirm the new value, but raised black levels and text artifacts remain.

Hardware configuration
======================

* MDSS uses the APPS SMMUv2 with SID/mask 0x2800/0x402. UFS and USB must
  also have their actual stream IDs when unmatched streams are faulted.
* SCM download-mode references a real TCSR syscon rather than a numeric
  phandle copied from the stock DTB. Private mainline labels preserve the
  symbols expected by the bootloader's stock overlays.
* Panel VDDIO is PM8350C L12 at 1.8 V, EXTVDD is PM8350B L1 at 1.2 V,
  and VCI is PM8350C L13 at 3 V. Enable them sequentially with a 1 ms
  delay after each. Host VDDA is PM8350C L10 at 1.2 V; PHY VDDS is
  PM8350 L5 at 0.88 V.
* GPIO3 is the active-low reset. GPIO186 is an input, low with a pull-down
  on working stock Android; it is not a verified AVDD enable GPIO.
* PHY v4.3.2 uses VREG_CTRL_0=0x45, VREG_CTRL_1=0x19,
  GLBL_HSTX_STR_CTRL_0=0xbb and GLBL_STR_SWI_CAL_SEL_CTRL=1 on this board.
  These values match both live stock registers and the official Senna
  panel-specific vendor PHY implementation.
* DSC is 1.1 SCR1, 10 bpc, 8 bpp, with two 620x12 slices. The SCR1
  first-line BPG offset is 15. RGB RC ranges match the DSC 1.2 RGB table.
  Two slices form one DSI packet: word count 1241, one packet per line.

Command transport limitation
============================

With the panel already initialized, switching the runtime parameter
``/sys/module/msm/parameters/dsi_cmd_fifo`` to N makes DMA reads return
zero readback count/data. Switching back to Y restores valid reads.
The board command line currently enables the FIFO workaround. It is
limited to controller 0, DSI v2.6 and packets of at most 256 bytes.
The root cause of command DMA failure remains unresolved.

Build and recovery
==================

Use ``tools/build-sm7475.sh all``. The script copies the source into a
path without spaces and packages boot, vendor_boot and dtbo images in
the project ``out`` directory. Preserve the USB shell in vendor_boot,
verify AVB and payload hashes, and flash all three matching images.

The Linux ``reboot bootloader`` path currently reboots into Linux;
use the device keys to enter fastboot. Stock Android supports
``adb reboot bootloader``. Restore the stock boot, vendor_boot and dtbo
images together when collecting further stock display measurements.
