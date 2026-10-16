// SPDX-License-Identifier: GPL-2.0-only
/*
 * Realme GT Neo5 SE (Qualcomm SM7475) bring-up: hand the kernel the
 * framebuffer the bootloader already set up.
 *
 * Why this exists instead of a /chosen/simple-framebuffer DT node:
 * this device's bootloader refuses any modification of the DTBs it feeds the
 * kernel.  vendor_boot must stay byte-identical (replacing any of its DTBs
 * makes the bootloader drop straight back to fastboot), and an extra dtbo
 * entry we add is not applied either - so a DT node can never be injected and
 * no framebuffer device is ever created, leaving the panel frozen on the
 * bootloader logo with no console output at all.
 *
 * The panel, however, keeps scanning the splash buffer the bootloader filled in
 * (its reserved-memory "splash_region", which the runtime DTB reports as
 * 0xb8000000 / 0x2b00000).  Registering a plain "simple-framebuffer" platform
 * device from C is therefore enough to obtain an fbdev, and with console=tty0
 * in the kernel command line fbcon prints dmesg on screen from early boot -
 * with no bootloader cooperation required.
 *
 * simplefb takes the geometry from the platform data (simplefb_parse_pd()) and
 * the physical address from resource 0 (IORESOURCE_MEM).
 */

#include <linux/init.h>
#include <linux/io.h>
#include <linux/ioport.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/platform_data/simplefb.h>
#include <linux/platform_device.h>

#define SM7475_SPLASHFB_BASE	0xb8000000
#define SM7475_SPLASHFB_SIZE	0x02b00000
#define SM7475_SPLASHFB_WIDTH	1240
#define SM7475_SPLASHFB_HEIGHT	2772
#define SM7475_SPLASHFB_STRIDE	(SM7475_SPLASHFB_WIDTH * 4)
#define SM7475_SPLASHFB_FORMAT	"a8r8g8b8"

/*
 * Poor man's console for bring-up: since no kernel log ever reaches the panel
 * on this device, the kernel reports its own progress by painting the splash
 * buffer.  The colour the panel ends up showing therefore tells us how far the
 * kernel got:
 *	blue	- reached early_initcall (ioremap works, address is scanned)
 *	green	- reached arch_initcall (past all the low-level SoC setup)
 *	nothing	- never got there, or 0xb8000000 is not what the panel scans
 * (pixel encoding follows the a8r8g8b8 format: AARRGGBB)
 */
#define SM7475_FB_BLUE	0xff0000ff
#define SM7475_FB_GREEN	0xff00ff00

static void __init sm7475_splashfb_paint(u32 px)
{
	/*
	 * 0xb8000000 is part of the kernel linear map (splash_region is reserved
	 * but not "no-map"), so use phys_to_virt - ioremap() could return NULL
	 * and fail silently, which is exactly the kind of thing we must not have
	 * in a self-reporting bring-up aid.
	 */
	void __iomem *fb = (void __iomem *)phys_to_virt(SM7475_SPLASHFB_BASE);
	u32 i, n = SM7475_SPLASHFB_WIDTH * SM7475_SPLASHFB_HEIGHT;

	for (i = 0; i < n; i++)
		writel(px, fb + i * 4);
}

static int __init sm7475_splashfb_early(void)
{
	sm7475_splashfb_paint(SM7475_FB_BLUE);
	return 0;
}
early_initcall(sm7475_splashfb_early);

static struct simplefb_platform_data sm7475_splashfb_pdata = {
	.width	= SM7475_SPLASHFB_WIDTH,
	.height	= SM7475_SPLASHFB_HEIGHT,
	.stride	= SM7475_SPLASHFB_STRIDE,
	.format	= SM7475_SPLASHFB_FORMAT,
};

static struct resource sm7475_splashfb_res =
	DEFINE_RES_MEM(SM7475_SPLASHFB_BASE, SM7475_SPLASHFB_SIZE);

static struct platform_device sm7475_splashfb_dev = {
	.name		= "simple-framebuffer",
	.id		= 0,
	.num_resources	= 1,
	.resource	= &sm7475_splashfb_res,
	.dev		= {
		.platform_data = &sm7475_splashfb_pdata,
	},
};

static int __init sm7475_splashfb_init(void)
{
	sm7475_splashfb_paint(SM7475_FB_GREEN);
	return platform_device_register(&sm7475_splashfb_dev);
}
arch_initcall(sm7475_splashfb_init);

MODULE_DESCRIPTION("Realme GT Neo5 SE (SM7475) bootloader splash framebuffer");
MODULE_LICENSE("GPL");
