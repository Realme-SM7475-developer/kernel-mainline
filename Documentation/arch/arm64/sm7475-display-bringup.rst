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

Disabling the standard compression mode before replaying native 0x90/0x91
also leaves grey black levels and distorted text. FIFO reads confirm that
standard compression was disabled during this comparison. It was enabled
again afterwards and the temporary module was removed.

Stock disables /dev/mem. A broad seq_printf argument probe preceded an
unexpected stock reboot without a retained pstore record; do not repeat
that probe. Subsequent probes limited to SMMU structure fields and DSI
kickoff completed and were removed, with encoder idle-collapse settings
restored. Existing IOMMU tracepoints alone did not capture a new display
mapping during the sampled interval.

Optional bootloader panel handoff diagnostic
============================================

The default driver still resets and fully initializes the panel. A separate
``sm7475-handoff.config`` fragment adds the read-only boot parameter
``panel_tianma_nt37705.bootloader_handoff=1``. It requests reset with
GPIOD_ASIS so probe does not discard the bootloader's state before prepare.
Only the first prepare can preserve that state, after enabling the rails
and checking deasserted output reset, panel ID, awake power mode and the
complete expected ten-bit native 0x90/0x91 configuration. Failed checks
select the existing full initialization. Subsequent power cycles also use
full initialization.

The successful handoff branch skips panel reset, initialization and the
standard compression-mode write. Mainline still programs its DPU, DSC,
DSI host and PHY, and backlight updates remain active. The bootloader's
0x2f refresh setting is logged and preserved; the host mode remains the
current 144 Hz mode. This is an initialization isolation experiment, not
a complete reproduction of the bootloader pipeline or a verified fix.
Check the handoff log before interpreting a visual result: a fallback
boot provides no evidence about preserving the bootloader panel state.

Build this diagnostic with::

  EXTRA_FRAGMENT_REL=arch/arm64/configs/sm7475-handoff.config \
    bash tools/build-sm7475.sh all

Initially, building without the extra fragment selected the original
initialization. Following the verified reset-order fix below, the board's
normal config enables this guarded handoff and the tested dynamic planes.
Use ``panel_tianma_nt37705.bootloader_handoff=0`` to compare full initialization.
Retain the matching known ten-bit images before replacing build output.
The 2026-10-21 diagnostic build passes compilation, checkpatch, AVB and
payload hashes, including final kernel/config and USB shell checks. All
three matching images were flashed and the USB shell returned. The boot
log confirms the preserving branch, ID 77 05 01, power 0x9c and the exact
native decoder bytes; the bootloader's 0x2f refresh value is 00. The user
reports normal black levels but still distorted text with black lines.
Preserving the bootloader panel state therefore improves the background,
but does not fix the whole display. Initialization also sets refresh and
other decoder state, so this comparison alone does not identify which
omitted command causes the grey background.

Even without mainline panel initialization,
the backlight read through memory DMA still returns no data. Restoring
FIFO mode returns the original readback of 8192. Thus the DMA limitation
does not require executing the full mainline panel initialization.

Framebuffer versus constant-colour comparison, 2026-10-21
--------------------------------------------------------

The user sees black horizontal lines through a framebuffer-rendered white
rectangle. Full framebuffer readback matches every visible RGB pixel of
the test pattern, and CTL-start/PP-done both increase for its write update.
With SSPP0 constant colour enabled instead, full-screen white is normal
without horizontal lines. INTF frame count confirms that transfer. This
makes the framebuffer fetch/source-format path a priority for the next
investigation; the precise cause is still unknown. The user requested a
pause to shut down the computer, so further experiments stopped.

Fetch-path isolation after resuming, 2026-10-21
---------------------------------------------

A stricter comparison writes the entire framebuffer to 0xff and verifies
its complete SHA256 before submitting the image. The user still sees black
horizontal lines. LM0/LM1 signatures repeatedly read 0x0c0e0bec and
0xf7eba632, whereas the same full-screen white from SSPP constant colour
reads 0xa2652535 on both mixers. The difference is already present at the
mixer outputs, before DSC. This comparison is stronger than comparing a
mixed test pattern against constant full-screen white.

Disabling CDP, pixel-extension override or the scaler input-depth flag
does not change the abnormal signatures. Mapping a separately allocated,
cache-cleaned DMA32 white page repeatedly across an independent scanout
IOVA range also gives the same signatures. The temporary mapping and
module were removed after restoring the original source address and
confirming a frame transfer. ARGB8888, RGB888, RGB565 and XRGB2101010
comparisons do not restore the constant-white signatures. Reducing the
source and output width to 620 still gives the abnormal left signature.
All these temporary controls are restored; they are not retained fixes.

The stock capture includes an active 620-pixel DMA0 source, but it is a
partial-height layer and does not establish the complete stock fetch
topology. Do not infer two full-height fetch pipes from that capture.

The optional ``sm7475-virtual-planes.config`` fragment retains panel
handoff and enables the existing ``msm.dpu_use_virtual_planes=1`` switch.
The resource manager prefers DMA SSPPs for unscaled RGB planes, unlike
the current primary plane fixed to VIG0. This provides a different fetch
path through normal DRM resource allocation. Verify the actual assigned
SSPP in live DRM state before interpreting the result. The fragment is
a diagnostic comparison. Its full kernel/DTB build, AVB, image and payload
hashes, effective boot parameters and USB shell payload checks pass. The
2026-10-21 10:53 kernel was flashed and boots with the USB shell and panel
handoff intact. Live state confirms SSPP_DMA0 (sspp_8) instead of VIG0.
The user still reports horizontal lines and incomplete text, so changing
the SSPP type alone is not a fix. Repeating the full-white memory test on
DMA0 produces the same framebuffer SHA256 and the same two abnormal mixer
signatures as VIG0. This prioritizes their shared memory-fetch path over
a fault specific to one SSPP type.

A temporary module's attempt to enumerate all 128 SMMU stream-match
registers aborts at SMR[113] (physical 0x150009c4), before changing scanout
or translation. The USB shell survives, but the module remains in Loading
state and requires a forced reboot to clear it. Do not enumerate that
register range; restrict any subsequent check to the already captured,
readable entries and the display-owned context.

After a clean reboot, a restricted one-shot comparison allocates a
cache-cleaned 128 KiB DMA32 buffer at physical 0xb7800000 and maps it at
IOVA 0x20000000. Source and pixel-extension geometry are limited to 24
white rows, so both translated and physical accesses remain in that
allocation. Constant colour gives 0x3f90720c on both mixers. Normal
translation gives 0x4991cc74/0x27864040; disabling SCTLR.M only in the
display-owned context and using the physical address gives the same
abnormal pair. This does not support a simple scanout page-mapping error
as the cause. The original context control, source address and geometry
are restored, a new frame is confirmed, and the buffer is unmapped and
freed before the module is removed.

Read-only VBIF checks show no pending/source errors, memory-type values
0x33333333/0x00333333 matching the stock device-tree entries, and no client
halt request. The MDP core clock is already 500 MHz.

Holding DMA0's clock on, using the captured stock CREQ LUT or requesting
the maximum CREQ priority does not change the full-white memory
signatures. These settings and the original framebuffer are restored.
Black memory and constant black both give zero signatures; grey, white,
green and blue memory comparisons differ from their constant-colour
controls. Treat these as hardware observations, rather than a decoded
image or a proof that every colour component is represented in the MISR.

A separate temporary geometry probe compares constant white with the
same owned white buffer. The memory signatures for 1x1, 16x1 and 64x1
are zero, while constant colour gives a nonzero left signature. Wider
rectangles give differing nonzero memory signatures. A 5120-byte stride
also fails the 1240x24 comparison. Original geometry, stride and source
address are restored and the mapping/module are removed afterwards.

Correlated 256-byte read failures, 2026-10-21
------------------------------------------

A standard atomic writeback test uses the otherwise inactive CRTC 90,
primary plane 47 and writeback connector 36. TEST_ONLY passes before the
real commit. Its input is a completely white 640x64 XRGB8888 dumb buffer,
with a 2560-byte pitch. The writeback fence signals and all 163840 output
bytes are read back. Each row contains exactly 320 opaque black pixels
and 320 white pixels, alternating in runs of 64 pixels. Across the entire
output, byte offsets with bit 8 clear contain pixels 0xff000000; those
with bit 8 set contain 0xffffffff. There are no other pixel values. The
black pixels' written alpha distinguishes them from untouched zeroed
output memory. This reproduces the symptom without DSI or panel DSC.
Writeback is disabled afterwards and live DRM state confirms that the
original display remains on CRTC 89/DMA0, with CRTC 90 and its plane free.

A separate command test places the identical eight-byte embedded DCS
brightness packet at offsets 0, 0x80, 0x100, 0x180, 0x200 and 0x300 within
one cache-cleaned DMA32 page. The page is mapped at IOVA 0x30000000.
Each pass resets brightness through the working FIFO before trying
memory DMA, then checks the result through FIFO. Offsets 0, 0x80 and
0x200 leave readback at 8192. Offsets 0x100, 0x180 and 0x300 change it to
4096, matching successful transmission. Every pass reports DMA complete,
not busy, with no ACK error. Brightness is restored to 2048 (FIFO readback
8192), original DMA/interrupt settings are restored and the test mapping,
page and module are removed.

These two independent observations correlate scanout corruption and the
previous command-DMA failure with address bit 8. This is a shared-read-path
diagnostic result, not a verified cause or a workaround suitable for the
driver. A command-buffer offset alone cannot repair arbitrary scanout
data. The known ten-bit diagnostic images are retained while collecting
a targeted stock bus/cache configuration comparison.

Stock bus comparison, 2026-10-21
-------------------------------

The targeted stock capture keeps the display awake and disables command
encoder idle collapse while reading. HF/SF AXI clock gates both read 0x111
when the display is actually awake; earlier 0x80000110 readings were taken
after sleep and must not be used as the active comparison. Stock and
mainline MDSS UBWC controls agree at 0x103e/2/1. Captured VBIF memory types,
limits, error status and halt state do not identify a missing setting.

Stock APPS SMMU CR0/ACR read 0x00e30406/0x1c, compared with mainline
0x00230406/0x51c. A guarded temporary module compares the CR0 SHCFG change,
clearing ACR bits 0x500, and both together. None changes which DSI packet
offsets succeed. The ACR-only writeback still gives alternating 256-byte
black/white runs. With SHCFG changed, writeback becomes entirely opaque
black; restoring both registers restores the original alternating result.
This is a diagnostic side effect, not an improvement. All controls and
modules are restored or removed before further experiments.

The published Realme Ukee LLCC driver contains a different slice table
from SM8450. There is currently no LLCC device bound in this mainline DT.
A read-only probe obtains LLCC HW_INFO 0x03010000 and STATUS0 0x40400501.
CPU slice 1 and display slice 16 status both read 2; their ATTR0/ATTR1
registers are zero. These observations alone do not prove the cause.

The same probe then aborts at LLCC FEAC address 0x19241030. Do not read
that address or enumerate the surrounding range: a source-code register
definition is not evidence that current firmware permits the access.
The probe made no MMIO writes. A forced reboot clears its incomplete
Loading state, with the USB shell and ten-bit panel handoff verified again.
Further LLCC comparisons must be limited to the registers already read
successfully, and must establish stock state before proposing changes.

The stock vendor LLCC perfmon module binds successfully, but reading its
``perfmon_scid_status`` attribute disconnects USB before producing any
slice data. The user reboots Android; ADB returns and the temporary module
is gone. Pstore and /proc/last_kmsg provide no crash record, so the failing
address and exact reason remain unconfirmed. Do not repeat that interface
or infer a specific inaccessible bank from the disconnect.

The stock vendor_boot ramdisk contains the actual llcc-qcom module. Its
23-entry Ukee table is extracted offline and matches every initialized
field in Realme's published driver. New SM7475 LLCC support uses this table,
not SM8450's larger way masks and capacities. The DT declares the four
stock bank windows and broadcast window, but keeps the device disabled by
default. EDAC is deliberately not registered during this initial bring-up;
its register permissions have not been established. Only a separately
packaged diagnostic DTB enables the node. The 2026-10-21 12:15:17 kernel
boots with the node enabled and the qcom-llcc driver bound. The compiled
23-entry table matches all 22 initialized fields per entry in the stock
binary. Full build, DT binding documentation validation, LLCC-node schema
validation, AVB and kernel/DTB/USB-shell payload checks pass. The node schema
check also emits an existing nvmem-cells type-definition warning.

Writeback still produces 320 black and 320 white pixels per row; DSI still
succeeds only at offsets 0x100, 0x180 and 0x300. LLCC configuration alone is
therefore not a display fix. Both DMA0 and DMA1 SYS_CACHE_MODE already read
0x10, matching the captured stock no-allocation setting.

A further temporary command probe allocates a write-combined page through
``dma_alloc_wc`` on a private device using direct DMA32, then maps the owned
page into the display IOMMU domain. CPU packet readback is checked before
transmission. It reproduces the same offset-dependent successes and
failures as the manually cache-cleaned page. Original DMA/IRQ settings and
brightness are restored, and the page, mapping, device and module are
released. This does not support a fix consisting only of changing the CPU
buffer allocation or its cache-clean loop.

Source provenance:
https://github.com/realme-kernel-opensource/realme_GTNeo5SE-AndroidB-kernel-source/blob/master/drivers/soc/qcom/llcc_qcom.c

Additional read-path controls and rejected reset test
----------------------------------------------------

The stock SDE driver clears VBIF OUT_AXI_ASHARED/OUT_AXI_AINNERSHARED in
its memory-type setup, whereas mainline reads 0x3fff/0. A reversible
comparison clearing OUT_AXI_ASHARED does not repair the command offsets
or establish a repeatable writeback improvement. The original value is
restored. A bounded 1240x24 DMA0 white-source test also compares IOMMU_CACHE
off/on and XIN1 outer-shareable off/on. All four cases retain mixer
signatures 0x4991cc74/0x27864040, against constant-white 0x3f90720c on both
mixers. Source address, geometry and VBIF controls are restored, and the
owned allocation and mapping are freed.

The writeback tool now queries SYNC_IOC_FILE_INFO in addition to polling.
The baseline alternating-image capture reports fence status 1, success.
A two-job standard atomic comparison first writes an XRGB8888 image into
a middle buffer, then reuses that hardware-written buffer as an RGB565
source for a second output. The CPU does not modify the middle buffer
between the two jobs. In a valid capture both fences report success.
The middle buffer contains 20480 opaque black pixels. Its actual bytes
predict 448 coloured RGB565 pixels per row, but the second output has
only 256. All 192 incorrectly black pixels per row have source byte
address bit 8 clear; none have bit 8 set. All 64 rows agree. The RGB565
interpretation scales the affected output regions with source bytes,
strengthening the read-side diagnosis independently of CPU source writes.

Some repeated writeback attempts instead produce an all-zero first
buffer, even with a successful fence; their subsequent all-black outputs
are uninformative for this nonzero-data comparison. Preserve raw buffer
checks and distinguish these cases from the valid chained capture.

A separately packaged DTB removes only the MDSS reset property, keeping
the same kernel and panel parameters. It boots with USB, but DSI setup and
panel handoff time out, and the user reports a brief corrupted image then
black. The first white writeback is uniform, but a repeat is all black.
Do not treat that first result as proof that skipping reset fixes reads.
This experiment is rejected and the previous three images, including the
normal MDSS reset, are restored. The repository DT retains that reset.
The user confirms that the rollback restores the previous black-background
text display; the original missing strokes remain unresolved.

Full-page command and physical-address controls
----------------------------------------------

A further bounded command test fills every eight-byte location of an
owned write-combined page with a valid brightness packet before starting
any DMA. It checks all packet words through the CPU, then sends eight
bytes from offsets 0, 0x80, 0x100, 0x180, 0x200, 0x300, 0xe00, 0xf00 and
0xff8. A uniform-packet pass still fails at all tested bit-8-clear offsets
and succeeds at all tested bit-8-set offsets. Filling the surrounding
memory therefore does not rescue the failed offsets.

A second pass gives each 256-byte block a distinct brightness value.
Successful offsets execute their own block's value, including the last
packet in the page; failed offsets leave the FIFO-established brightness
unchanged. These results do not support a simple in-page address alias.
Both passes use DMA32 physical pages, at 0xb7800000 and 0xb7801000.

Repeating the distinct-packet pass with a 36-bit direct-DMA allocation
obtains physical page 0x804a97000, mapped to the same IOVA 0x30000000.
It gives the same offset-dependent results, so the observation is not
limited to the tested low physical-memory pages. All 27 commands complete
with IRQ 1, status 0 and ACK 0. Brightness is restored to 2048, with FIFO
readback 8192; DMA/interrupt settings are restored and all temporary
allocations, mappings and modules are released. USB remains available
with no new context fault, Oops or external abort. These are diagnostic
controls, not a verified repair or proof of a particular failed AXI port.

Display read-port isolation
--------------------------

A read-only check bounds SMR enumeration to the hardware-reported 113
groups. Both display SIDs, 0x2800 and 0x2c00, match only group 4
(SMR 0x84022800, S2CR 3). There is no duplicate matching route. CB3
CBAR/CBA2R are 0x1f300/1; TCR, TCR2 and the relevant MAIR0 match the
stock context. Clearing CB3 ACTLR.CMTLB temporarily, between two original
value controls, leaves the command-offset result unchanged. ACTLR 1 is
restored afterwards.

The stock vendor_boot's SM7475 DTB identifies the display TBUs at
0x151f9000 and 0x151fd000, covering SID ranges 0x2800 and 0x2c00.
Following the published driver's micro-idle sequence, setting only bits
10/11 in APPS_SMMU_TBU_REG_ACCESS_REQ_NS obtains matching ACK bits.
Holding both TBUs awake does not repair command DMA. Request and ACK
return to their original zero values when the control is removed.
Access to TBU local registers is performed only after this handshake.

A bounded ECATS test maps one owned DMA32 page and checks IOVAs
0x30000000 and 0x30000100 through each TBU. All four hardware translations
return the expected physical byte addresses, with no context fault.
For a page at 0xb7802000, the raw PAR values are 0x33000b7802000b82 and
0x33000b7802100b82 on both TBUs. The initial diagnostic's match flag used
an incorrect unshifted mask; the correct downstream decoding is
FIELD_GET(GENMASK_ULL(47, 12), PAR), yielding the full physical byte address.
A corrected repeat confirms all four matches. Halt, debug request, context
control and wake settings are restored and the page/mapping are released.
The subsequent command-DMA control still fails at bit-8-clear offsets.

To identify the actual command path, a separate bounded control pauses
one TBU for approximately one millisecond during each eight-byte DMA.
Holding TBU0 stalls offset 0 (DSI STATUS 3, completion IRQ 0), while offset
0x100 completes. Holding TBU1 does the reverse. After resuming the held
TBU, every transfer completes with STATUS 0, IRQ 1 and ACK 0. Offset 0
still fails the brightness check; offset 0x100 succeeds. Thus the failing
command is associated with display read path 0/SID 0x2800, while the
working command uses path 1/SID 0x2c00. This is stronger than inferring a
port from address striping alone. It does not establish which component
or configuration on path 0 causes the data failure.

A normal HF interconnect request, separate from the existing virtual
display HF requests, is also tested at peak 2500000 kB/s. The request is
visible through MDP, MNOC HF, LLCC and EBI; pending sync-state constraints
raise the displayed aggregate to INT_MAX. The DMA-offset failure remains.
The request and overlay are removed and the original virtual path is
refreshed. Forcing the VBIF core clock using the stock debug driver's
CLKON bit 1 likewise does not repair the offsets; CLKON is restored to 0.
All temporary modules are removed and brightness is restored. No new
Oops, external abort or context fault is observed during these controls.

A subsequent QoS reader contains an address-arithmetic error: MMSS base
0x01740000 plus offset 0x16008 is incorrectly written as 0x17416008.
That read causes an external abort after the TBU wake state has already
been restored. The USB shell remains available; logs are saved and a forced
reboot clears the incomplete module load. Do not classify this as a NoC
permission failure. The corrected reader obtains bases from DT resources,
checks resource bounds and adds offsets, rather than concatenating hex
digits. The correct MMSS addresses 0x01756008/0x01756088 and GEM addresses
0x19121008/0x19161008 all read successfully, each returning 0x00020008.
The helper unloads normally. A corresponding stock 5.10.236 build uses
the stock Clang r416183b, retains CFI and passes checks of all 19 import
CRCs against the original ramdisk modules and the 1024-byte module layout.
The stock helper subsequently loads and unloads successfully on the actual
5.10.236 kernel. With encoder idle power collapse disabled and the display
awake, both stock TBUs have CTRL 0x94120000, STATUS 0x00100000 and zero debug
VA/TRIGGER/PAR/AXUSER, matching a clean mainline capture. All four stock
NoC QoS words also read 0x00020008. Wake request/ACK return to zero and the
original debugfs selectors and idle setting are restored. No new Oops,
external abort, CFI or module-version error is observed.

The stock driver's VBIF debugfs captures the full 0x1040-byte range. All
1040 words are compared against the bounded mainline snapshot. There are
29 differences: OUT_AXI_ASHARED and 28 QoS-remap words between offsets
0x550 and 0x5cc. All other captured words agree. A reversible mainline
comparison installs and verifies the complete 32-word stock QoS tables,
including unchanged entries, and clears OUT_AXI_ASHARED. Nine uniform
brightness commands are checked before, during and after the replacement.
All 27 retain the same bit-8-dependent failure; every transfer completes
with STATUS 0, IRQ 1 and ACK 0. Original QoS tables and shared attributes
are restored and temporary modules are unloaded. This does not support a
repair consisting only of copying the captured VBIF configuration.

Verified MDSS reset-order fix
----------------------------

The original MDSS initialization pulses reset before acquiring and enabling
the MDSS clocks. A separate comparison retains the same 20 ms reset pulse,
enabling the four DT-listed MDSS clocks around it. Boot confirms all four
clock enables and successful reset deassertion. The optional status query
returns -ENOTSUPP because the Qcom reset provider has no status operation;
this is not a failed deassertion.

On the 2026-10-21 14:09:06 diagnostic kernel, all nine uniform brightness
packets pass, including the formerly failing path-0 offsets. The user
confirms normal text with no horizontal lines or missing strokes. Following
a user-confirmed manual reboot, eighteen distinct packets using DMA32 and
36-bit physical addresses all execute their own data correctly. A further
nine-command control after writeback also passes. The restart was manual,
not evidence of an automatic crash.

A valid 640x64 writeback contains 40960 opaque white pixels. A separate
hardware-producer/consumer chain writes an XRGB8888 middle buffer and reuses
it as RGB565 input without CPU modification. Both fences report success,
all 64 rows match, and middle/output are both all 0xffffffff, SHA256
5639b95c2f8d2a2d92aa71f3c2414032aff8b9cbfa2f63e252461f70df35da84.
The old 256-byte missing-source pattern is absent from these valid outputs.
One ordinary repeated writeback instead times out and leaves an all-zero
output despite its signaled fence. That untouched buffer is not a valid
read-correctness result; repeated writeback completion still needs work.

The regular DSI driver also reads brightness with FIFO disabled. With a
one-second settling interval, both its normal DMA and FIFO paths apply
brightness 1024/2048 and read 4096/8192, matching this panel's existing
readback convention. Immediate reads can still show the previous value.
FIFO remains enabled in the known working profile, and brightness is
restored to 2048. All temporary modules are unloaded. An earlier shell
redirection failed to expand a wildcard, so those two attempted writes are
not counted. The original console reader also stops after short output
gaps; delayed tests use a completion marker instead.

The verified reset sequence is now automatic for root compatible
``qcom,ukee`` with device compatible ``qcom,sm8450-mdss``. ABL replaces the
root compatibles with ``qcom,ukee-mtp``, ``qcom,ukee`` and ``qcom,mtp``, so
the source DTS's Realme string cannot guard it. Clock acquisition/enable
and reset errors abort initialization, and clock references are released
on exit. Other platforms retain their reset clock sequence. No extra reset
parameter is required; the old opt-in fragment/parameter is removed.
The test establishes the required sequencing, not which individual clock
is sufficient or the underlying RTL failure. Keep the normal MDSS reset;
the earlier no-reset experiment remains rejected.

The normal board config now selects the already validated panel handoff
and dynamic plane allocation. LLCC remains disabled in the source DT, as
before; the first successful image used the archived LLCC diagnostic DTB.
Evidence is in ``out/display-evidence/stock-llcc-20261021/clocked-reset-*``.

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
