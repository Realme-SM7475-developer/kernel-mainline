// SPDX-License-Identifier: GPL-2.0-only
/* Realme GT Neo5 SE / Senna NT37705 DSI panel. */

#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/regulator/consumer.h>

#include <video/mipi_display.h>

#include <drm/display/drm_dsc.h>
#include <drm/display/drm_dsc_helper.h>
#include <drm/drm_mipi_dsi.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <drm/drm_probe_helper.h>

struct realme_nt37705 {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct drm_dsc_config dsc;
	struct gpio_desc *reset_gpio;
	struct regulator_bulk_data supplies[4];
};

static inline struct realme_nt37705 *to_realme_nt37705(struct drm_panel *panel)
{
	return container_of(panel, struct realme_nt37705, panel);
}

static void realme_nt37705_reset(struct realme_nt37705 *ctx)
{
	gpiod_set_value_cansleep(ctx->reset_gpio, 0);
	usleep_range(2000, 2500);
	gpiod_set_value_cansleep(ctx->reset_gpio, 1);
	usleep_range(2000, 2500);
	gpiod_set_value_cansleep(ctx->reset_gpio, 0);
	msleep(20);
}

static int realme_nt37705_on(struct realme_nt37705 *ctx)
{
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };

	ctx->dsi->mode_flags |= MIPI_DSI_MODE_LPM;

	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x55, 0xaa, 0x52, 0x08, 0x07);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb4, 0xc0, 0x80, 0x80, 0x80,
				     0x80, 0x50, 0x80, 0x80, 0x80, 0x80, 0x80,
				     0x50, 0x80);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x55, 0xaa, 0x52, 0x08, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x02);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xbe, 0x49, 0x4c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x55, 0xaa, 0x52, 0x08, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x07);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb5, 0x4e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb5, 0x80);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x2c);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xb5, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x19);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfb, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x05);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfe, 0x34);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x80);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x1a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf4, 0x55);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x83);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x12);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfe, 0x41);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x5f, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x26, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x26, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x17, 0x10);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x2a, 0x00, 0x00, 0x04, 0xd7);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x2b, 0x00, 0x00, 0x0a, 0xd3);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x2f, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x35, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x44, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x51, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x04);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x51, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x53, 0x20);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x90, 0x03, 0x03);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x91,
				     0xab, 0x28, 0x00, 0x0c, 0xf2, 0x00, 0x02,
				     0x85, 0x01, 0x0f, 0x00, 0x08, 0x0a, 0xe9,
				     0x07, 0x5f, 0x10, 0xf0);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x24);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfb,
				     0x00, 0x03, 0x04, 0x55, 0x77, 0x77, 0x77,
				     0x99, 0x9d, 0x00, 0x00, 0x06, 0x88, 0x9a, 0xbb,
				     0xbc, 0xde, 0xef, 0xf0, 0x11);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x0e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf5, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x80);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x0f);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfc, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x09);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfc, 0xfc, 0xf0);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x80);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x0a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf6, 0x70, 0x70, 0x70);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x0e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf6, 0x60);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x80);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x11);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf8, 0x01, 0x8e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x2d);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf8, 0x00, 0xfc);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x1f, 0x06);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x1e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfb, 0x0f);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x83);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x12);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xfe, 0x41);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x80);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x19);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf2, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xff, 0xaa, 0x55, 0xa5, 0x81);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x02);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf9, 0x04);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x5a, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x55, 0xaa, 0x52, 0x08, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xd2, 0x00, 0x00, 0x00, 0x00, 0x15);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x05);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xd2, 0x01, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x0e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xd2, 0x02, 0x00, 0x10, 0x05, 0x88);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xe4,
				     0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
				     0x00, 0x00, 0x33);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x0a);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xe4, 0x80, 0x00, 0x00, 0x10, 0x00, 0x53);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x55, 0xaa, 0x52, 0x08, 0x01);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0x0e);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xd2, 0x02, 0x00, 0x10, 0x05, 0x82);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x11, 0x00);
	mipi_dsi_msleep(&dsi_ctx, 128);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xf0, 0x55, 0xaa, 0x52, 0x08, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x2f, 0x00);
	mipi_dsi_msleep(&dsi_ctx, 17);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xbe, 0x47);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0xa8);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6f, 0xb0);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0xba, 0x00, 0x00, 0x00, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x2f, 0x30);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x6d, 0x00);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, 0x35, 0x00, 0x00, 0x00, 0x00);
	mipi_dsi_dcs_set_display_on_multi(&dsi_ctx);

	return dsi_ctx.accum_err;
}


static int realme_nt37705_off(struct realme_nt37705 *ctx)
{
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };

	ctx->dsi->mode_flags &= ~MIPI_DSI_MODE_LPM;
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, MIPI_DCS_SET_DISPLAY_OFF);
	mipi_dsi_msleep(&dsi_ctx, 20);
	mipi_dsi_dcs_write_seq_multi(&dsi_ctx, MIPI_DCS_ENTER_SLEEP_MODE);
	mipi_dsi_msleep(&dsi_ctx, 120);

	return dsi_ctx.accum_err;
}

static int realme_nt37705_prepare(struct drm_panel *panel)
{
	struct realme_nt37705 *ctx = to_realme_nt37705(panel);
	struct mipi_dsi_multi_context dsi_ctx = { .dsi = ctx->dsi };
	struct drm_dsc_picture_parameter_set pps;
	int ret;

	ret = regulator_bulk_enable(ARRAY_SIZE(ctx->supplies), ctx->supplies);
	if (ret)
		return ret;

	/* The stock panel supply table gives extvdd a 10 ms post-on delay. */
	msleep(10);

	realme_nt37705_reset(ctx);
	ret = realme_nt37705_on(ctx);
	if (ret < 0) {
		dev_err(panel->dev, "panel initialization commands failed: %d\n", ret);
		goto err_disable_supplies;
	}

	/* This panel accepts PPS and DSC enable after its vendor init sequence. */
	drm_dsc_pps_payload_pack(&pps, &ctx->dsc);
	mipi_dsi_picture_parameter_set_multi(&dsi_ctx, &pps);
	mipi_dsi_compression_mode_multi(&dsi_ctx, true);
	ret = dsi_ctx.accum_err;
	if (ret < 0) {
		dev_err(panel->dev, "failed to configure DSC: %d\n", ret);
		goto err_disable_supplies;
	}

	msleep(28);
	return 0;

err_disable_supplies:
	gpiod_set_value_cansleep(ctx->reset_gpio, 1);
	regulator_bulk_disable(ARRAY_SIZE(ctx->supplies), ctx->supplies);
	return ret;
}

static int realme_nt37705_unprepare(struct drm_panel *panel)
{
	struct realme_nt37705 *ctx = to_realme_nt37705(panel);

	realme_nt37705_off(ctx);
	gpiod_set_value_cansleep(ctx->reset_gpio, 1);
	regulator_bulk_disable(ARRAY_SIZE(ctx->supplies), ctx->supplies);

	return 0;
}

static const struct drm_display_mode realme_nt37705_mode = {
	.clock = 455016,
	.hdisplay = 1240,
	.hsync_start = 1304,
	.hsync_end = 1312,
	.htotal = 1362,
	.vdisplay = 2772,
	.vsync_start = 2774,
	.vsync_end = 2776,
	.vtotal = 2784,
	.width_mm = 70,
	.height_mm = 156,
	.type = DRM_MODE_TYPE_DRIVER,
};

static int realme_nt37705_get_modes(struct drm_panel *panel,
					struct drm_connector *connector)
{
	return drm_connector_helper_get_modes_fixed(connector, &realme_nt37705_mode);
}

static const struct drm_panel_funcs realme_nt37705_panel_funcs = {
	.prepare = realme_nt37705_prepare,
	.unprepare = realme_nt37705_unprepare,
	.get_modes = realme_nt37705_get_modes,
};

static int realme_nt37705_bl_update_status(struct backlight_device *bl)
{
	struct mipi_dsi_device *dsi = bl_get_data(bl);
	int ret;

	dsi->mode_flags &= ~MIPI_DSI_MODE_LPM;
	ret = mipi_dsi_dcs_set_display_brightness_large(dsi,
							 backlight_get_brightness(bl));
	dsi->mode_flags |= MIPI_DSI_MODE_LPM;

	return ret;
}

static const struct backlight_ops realme_nt37705_bl_ops = {
	.update_status = realme_nt37705_bl_update_status,
};

static int realme_nt37705_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	struct realme_nt37705 *ctx;
	struct backlight_properties props = {
		.type = BACKLIGHT_RAW,
		.max_brightness = 4095,
		.brightness = 1024,
	};
	int ret;

	ctx = devm_drm_panel_alloc(dev, struct realme_nt37705, panel,
				  &realme_nt37705_panel_funcs,
				  DRM_MODE_CONNECTOR_DSI);
	if (IS_ERR(ctx))
		return PTR_ERR(ctx);

	ctx->supplies[0].supply = "vddio";
	ctx->supplies[1].supply = "extvdd";
	ctx->supplies[2].supply = "vci";
	ctx->supplies[3].supply = "avdd";
	ret = devm_regulator_bulk_get(dev, ARRAY_SIZE(ctx->supplies), ctx->supplies);
	if (ret)
		return dev_err_probe(dev, ret, "failed to get panel supplies\n");

	ctx->reset_gpio = devm_gpiod_get(dev, "reset", GPIOD_OUT_HIGH);
	if (IS_ERR(ctx->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(ctx->reset_gpio),
				     "failed to get reset GPIO\n");

	ctx->dsi = dsi;
	dsi->lanes = 4;
	dsi->format = MIPI_DSI_FMT_RGB888;
	dsi->mode_flags = MIPI_DSI_MODE_NO_EOT_PACKET |
			  MIPI_DSI_CLOCK_NON_CONTINUOUS;
	dsi->dsc = &ctx->dsc;
	ctx->dsc.dsc_version_major = 1;
	ctx->dsc.dsc_version_minor = 1;
	ctx->dsc.slice_height = 12;
	ctx->dsc.slice_width = 620;
	ctx->dsc.slice_count = 2;
	ctx->dsc.bits_per_component = 10;
	ctx->dsc.bits_per_pixel = 8 << 4;
	ctx->dsc.block_pred_enable = true;

	ctx->panel.prepare_prev_first = true;
	ctx->panel.backlight = devm_backlight_device_register(dev, dev_name(dev),
							     dev, dsi,
							     &realme_nt37705_bl_ops,
							     &props);
	if (IS_ERR(ctx->panel.backlight))
		return dev_err_probe(dev, PTR_ERR(ctx->panel.backlight),
				     "failed to create backlight\n");

	mipi_dsi_set_drvdata(dsi, ctx);
	drm_panel_add(&ctx->panel);

	ret = mipi_dsi_attach(dsi);
	if (ret) {
		drm_panel_remove(&ctx->panel);
		return dev_err_probe(dev, ret, "failed to attach DSI host\n");
	}

	return 0;
}

static void realme_nt37705_remove(struct mipi_dsi_device *dsi)
{
	struct realme_nt37705 *ctx = mipi_dsi_get_drvdata(dsi);

	mipi_dsi_detach(dsi);
	drm_panel_remove(&ctx->panel);
}

static const struct of_device_id realme_nt37705_of_match[] = {
	{ .compatible = "realme,gt-neo5-se-nt37705" },
	{ }
};
MODULE_DEVICE_TABLE(of, realme_nt37705_of_match);

static struct mipi_dsi_driver realme_nt37705_driver = {
	.probe = realme_nt37705_probe,
	.remove = realme_nt37705_remove,
	.driver = {
		.name = "panel-realme-nt37705",
		.of_match_table = realme_nt37705_of_match,
	},
};
module_mipi_dsi_driver(realme_nt37705_driver);

MODULE_DESCRIPTION("Realme GT Neo5 SE NT37705 DSI panel");
MODULE_LICENSE("GPL");
