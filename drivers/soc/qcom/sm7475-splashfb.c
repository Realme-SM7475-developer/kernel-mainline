// SPDX-License-Identifier: GPL-2.0-only
/*
 * Realme GT Neo5 SE (Qualcomm SM7475) bring-up console on the bootloader
 * splash buffer.
 *
 * Why this exists instead of a /chosen/simple-framebuffer DT node:
 * this device's bootloader refuses any modification of the DTBs it feeds the
 * kernel.  vendor_boot must stay byte-identical (replacing any of its DTBs
 * makes the bootloader drop straight back to fastboot), and an extra dtbo
 * entry we add is not applied either - so a DT framebuffer node can never be
 * injected and no fbdev is ever created, leaving the panel frozen on the
 * bootloader logo with no kernel log at all.  simplefb's platform-device path
 * is registered below as well, but the probe evidently does not produce a
 * usable fbdev here, so the console below does not depend on it.
 *
 * What does work - and is proven on hardware - is writing straight into the
 * linear mapping of the buffer the panel is still scanning (the bootloader's
 * reserved-memory "splash_region", 0xb8000000 / 0x2b00000): a cheap paint
 * shows up on the panel immediately.  So this file registers a real
 * "struct console" and renders that buffer itself with the in-kernel 8x16
 * font.  printk then feeds it like any other console, and CON_PRINTBUFFER
 * replays the whole backlog at registration, which is what finally makes
 * dmesg visible on screen.
 *
 * Pixel encoding follows the a8r8g8b8 format (AARRGGBB).
 */

#include <linux/console.h>
#include <linux/font.h>
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

/* 8x16 glyphs drawn at 2x so they are readable on a 6.7" 1240x2772 panel */
#define SM7475_GLYPH_W		8
#define SM7475_GLYPH_H		16
#define SM7475_SCALE		2

#define SM7475_COLS		(SM7475_SPLASHFB_WIDTH / (SM7475_GLYPH_W * SM7475_SCALE))
#define SM7475_ROWS		(SM7475_SPLASHFB_HEIGHT / (SM7475_GLYPH_H * SM7475_SCALE))

#define SM7475_FG		0xffffffff
#define SM7475_BG		0xff000000

static void __iomem *sm7475_fb;
static const u8 *sm7475_font;
static u32 sm7475_col, sm7475_row;

static void sm7475_put_block(u32 x, u32 y, u32 px)
{
	u32 dx, dy;

	for (dy = 0; dy < SM7475_SCALE; dy++)
		for (dx = 0; dx < SM7475_SCALE; dx++)
			writel(px, sm7475_fb + (y + dy) * SM7475_SPLASHFB_STRIDE +
				      (x + dx) * 4);
}

static void sm7475_fill_rows(u32 first_row, u32 last_row, u32 px)
{
	u32 x, y;

	for (y = first_row * SM7475_GLYPH_H * SM7475_SCALE;
	     y < last_row * SM7475_GLYPH_H * SM7475_SCALE; y++)
		for (x = 0; x < SM7475_SPLASHFB_WIDTH; x++)
			writel(px, sm7475_fb + y * SM7475_SPLASHFB_STRIDE + x * 4);
}

static void sm7475_draw_char(u8 c, u32 col, u32 row)
{
	const u8 *glyph = sm7475_font + (u32)c * SM7475_GLYPH_H;
	u32 gx, gy;
	u32 x0 = col * SM7475_GLYPH_W * SM7475_SCALE;
	u32 y0 = row * SM7475_GLYPH_H * SM7475_SCALE;

	for (gy = 0; gy < SM7475_GLYPH_H; gy++) {
		u8 bits = glyph[gy];

		for (gx = 0; gx < SM7475_GLYPH_W; gx++)
			sm7475_put_block(x0 + gx * SM7475_SCALE,
					y0 + gy * SM7475_SCALE,
					(bits & (0x80 >> gx)) ? SM7475_FG : SM7475_BG);
	}
}

static void sm7475_scroll(void)
{
	/* copy each pixel forward: dst is below src, so this cannot overlap */
	u32 shift = SM7475_GLYPH_H * SM7475_SCALE * SM7475_SPLASHFB_WIDTH;
	u32 total = SM7475_SPLASHFB_HEIGHT * SM7475_SPLASHFB_WIDTH;
	u32 i;

	for (i = 0; i < total - shift; i++)
		writel(readl(sm7475_fb + (i + shift) * 4), sm7475_fb + i * 4);

	sm7475_fill_rows(SM7475_ROWS - 1, SM7475_ROWS, SM7475_BG);
}

static void sm7475_console_write(struct console *co, const char *s, unsigned int n)
{
	unsigned int i;

	if (!sm7475_fb)
		return;

	for (i = 0; i < n; i++) {
		u8 c = s[i];

		switch (c) {
		case '\n':
			sm7475_col = 0;
			sm7475_row++;
			break;
		case '\r':
			sm7475_col = 0;
			break;
		case '\t':
			sm7475_col = (sm7475_col + 8) & ~7U;
			break;
		default:
			if (c >= 32) {
				sm7475_draw_char(c, sm7475_col, sm7475_row);
				sm7475_col++;
			}
			break;
		}

		if (sm7475_col >= SM7475_COLS) {
			sm7475_col = 0;
			sm7475_row++;
		}
		while (sm7475_row >= SM7475_ROWS) {
			sm7475_scroll();
			sm7475_row--;
		}
	}
}

static struct console sm7475_console = {
	.name	= "sm7475fb",
	.write	= sm7475_console_write,
	.flags	= CON_PRINTBUFFER | CON_ENABLED,
	.index	= -1,
};

static int __init sm7475_splashfb_init(void)
{
	sm7475_fb = (void __iomem *)phys_to_virt(SM7475_SPLASHFB_BASE);
	sm7475_font = font_vga_8x16.data;
	if (!sm7475_fb || !sm7475_font)
		return 0;

	sm7475_fill_rows(0, SM7475_ROWS, SM7475_BG);
	register_console(&sm7475_console);

	return 0;
}
early_initcall(sm7475_splashfb_init);

/*
 * Also try the regular path, in case simplefb eventually probes: harmless if
 * it does not, and if it does, fbcon takes over the same buffer.
 */
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

static int __init sm7475_simplefb_register(void)
{
	return platform_device_register(&sm7475_splashfb_dev);
}
arch_initcall(sm7475_simplefb_register);

MODULE_DESCRIPTION("Realme GT Neo5 SE (SM7475) bootloader splash framebuffer console");
MODULE_LICENSE("GPL");
