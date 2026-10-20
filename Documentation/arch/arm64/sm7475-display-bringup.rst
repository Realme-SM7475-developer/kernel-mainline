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

With stock Android's command encoder idle power collapse temporarily
disabled, both DCE0 encoder register banks, their control blocks and
the shared configuration match mainline. Stock's enabled PCC matrices
are identity matrices. These measurements do not explain the remaining
artifacts. Capture registers with the display awake: idle power collapse
otherwise exposes reset values. Restore the debug settings afterwards.

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
limited to controller 0, DSI v2.6 and packets of at most 64 bytes,
including the command header and padding. The native panel 0x90/0x91
commands configure its DSC decoder; do not send a 128-byte PPS through
the 64-byte command FIFO.
Removing the oversized PPS transfer preserves panel ID and power-mode
readback but does not fix raised black or text artifacts.
The root cause of command DMA failure remains unresolved.

Further hardware isolation, 2026-10-20
-------------------------------------

Pinning the command GEM at stock's IOVA 0xfff2d000 does not restore DMA
readback or improve the display. Privileged SMMU reads show SMR[4] =
0x84022800 and S2CR[4] = 3. Hardware translation resolves that IOVA, and
a write-combined mapping of the resulting RAM page contains the expected
embedded DCS command header. A separately mapped page below 4 GB, with
explicit cache cleaning, also produces no readback. Zero padding to eight
bytes and batching maximum-return-size with the read command do not help.

A controlled read from an intentionally unmapped IOVA reports SID 0x2802
and context bank 3. DSI command DMA therefore reaches the expected SMMU
context. This deliberately injected fault must not be confused with a
spontaneous display failure. The temporary diagnostic mapping and module
were removed after the test.

The bootloader replaces the root compatible with qcom,ukee-mtp,
qcom,ukee and qcom,mtp. Board diagnostics gated only on
realme,gt-neo5-se will not execute. The MDSS node retains its compatible.

Stock SDE debug offsets use physical base 0xae00000, whereas mainline's
DPU catalog offsets use MDP base 0xae01000. Account for this difference
when comparing subblocks: stock INTF1 offset 0x36000 is physical
0xae36000. DSC, wide-bus and interface mux configuration match stock.

An eight-bit DSC experiment changed both encoder and native decoder
parameters, preserving resolution, slice geometry and rate. It caused
full-screen coloured noise on this Senna panel. The experiment was
rejected, its source changes reverted, and the known ten-bit image
selected for recovery. Reports about another NT37705 panel are not
evidence that this panel supports the same eight-bit configuration.

Display memory bandwidth
========================

The initial SM7475 tree omitted all interconnect providers and MDSS
bandwidth paths; the live interconnect summary was empty. Add the
Waipio MC, GEM, configuration and multimedia NoCs with an APPS BCM voter,
and the standard MDSS mdp0-mem, mdp1-mem and cpu-cfg paths. The stock DTB
uses these NoC addresses, and the live command DB contains the expected
MC0, SH0, SH1, CN0, MM0 and MM1 resources.

With these providers present, the 2026-10-20 22:48 kernel boots to the USB
shell and registers the display requests in the interconnect summary.
The user still reports grey black levels and text distortion. DMA reads
remain empty, and a DMA brightness write followed by FIFO readback does
not change the panel setting. Temporarily voting 400 MB/s on both SF
memory routes also does not restore DMA; the temporary votes and consumer
overlay were removed afterwards. These bandwidth paths repair a missing
platform resource, but are not a display-quality or command-DMA fix.

Some suppliers still report sync_state pending on legacy camera nodes.
Their aggregate bandwidth can retain initial constraints; distinguish
the individual display requests from these aggregate values.

Command transport isolation
===========================

A controlled runtime test sends the same embedded DCS brightness packet
from a temporary, cache-cleaned RAM page and from the internal FIFO.
Memory DMA reports completion but FIFO readback remains 8192; the FIFO
transmission changes readback to 4096. Each pass restores brightness to
2048 through the working FIFO path. An additional non-embedded DMA
brightness test also fails; this small-packet test alone does not establish
that every non-embedded transfer is broken.

With DSI interrupt enables temporarily masked, latched registers after
memory DMA show completion, FIFO_STATUS=0x11111010, ACK_ERR_STATUS=0,
TIMEOUT_STATUS=0 and no defined PHY error bits. FIFO_STATUS includes normal
empty indicators, so a nonzero register is not sufficient to report a
FIFO error. Filter overflow and underflow bits before setting the software
FIFO error flag. The old ``dsi_err_worker: status=4`` message is not proof
of a hardware underflow.

The physical GCC HF and SF AXI clock gates both read 0x111, with CLK_OFF
clear. Temporarily forcing the vendor DSI dynamic-clock mask does not
restore memory DMA. The display SMMU context already has ACTLR=1, matching
the stock SID table; rewriting it and flushing the IOTLB does not help.
Temporary mappings, interrupt masks, clock settings and modules are
restored or removed after these probes. These results narrow the command
transport investigation but do not identify the cause of raised black
levels or text distortion.

Stock DMA and decoder comparison
===============================

Scoped probes at stock's DSI command kickoff function capture an actual
128-byte PPS transmission. Both halves of the generated mainline PPS now
match that stock payload byte for byte. Reading native panel registers
also returns the same 0x90 data (03 03) and complete 18-byte 0x91 data on
both kernels. This verifies configuration values, not successful delivery
of a standard PPS over mainline's failing memory DMA path. Stock's standard
READ_PPS_START command returns an all-zero buffer and is not a reliable
way to establish decoder PPS state on this panel.

Stock's display stream uses SMR[4]=0x84022800 and S2CR[4]=0x304, selecting
context bank 4. Mainline uses the same stream match with context bank 3;
context indices are allocation results and must not simply be copied.
Stock's context has ACTLR=1, TCR=0x80351c and MAIR0=0xf404ff44.

In the captured stock boot, walking the three-level command mapping
resolves IOVA 0xfff2d000 to physical page 0xa7512000. At command kickoff,
both the driver's vmap and
the physical page's linear mapping contain 0x00370001, 0xa006000a. This
independently validates the walk. The leaf uses write-back caching and
inner shareability. An isolated mainline-page comparison with and without
IOMMU_CACHE still fails in both DMA cases; its FIFO control succeeds.
Temporarily matching stock's stream shareability and context bypass
attributes also does not restore DMA. These changes were reverted.

Stock disables /dev/mem. A broad seq_printf argument probe preceded an
unexpected stock reboot without a retained pstore record; do not repeat
that probe. Subsequent probes limited to SMMU structure fields and DSI
kickoff completed and were removed, with encoder idle-collapse settings
restored. Existing IOMMU tracepoints alone did not capture a new display
mapping during the sampled interval.

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
