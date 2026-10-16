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
 * bootloader logo with no kernel log at all.
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
 * This console must be the *only* writer of that buffer.  An earlier revision
 * also registered a "simple-framebuffer" platform device, which made simplefb
 * probe and fbcon bind fb0 to the very same physical pixels; two consoles
 * interleaving writes into one buffer the panel is already scanning is exactly
 * what produced the snowflake tearing, and fbcon's own redraws kept scrolling
 * our text away.  FB_SIMPLE and FRAMEBUFFER_CONSOLE are therefore off and no
 * platform device is created - nothing else may touch these pixels.
 *
 * Rendering model - why a shadow buffer:
 * the panel keeps scanning this buffer while we draw into it.  Two things
 * go wrong if we paint it pixel by pixel:
 *   - the panel reads the same DRAM we are writing, so any intermediate
 *     state it samples shows up as tearing;
 *   - through a cacheable mapping our stores sit in the CPU cache and the
 *     display controller only sees them whenever the lines happen to be
 *     evicted, which is the "ghosting that clears once drawing stops".
 * So all rendering (clear, glyphs, scroll) is done on a cacheable RAM shadow
 * with plain memset/memcpy, we remember which pixel rows changed, and after
 * each console_write() only those rows are pushed to the display buffer in a
 * single write-combining memcpy_toio() burst.  The window during which the
 * scanned-out buffer differs from the finished image is then as short as it
 * can be, and every store has provably left the CPU caches.
 *
 * Pixel encoding follows the a8r8g8b8 format (AARRGGBB).
 */

#include <linux/console.h>
#include <linux/font.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/string.h>
#include <linux/vmalloc.h>

#define SM7475_SPLASHFB_BASE	0xb8000000
#define SM7475_SPLASHFB_SIZE	0x02b00000
#define SM7475_SPLASHFB_WIDTH	1240
#define SM7475_SPLASHFB_HEIGHT	2772
#define SM7475_SPLASHFB_STRIDE	(SM7475_SPLASHFB_WIDTH * 4)

/* visible framebuffer size: the reserved region is larger, we only touch this */
#define SM7475_SPLASHFB_FBSIZE	(SM7475_SPLASHFB_STRIDE * SM7475_SPLASHFB_HEIGHT)

/* 8x16 glyphs drawn at 2x so they are readable on a 6.7" 1240x2772 panel */
#define SM7475_GLYPH_W		8
#define SM7475_GLYPH_H		16
#define SM7475_SCALE		2

/* one text row in pixels */
#define SM7475_TEXT_H		(SM7475_GLYPH_H * SM7475_SCALE)

#define SM7475_COLS		(SM7475_SPLASHFB_WIDTH / (SM7475_GLYPH_W * SM7475_SCALE))
#define SM7475_ROWS		(SM7475_SPLASHFB_HEIGHT / SM7475_TEXT_H)

#define SM7475_FG		0xffffffff
#define SM7475_BG		0xff000000

static void __iomem *sm7475_fb;
static u32 *sm7475_shadow;		/* cacheable RAM copy we render into */
static const u8 *sm7475_font;
static u32 sm7475_col, sm7475_row;

/* pixel rows that differ from what the panel currently shows; [first, last) */
static u32 sm7475_dirty_first = SM7475_SPLASHFB_HEIGHT;
static u32 sm7475_dirty_last;

static void sm7475_mark_dirty(u32 first_px, u32 last_px)
{
	if (first_px < sm7475_dirty_first)
		sm7475_dirty_first = first_px;
	if (last_px > sm7475_dirty_last)
		sm7475_dirty_last = last_px;
}

static void sm7475_fill_rows(u32 first_row, u32 last_row, u32 px)
{
	u32 y0 = first_row * SM7475_TEXT_H;
	u32 y1 = last_row * SM7475_TEXT_H;
	u32 y;

	for (y = y0; y < y1; y++)
		memset32(sm7475_shadow + (size_t)y * SM7475_SPLASHFB_WIDTH,
			 px, SM7475_SPLASHFB_WIDTH);

	sm7475_mark_dirty(y0, y1);
}

static void sm7475_draw_char(u8 c, u32 col, u32 row)
{
	const u8 *glyph = sm7475_font + (u32)c * SM7475_GLYPH_H;
	u32 gx, gy;
	u32 x0 = col * SM7475_GLYPH_W * SM7475_SCALE;
	u32 y0 = row * SM7475_TEXT_H;

	for (gy = 0; gy < SM7475_GLYPH_H; gy++) {
		u8 bits = glyph[gy];
		u32 *line = sm7475_shadow + (size_t)(y0 + gy * SM7475_SCALE) *
					    SM7475_SPLASHFB_WIDTH + x0;

		for (gx = 0; gx < SM7475_GLYPH_W; gx++) {
			u32 px = (bits & (0x80 >> gx)) ? SM7475_FG : SM7475_BG;
			u32 dx;

			/* paint the 2x2 block for this font pixel */
			for (dx = 0; dx < SM7475_SCALE; dx++) {
				line[gx * SM7475_SCALE + dx] = px;
				line[SM7475_SPLASHFB_WIDTH +
				     gx * SM7475_SCALE + dx] = px;
			}
		}
	}

	sm7475_mark_dirty(y0, y0 + SM7475_TEXT_H);
}

static void sm7475_scroll(void)
{
	u32 shift = SM7475_TEXT_H * SM7475_SPLASHFB_WIDTH;
	size_t total = (size_t)SM7475_SPLASHFB_HEIGHT * SM7475_SPLASHFB_WIDTH;

	/* dst is below src, so a forward move cannot overlap */
	memmove(sm7475_shadow, sm7475_shadow + shift, (total - shift) * 4);
	sm7475_fill_rows(SM7475_ROWS - 1, SM7475_ROWS, SM7475_BG);

	/* the whole panel shifted, so everything has to be pushed out again */
	sm7475_mark_dirty(0, SM7475_SPLASHFB_HEIGHT);
}

/*
 * Push the changed rows out in one write-combining burst.  memcpy_toio() over
 * a WC ioremap is a single linear stream of full-line stores, so the panel (and
 * the DRAM the display controller reads) sees each row either old or new, never
 * a partially-written mix - and nothing is left behind in the CPU cache.
 */
static void sm7475_flush(void)
{
	size_t off, len;

	if (!sm7475_fb)
		return;
	if (sm7475_dirty_first >= sm7475_dirty_last) {
		sm7475_dirty_first = SM7475_SPLASHFB_HEIGHT;
		sm7475_dirty_last = 0;
		return;
	}

	off = (size_t)sm7475_dirty_first * SM7475_SPLASHFB_STRIDE;
	len = (size_t)(sm7475_dirty_last - sm7475_dirty_first) *
	      SM7475_SPLASHFB_STRIDE;
	memcpy_toio(sm7475_fb + off, (const u8 *)sm7475_shadow + off, len);

	sm7475_dirty_first = SM7475_SPLASHFB_HEIGHT;
	sm7475_dirty_last = 0;
}

static void sm7475_console_write(struct console *co, const char *s, unsigned int n)
{
	unsigned int i;

	if (!sm7475_fb || !sm7475_shadow)
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

	sm7475_flush();
}

static struct console sm7475_console = {
	.name	= "sm7475fb",
	.write	= sm7475_console_write,
	.flags	= CON_PRINTBUFFER | CON_ENABLED,
	.index	= -1,
};

static void __iomem *sm7475_map(void)
{
	/*
	 * Only ioremap_wc() can produce a mapping here.  memremap() refuses
	 * outright: the region is reported as IORESOURCE_SYSTEM_RAM, and
	 * memremap() WARN_ONCE()s and returns -ENXIO for any RAM region, so it
	 * would only ever add a spurious warning to the log.  A write-combining
	 * mapping is what we want anyway - it is uncached, so nothing we draw
	 * lingers in the CPU cache waiting for an eviction the display
	 * controller never waits for.  Fall back to phys_to_virt() so a mapping
	 * failure cannot silently blank the screen again.
	 */
	void __iomem *p = ioremap_wc(SM7475_SPLASHFB_BASE, SM7475_SPLASHFB_SIZE);

	return p ? p : (void __iomem *)phys_to_virt(SM7475_SPLASHFB_BASE);
}

static int __init sm7475_splashfb_init(void)
{
	sm7475_font = font_vga_8x16.data;
	sm7475_shadow = vzalloc(SM7475_SPLASHFB_FBSIZE);
	sm7475_fb = sm7475_map();
	if (!sm7475_shadow || !sm7475_fb || !sm7475_font)
		return 0;

	/* start from a clean, all-background image both in RAM and on screen */
	sm7475_fill_rows(0, SM7475_ROWS, SM7475_BG);
	sm7475_flush();
	register_console(&sm7475_console);

	return 0;
}
early_initcall(sm7475_splashfb_init);

MODULE_DESCRIPTION("Realme GT Neo5 SE (SM7475) bootloader splash framebuffer console");
MODULE_LICENSE("GPL");
