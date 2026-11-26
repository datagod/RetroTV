assign CLK_VIDEO = clk_video;
assign CE_PIXEL  = 1'b1;

// Cabinet pixels replace framebuffer RGB outside the glass. The DDR photo
// takes the same one-clock delay as the old ROM. A channel change blacks
// the glass and then draws the channel name over the picture.
wire [7:0] retro_r, retro_g, retro_b;
wire       retro_hs, retro_vs, retro_de;
wire       cabinets_ready;
(* preserve, altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF; -name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [2:0] hold_sync = 3'b000;
always @(posedge clk_video) hold_sync <= {hold_sync[1:0], channel_hold | join_cover};
(* preserve, altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF; -name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [2:0] glass_blank = 3'b000;
always @(posedge clk_video) glass_blank <= {glass_blank[1:0], channel_hold | join_cover | music_mode};
wire [7:0] glass_r = glass_blank[2] ? 8'd0 : fb_video_r;
wire [7:0] glass_g = glass_blank[2] ? 8'd0 : fb_video_g;
wire [7:0] glass_b = glass_blank[2] ? 8'd0 : fb_video_b;

retrotv_cabinet retrotv_bezel (
	.clk_sys          (clk_sys),
	.clk_mem          (clk_mpeg2),
	.clk_vid          (clk_video),
	.reset_sys        (RESET),
	.reset_mem        (reset_mpeg2),
	.reset_vid        (reset_video),
	.osd_open         (media_osd_sync[2]),
	.ps2_key          (ps2_key),
	.compact         (compact_video),
	.trinitron       (trinitron_video),
	.xbr             (xbr_video),
	.xbr_requested   (xbr_requested_sys),
	.xbr_gallery     (xbr_gallery_ready),
	.xbr_last_slot    (xbr_last_slot),
	.music_art       ({news_art, music_art_valid, music_art_bank}),
	.ioctl_download   (ioctl_download),
	.ioctl_index      (ioctl_index),
	.ioctl_wr         (ioctl_wr),
	.ioctl_dout       (ioctl_dout),
	.ioctl_wait       (ioctl_wait),
	.cabinet_burstcnt (cabinet_burstcnt),
	.cabinet_addr     (cabinet_addr),
	.cabinet_din      (cabinet_din),
	.cabinet_rd       (cabinet_rd),
	.cabinet_we       (cabinet_we),
	.cabinet_preload  (cabinet_preload),
	.cabinet_busy     (cabinet_busy),
	.cabinet_dout_ready(cabinet_dout_ready),
	.ddram_dout       (DDRAM_DOUT),
	.h_pos            (display_h_pos),
	.v_pos            (display_v_pos),
	.r_in             (glass_r),
	.g_in             (glass_g),
	.b_in             (glass_b),
	.hs_in            (fb_video_hs),
	.vs_in            (fb_video_vs),
	.de_in            (fb_video_de),
	.r_out            (retro_r),
	.g_out            (retro_g),
	.b_out            (retro_b),
	.hs_out           (retro_hs),
	.vs_out           (retro_vs),
	.de_out           (retro_de),
	.cabinets_ready   (cabinets_ready)
);

wire [7:0] banner_r, banner_g, banner_b;
wire       banner_hs, banner_vs, banner_de;
retrotv_channel_banner retrotv_banner (
	.clk_vid   (clk_video),
	.reset_vid (reset_video),
	.h_pos     (display_h_pos),
	.v_pos     (display_v_pos),
	.r_in      (retro_r),
	.g_in      (retro_g),
	.b_in      (retro_b),
	.hs_in     (retro_hs),
	.vs_in     (retro_vs),
	.de_in     (retro_de),
	.compact   (compact_video),
	.trinitron (trinitron_video),
	.xbr       (xbr_video),
	.name_flat (banner_name),
	.name_len  (banner_len),
	.name_tog  (banner_tog),
	.hold_in   (hold_sync[2]),
	.r_out     (banner_r),
	.g_out     (banner_g),
	.b_out     (banner_b),
	.hs_out    (banner_hs),
	.vs_out    (banner_vs),
	.de_out    (banner_de)
);

// The words stay up until the cabinets are stored and a clip has been chosen,
// then for two more seconds, so the set cuts from the title to a picture.
reg        splash_go = 1'b0;
always @(posedge clk_sys) begin
	if (RESET)
		splash_go <= 1'b0;
	else if (playlist_selected || playlist_error || music_art_valid)
		splash_go <= 1'b1;
end
(* preserve, altera_attribute = "-name AUTO_SHIFT_REGISTER_RECOGNITION OFF; -name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [2:0]  splash_sync = 3'b000;
reg [7:0]  splash_hold = 8'd0;
reg        splash_vs_d = 1'b0;
always @(posedge clk_video) begin
	splash_sync <= {splash_sync[1:0], splash_go};
	splash_vs_d <= fb_video_vs;
	if (reset_video)
		splash_hold <= 8'd0;
	else if (!cabinets_ready)
		splash_hold <= 8'd120;
	else if (fb_video_vs && !splash_vs_d && splash_hold != 0)
		splash_hold <= splash_hold - 8'd1;
end
wire [7:0] splash_r, splash_g, splash_b;
wire       splash_hs, splash_vs, splash_de;
retrotv_splash retrotv_opening (
	.clk_vid   (clk_video),
	.reset_vid (reset_video),
	.active    (!(cabinets_ready && splash_sync[2]) || splash_hold != 0),
	.xbr       (xbr_video),
	.h_pos     (display_h_pos),
	.v_pos     (display_v_pos),
	.r_in      (banner_r),
	.g_in      (banner_g),
	.b_in      (banner_b),
	.hs_in     (banner_hs),
	.vs_in     (banner_vs),
	.de_in     (banner_de),
	.r_out     (splash_r),
	.g_out     (splash_g),
	.b_out     (splash_b),
	.hs_out    (splash_hs),
	.vs_out    (splash_vs),
	.de_out    (splash_de)
);

assign VGA_DE = splash_de;
assign VGA_HS = splash_hs;
assign VGA_VS = splash_vs;
assign VGA_R  = splash_r;
assign VGA_G  = splash_g;
assign VGA_B  = splash_b;

// Gate one: framebuffer pixels reach the platform directly. Player UI and
// subtitles remain in their independent HDMI overlay.

// Normal platform LED values; legacy diagnostic success/blink logic is retired.
assign LED_USER = 1'b0;
assign LED_POWER = 2'b00;
assign LED_DISK = 2'b00;

endmodule
