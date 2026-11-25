reg direct_movie = 1'b0;
reg direct_mount_pending = 1'b0;
wire manual_movie_mount = media_img_mounted[0] && !media_mount_d && !direct_mount_pending;
wire media_external_new_file = manual_movie_mount ||
                               (media_user_reset && !media_user_reset_d) ||
                               channel_rescan;
wire media_new_file=media_external_new_file || playlist_selected || media_eof_close;
// chain: this channel has another archive. start_last: open on the last clip.
// start_pick: open on start_index (a broadcast join).
reg chain = 1'b0;
reg start_last = 1'b0;
reg start_pick = 1'b0;
reg [7:0] start_index = 8'd0;
reg [23:0] join_seconds = 24'd0;
wire part_next, part_prev;
media_movie_playlist playlist(
 .clk(clk_sys),.reset(RESET || music_mode),.open(media_external_new_file),
 .metadata_clk(PLAYER_META_CLOCK),.metadata_address(PLAYER_META_ADDRESS),.metadata_data(PLAYER_META_DATA),
 .mounted_size(media_img_mounted[0]?media_img_size:media_mount_size),
 .completed(media_video_eof_close),.osd_open(media_osd_sync[2] || channel_hold || join_cover),.key(ps2_key),
 .reader_idle(media_reader_idle),.reader_error(media_error),.stream_data(media_stream_data),.stream_valid(media_stream_valid),
 .scan_busy(playlist_scan_busy),.scan_cancel(playlist_scan_cancel),.stream_ready(playlist_stream_ready),
 .scan_start(playlist_scan_start),.scan_offset(playlist_scan_offset),.scan_end(playlist_scan_end),
 .selected(playlist_selected),.movie_base(media_file_base),.movie_size(media_file_size),
 .subtitle_base(playlist_subtitle_base),.subtitle_size(playlist_subtitle_size),
 .playlist_active(playlist_active),.track(playlist_track),.count(playlist_count),.error(playlist_error),
 .chain(chain),.start_last(start_last),.start_pick(start_pick),.start_index(start_index),
 .part_next(part_next),.part_prev(part_prev));
wire media_paused_sys,media_seek_sys,media_seek_restart;
wire [34:0] media_target_sys,media_elapsed_sys,media_elapsed_q;
wire media_seek_done,media_seek_done_sys;
wire [36:0] media_control_mpeg;
wire media_paused=media_control_mpeg[36];
wire media_seeking=media_control_mpeg[35];
wire [34:0] media_target_q=media_control_mpeg[34:0];
wire media_search_restart,media_search_busy,media_probe_sys;
wire [40:0] media_start_offset,media_video_start;
wire [7:0] media_search_tag,media_search_echo;
wire [90:0] media_seek_config_mpeg;
wire [7:0] media_search_tag_mpeg=media_seek_config_mpeg[90:83];
wire media_probe_mpeg=media_seek_config_mpeg[82];
wire [40:0] media_start_offset_mpeg=media_seek_config_mpeg[81:41];
wire [40:0] media_video_start_mpeg=media_seek_config_mpeg[40:0];
wire media_movie_origin_valid;
wire [32:0] media_movie_origin;
wire media_point_found;
wire [32:0] media_point_pts;
wire [40:0] media_point_pack,media_point_sequence;
wire [159:0] media_probe_response_sys;
wire music_enter;
wire media_restart=media_new_file||media_search_restart||music_enter;
video_config_cdc #(.WIDTH(91)) seek_file_config(
 .src_clk(clk_sys),.dst_clk(clk_mpeg2),
 .src_data({media_search_tag,media_probe_sys,media_start_offset,media_video_start}),
 .dst_data(media_seek_config_mpeg));
video_config_cdc #(.WIDTH(8)) seek_file_echo_config(
 .src_clk(clk_mpeg2),.dst_clk(clk_sys),.src_data(media_search_tag_mpeg),.dst_data(media_search_echo));
video_config_cdc #(.WIDTH(160)) seek_probe_config(
 .src_clk(clk_mpeg2),.dst_clk(clk_sys),
 .src_data({media_search_tag_mpeg,av_is_ps,media_movie_origin_valid,media_movie_origin,
            media_point_found,av_raw_end,media_point_pts,media_point_pack,media_point_sequence}),
 .dst_data(media_probe_response_sys));
// Join seek target is seconds from the clip origin, in the same quarter-90 kHz
// units the function keys use. 90000 ticks per second, then << 2.
wire [40:0] join_ticks = join_seconds * 17'd90000;
wire [34:0] join_target = {join_ticks[32:0], 2'b00};
wire join_origin_valid = media_probe_response_sys[151] && media_probe_response_sys[150];
reg ext_seek = 1'b0;
reg [34:0] ext_target = 35'd0;
media_seek_search media_seek_search(
 .clk(clk_sys),.reset(RESET || music_mode),.new_file(media_new_file),.request(media_seek_restart),
 .program_stream(media_probe_response_sys[151]),.origin_valid(media_probe_response_sys[150]),
 .origin(media_probe_response_sys[149:117]),.target_q(media_target_sys),.file_size(media_file_size),
 .reader_start(media_reader_start),.reader_position(media_byte_position),
 .response_tag(media_probe_response_sys[159:152]),.point_found(media_probe_response_sys[116]),
 .probe_end(media_probe_response_sys[115]),.point_pts(media_probe_response_sys[114:82]),
 .point_pack(media_probe_response_sys[81:41]),.point_sequence(media_probe_response_sys[40:0]),
 .busy(media_search_busy),.probing(media_probe_sys),.restart(media_search_restart),
 .tag(media_search_tag),.start_offset(media_start_offset),.video_start(media_video_start));
(* preserve, altera_attribute="-name AUTO_SHIFT_REGISTER_RECOGNITION OFF; -name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [2:0] media_osd_sync=0;
always @(posedge clk_sys) media_osd_sync<={media_osd_sync[1:0],OSD_STATUS};
media_keyboard_control #(.RESTART_BOTH_DIRECTIONS(1),.ENABLE_SEEK_GATE(1),.ENABLE_LAYOUT_KEYS(1)) media_keyboard_control(
 .clk(clk_sys),.reset(RESET),.new_file(media_new_file),.enabled(media_file_size!=0 && !playlist_scan_busy && !media_duration_busy && !channel_hold && !music_mode),
 .seek_enabled(1'b1),.osd_open(media_osd_sync[2] || channel_hold || join_cover),.key(ps2_key),.elapsed_q(media_elapsed_sys),
 .seek_done(media_seek_done_sys && !media_search_busy),.restart_complete(media_reader_start && !media_probe_sys),
 .duration_q(media_duration_q),
 .seek_origin_q(35'd0),
 .duration_valid(media_duration_known),
 .paused(media_paused_sys),.seek_active(media_seek_sys),
 .seek_target_q(media_target_sys),.restart(media_seek_restart),
 .ext_seek(ext_seek),.ext_target(ext_target));
video_config_cdc #(.WIDTH(37)) playback_control_config(
 .src_clk(clk_sys),.dst_clk(clk_mpeg2),
 .src_data({media_paused_sys,media_seek_sys,media_target_sys}),.dst_data(media_control_mpeg));
video_config_cdc #(.WIDTH(36)) playback_position_config(
 .src_clk(clk_mpeg2),.dst_clk(clk_sys),
 .src_data({media_seek_done,media_elapsed_q}),.dst_data({media_seek_done_sys,media_elapsed_sys}));
always @(posedge clk_sys) begin
    media_mount_d<=media_img_mounted[0];media_user_reset_d<=media_user_reset;
    if(RESET) media_mount_size<=0;
    else if(media_img_mounted[0]) media_mount_size<=media_img_size;
end
// Duration preflight owns the same reader until every accepted response drains.
wire media_duration_busy,media_duration_start,media_duration_cancel,media_duration_ready;
wire media_duration_valid;
wire [34:0] media_duration_q;
wire [63:0] media_duration_size,media_duration_offset;
media_duration_probe media_duration_probe(
 .clk(clk_sys),.reset(RESET||playlist_scan_busy||channel_hold||music_mode),.new_file(media_new_file),.file_size(media_file_size),
 .reader_idle(media_reader_idle),.reader_error(media_error),
 .stream_data(media_stream_data),.stream_valid(media_stream_valid),.stream_ready(media_duration_ready),
 .busy(media_duration_busy),.reader_start(media_duration_start),.reader_cancel(media_duration_cancel),
 .read_size(media_duration_size),.read_offset(media_duration_offset),
 .duration_valid(media_duration_valid),.duration_q(media_duration_q),.origin());
wire playlist_ui_visible;
media_album_ui_toggle playlist_ui_keys(
 .clk(clk_sys),.reset(RESET),.new_file(media_external_new_file),
 .enabled(playlist_active&&!playlist_scan_busy),.osd_open(media_osd_sync[2]),
 .key(ps2_key),.visible(playlist_ui_visible));
// The A key alone selects display shape; sequence metadata never overrides it.
// Follow the level into the video clock. The change mailbox can miss the
// reset value when its power-up copy already matches.
wire aspect_wide;
media_aspect_toggle aspect_key(.clk(clk_sys),.reset(RESET),.osd_open(media_osd_sync[2]),.key(ps2_key),.wide(aspect_wide));
// ttyS1 is the HPS UART wired through the core, not the console.
// 20 MHz / 115200 is 173.6 cycles; 174 is used. 8N1, idle high.
// Core to Linux: 0xA5 escape, 0xA6 next channel, 0xA8 previous channel,
//   0xA9 next archive in this channel, 0xAA previous archive.
// Linux to core, after the mounted tar is fully written:
//   0xC1, name, 0x00  rescan from the first clip and show the name
//   0xC2, name, 0x00  show the name only
//   0xC3, name, 0x00  rescan from the last clip and show the name
//   0xC4              allow another channel key; glass stays dark
//   0xC5              finish browsing and begin the committed tune
//   0xC8              this channel continues in another archive
//   0xC9              this channel is one archive; the playlist loops itself
//   0xCA, index, seconds[23:16], seconds[15:8], seconds[7:0], name, 0x00
//                     rescan at that clip and seek that many seconds in
//   0xCB              enter music mode, blank the glass, retire the movie
//   0xCC/0xCD         show artwork from DDR bank 0/1
//   0xD0              hold video while Main mounts a standalone MPG
//   0xD1              default XBR bezel is ready
//   0xD2              all six XBR-layout cabinets are ready
// After the mount event delivers its real size, CA with index zero opens
// the MPG and applies the channel clock offset. Direct EOF/N/P use A9/AA.
// Core to Linux while in music mode: A9/AA next/previous, AB pause.
// AC/AD mirror the core's mute state, including at entry to music mode.
reg [9:0] menu_uart_frame = 10'h3FF;
reg [3:0] menu_uart_left = 4'd0;
reg [7:0] menu_uart_div = 8'd0;
reg [7:0] uart_q0 = 8'h00;
reg [7:0] uart_q1 = 8'h00;
reg [1:0] uart_qn = 2'd0;
reg key_tog = 1'b0;
reg esc_down = 1'b0;
reg l_down = 1'b0;
reg r_down = 1'b0;
reg music_n_down = 1'b0;
reg music_p_down = 1'b0;
reg music_space_down = 1'b0;
reg m_down = 1'b0;
reg channel_busy = 1'b0;
reg channel_browsing = 1'b0;
// The XBR raster inherits the native and compact geometry flags.
reg xbr_asset_ready = 1'b0;
reg xbr_gallery_ready = 1'b0;
wire xbr_requested_sys = xbr_asset_ready;
wire compact_video, trinitron_video, xbr_video;
wire [2:0] video_layout;
video_config_cdc #(.WIDTH(3)) cabinet_layout_config(
 .src_clk(clk_sys), .dst_clk(clk_video),
 .src_data(xbr_asset_ready ? 3'b111 : 3'b000), .dst_data(video_layout));
wire native_hdmi = HDMI_WIDTH == 12'd1920 && HDMI_HEIGHT == 12'd1080;
wire compact_request_video = video_layout[0] && native_hdmi;
wire trinitron_request_video = video_layout[1] && native_hdmi;
wire xbr_request_video = video_layout[2] && native_hdmi;
reg [255:0] banner_name = 256'd0;
reg [5:0] banner_len = 6'd0;
reg banner_tog = 1'b0;
reg tog_arm = 1'b0;
reg [7:0] tog_wait = 8'd0;
reg [7:0] nb [0:31];
reg [1:0] rx_parse = 2'd0;
reg rx_rescan = 1'b0;
reg rx_join = 1'b0;
reg [1:0] join_fill = 2'd0;
reg join_seek_sent = 1'b0;
reg join_seen = 1'b0;
reg join_origin_low = 1'b0;
reg [29:0] join_timer = 30'd0;
reg pend_next = 1'b0;
reg pend_prev = 1'b0;
reg [5:0] rx_len = 6'd0;
integer name_i;
localparam RX_IDLE = 2'd0, RX_NAME = 2'd1, RX_JOIN = 2'd2;

(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [2:0] rx_meta = 3'b111;
reg [1:0] rx_state = 2'd0;
reg [7:0] rx_div = 8'd0;
reg [2:0] rx_bitn = 3'd0;
reg [7:0] rx_shift = 8'd0;
reg [7:0] rx_byte = 8'd0;
reg rx_stb = 1'b0;
localparam RXS_IDLE = 2'd0, RXS_START = 2'd1, RXS_DATA = 2'd2, RXS_STOP = 2'd3;

wire key_step = (key_tog != ps2_key[10]);
wire esc_make = key_step && (ps2_key[8:0] == 9'h076) && ps2_key[9] && !esc_down && !media_osd_sync[2];
wire can_browse = !channel_busy || channel_browsing;
wire left_make = key_step && (ps2_key[8:0] == 9'h16b) && ps2_key[9] && !l_down && !media_osd_sync[2] && can_browse;
wire right_make = key_step && (ps2_key[8:0] == 9'h174) && ps2_key[9] && !r_down && !media_osd_sync[2] && can_browse;
wire ch_make = left_make || right_make;
wire queue_room = (uart_qn < 2'd2) || ((menu_uart_left == 0) && (uart_qn != 0));
wire accept_ch = ch_make && queue_room;
assign music_enter = rx_stb && (rx_parse == RX_IDLE) && (rx_byte == 8'hCB);
wire music_key = music_mode && !channel_busy && !media_osd_sync[2] &&
                 key_step && ps2_key[9];
wire music_next = music_key && ps2_key[8:0] == 9'h031 && !music_n_down;
wire music_prev = music_key && ps2_key[8:0] == 9'h04d && !music_p_down;
wire music_pause = music_key && ps2_key[8:0] == 9'h029 && !music_space_down;
wire music_mute = music_mode && key_step && ps2_key[9] && !m_down &&
                  !media_osd_sync[2] && (ps2_key[8:0] == 9'h03a);
wire direct_key = direct_movie && !music_mode && !channel_busy &&
                  !media_osd_sync[2] && key_step && ps2_key[9] && media_file_size != 0;
wire direct_next = direct_movie && !music_mode &&
                   (media_video_eof_close || (direct_key && ps2_key[8:0] == 9'h031 && !music_n_down));
wire direct_prev = direct_key && ps2_key[8:0] == 9'h04d && !music_p_down;
wire req_next = pend_next || part_next || direct_next;
wire req_prev = pend_prev || part_prev || direct_prev;
wire fire_part = !music_mode && (req_next || req_prev) && !channel_busy && queue_room && !esc_make && !ch_make;
wire fire_music = queue_room && (music_enter || music_mute || music_next || music_prev || music_pause);
wire do_push = esc_make || accept_ch || fire_part || fire_music;
wire [7:0] pushb = esc_make ? 8'hA5 :
                   accept_ch ? (left_make ? 8'hA8 : 8'hA6) :
                   music_enter ? (audio_mute ? 8'hAC : 8'hAD) :
                   music_mute ? (audio_mute ? 8'hAD : 8'hAC) :
                   music_pause ? 8'hAB :
                   (music_prev || (!music_mode && req_prev && !req_next)) ? 8'hAA : 8'hA9;

always @(posedge clk_sys) begin
 rx_stb <= 1'b0;
 if (RESET) begin
  rx_meta <= 3'b111;
  rx_state <= RXS_IDLE;
  rx_div <= 8'd0;
  rx_bitn <= 3'd0;
  rx_shift <= 8'd0;
 end else begin
  rx_meta <= {rx_meta[1:0], UART_RXD};
  case (rx_state)
   RXS_IDLE: if (!rx_meta[2]) begin
    rx_state <= RXS_START;
    rx_div <= 8'd0;
   end
   RXS_START: if (rx_div == 8'd86) begin
    rx_div <= 8'd0;
    if (rx_meta[2]) rx_state <= RXS_IDLE;
    else begin
     rx_state <= RXS_DATA;
     rx_bitn <= 3'd0;
    end
   end else
    rx_div <= rx_div + 8'd1;
   RXS_DATA: if (rx_div == 8'd173) begin
    rx_div <= 8'd0;
    rx_shift <= {rx_meta[2], rx_shift[7:1]};
    if (rx_bitn == 3'd7) rx_state <= RXS_STOP;
    else rx_bitn <= rx_bitn + 3'd1;
   end else
    rx_div <= rx_div + 8'd1;
   default: if (rx_div == 8'd173) begin
    rx_div <= 8'd0;
    rx_state <= RXS_IDLE;
    if (rx_meta[2]) begin
     rx_byte <= rx_shift;
     rx_stb <= 1'b1;
    end
   end else
    rx_div <= rx_div + 8'd1;
  endcase
 end
end

always @(posedge clk_sys) begin
 if (RESET) begin
  menu_uart_tx <= 1'b1;
  menu_uart_frame <= 10'h3FF;
  menu_uart_left <= 4'd0;
  menu_uart_div <= 8'd0;
  uart_qn <= 2'd0;
  esc_down <= 1'b0;
  l_down <= 1'b0;
  r_down <= 1'b0;
  music_n_down <= 1'b0;
  music_p_down <= 1'b0;
  music_space_down <= 1'b0;
  music_mode <= 1'b0;
  music_art_valid <= 1'b0;
  music_art_bank <= 1'b0;
  news_art <= 1'b0;
  key_tog <= ps2_key[10];
  channel_hold <= 1'b0;
  channel_busy <= 1'b0;
  channel_browsing <= 1'b0;
  xbr_asset_ready <= 1'b0;
  xbr_gallery_ready <= 1'b0;
  channel_rescan <= 1'b0;
  chain <= 1'b0;
  direct_movie <= 1'b0;
  direct_mount_pending <= 1'b0;
  start_last <= 1'b0;
  start_pick <= 1'b0;
  start_index <= 8'd0;
  join_seconds <= 24'd0;
  join_cover <= 1'b0;
  ext_seek <= 1'b0;
  join_fill <= 2'd0;
  join_seek_sent <= 1'b0;
  join_seen <= 1'b0;
  join_origin_low <= 1'b0;
  join_timer <= 30'd0;
  pend_next <= 1'b0;
  pend_prev <= 1'b0;
  banner_len <= 6'd0;
  banner_tog <= 1'b0;
  tog_arm <= 1'b0;
  tog_wait <= 8'd0;
  rx_parse <= RX_IDLE;
  rx_rescan <= 1'b0;
  rx_join <= 1'b0;
  rx_len <= 6'd0;
 end else begin
  channel_rescan <= 1'b0;
  ext_seek <= 1'b0;
  key_tog <= ps2_key[10];
  if (key_step) begin
   if (ps2_key[8:0] == 9'h076) esc_down <= ps2_key[9];
   if (ps2_key[8:0] == 9'h16b) l_down <= ps2_key[9];
   if (ps2_key[8:0] == 9'h174) r_down <= ps2_key[9];
   if (ps2_key[8:0] == 9'h031) music_n_down <= ps2_key[9];
   if (ps2_key[8:0] == 9'h04d) music_p_down <= ps2_key[9];
   if (ps2_key[8:0] == 9'h029) music_space_down <= ps2_key[9];
  end

  if (tog_arm) begin
   if (tog_wait == 8'd255) begin
    tog_arm <= 1'b0;
    banner_tog <= ~banner_tog;
   end else
    tog_wait <= tog_wait + 8'd1;
  end

  if (playlist_selected && !music_mode && !channel_browsing && !channel_busy)
   channel_hold <= 1'b0;
  if (accept_ch)
   channel_browsing <= 1'b1;
  if (accept_ch || fire_part) begin
   music_art_valid <= 1'b0;
   channel_hold <= 1'b1;
   channel_busy <= 1'b1;
  end
  if (manual_movie_mount)
   direct_movie <= 1'b0;
  if (RESET || accept_ch || channel_rescan || fire_part) begin
   pend_next <= 1'b0;
   pend_prev <= 1'b0;
  end else begin
   if (part_next || direct_next) pend_next <= 1'b1;
   if (part_prev || direct_prev) pend_prev <= 1'b1;
  end

  // The glass stays dark while the join seek runs. The reader is not held,
  // so the clip can start and the search can move it. Anything under two
  // seconds is inside the search window, so that target plays from the start.
  // 30 seconds at 20 MHz abandons a search that never lands.
  if (join_cover) begin
   if (join_timer != 30'd600000000)
    join_timer <= join_timer + 30'd1;
   if (!join_origin_valid)
    join_origin_low <= 1'b1;
   if (playlist_error || join_timer == 30'd600000000)
    join_cover <= 1'b0;
   else if (!channel_hold && !playlist_scan_busy && !join_seek_sent &&
            join_origin_low && join_origin_valid && !media_seek_sys &&
            !media_search_busy && (media_file_size != 0)) begin
    if (join_target < 35'd720000)
     join_cover <= 1'b0;
    else begin
     ext_target <= join_target;
     ext_seek <= 1'b1;
     join_seek_sent <= 1'b1;
    end
   end else if (join_seek_sent && media_seek_sys)
    join_seen <= 1'b1;
   else if (join_seek_sent && join_seen && !media_seek_sys && !media_search_busy)
    join_cover <= 1'b0;
  end

  if (rx_stb) begin
   if (rx_parse == RX_IDLE) begin
    if (rx_byte == 8'hC1 || rx_byte == 8'hC2 || rx_byte == 8'hC3) begin
     rx_parse <= RX_NAME;
     rx_rescan <= (rx_byte != 8'hC2);
     rx_join <= 1'b0;
     rx_len <= 6'd0;
     if (rx_byte == 8'hC3) begin
      start_last <= 1'b1;
      start_pick <= 1'b0;
      join_cover <= 1'b0;
     end else if (rx_byte == 8'hC1) begin
      start_last <= 1'b0;
      start_pick <= 1'b0;
      join_cover <= 1'b0;
     end
    end else if (rx_byte == 8'hCA) begin
     rx_parse <= RX_JOIN;
     rx_rescan <= 1'b1;
     rx_join <= 1'b1;
     join_fill <= 2'd0;
     start_last <= 1'b0;
    end else if (rx_byte == 8'hD0) begin
     direct_movie <= 1'b1;
     direct_mount_pending <= 1'b1;
     channel_hold <= 1'b1;
     channel_busy <= 1'b1;
     channel_browsing <= 1'b0;
     join_cover <= 1'b0;
     pend_next <= 1'b0;
     pend_prev <= 1'b0;
    end else if (music_enter) begin
     direct_movie <= 1'b0;
     channel_browsing <= 1'b0;
     music_mode <= 1'b1;
     music_art_valid <= 1'b0;
     news_art <= 1'b0;
     channel_hold <= 1'b1;
     channel_busy <= 1'b1;
     join_cover <= 1'b0;
    end else if (music_mode && !channel_browsing && !accept_ch &&
                 (rx_byte == 8'hCC || rx_byte == 8'hCD ||
                  rx_byte == 8'hD4 || rx_byte == 8'hD5)) begin
     music_art_valid <= 1'b1;
     music_art_bank <= rx_byte[0];
     news_art <= rx_byte == 8'hD4 || rx_byte == 8'hD5;
     channel_hold <= 1'b0;
     channel_busy <= 1'b0;
    end else if (rx_byte == 8'hC4) begin
     direct_mount_pending <= 1'b0;
     music_art_valid <= 1'b0;
     channel_busy <= 1'b0;
     channel_browsing <= 1'b0;
     join_cover <= 1'b0;
    end else if (rx_byte == 8'hD1 || rx_byte == 8'hD2) begin
     xbr_asset_ready <= 1'b1;
     xbr_gallery_ready <= rx_byte == 8'hD2;
    end else if (rx_byte == 8'hC5)
     channel_browsing <= 1'b0;
    else if (rx_byte == 8'hC8)
     chain <= 1'b1;
    else if (rx_byte == 8'hC9)
     chain <= 1'b0;
   end else if (rx_parse == RX_JOIN) begin
    if (join_fill == 2'd0) start_index <= rx_byte;
    else if (join_fill == 2'd1) join_seconds[23:16] <= rx_byte;
    else if (join_fill == 2'd2) join_seconds[15:8] <= rx_byte;
    else begin
     join_seconds[7:0] <= rx_byte;
     rx_parse <= RX_NAME;
     rx_len <= 6'd0;
    end
    if (join_fill != 2'd3)
     join_fill <= join_fill + 2'd1;
   end else if (rx_byte == 8'h00) begin
    rx_parse <= RX_IDLE;
    banner_len <= rx_len;
    for (name_i = 0; name_i < 32; name_i = name_i + 1)
     banner_name[name_i * 8 +: 8] <= (name_i < rx_len) ? nb[name_i] : 8'h20;
    tog_arm <= 1'b1;
    tog_wait <= 8'd0;
    if (rx_join) begin
     start_pick <= 1'b1;
     start_last <= 1'b0;
     rx_join <= 1'b0;
     if (join_seconds >= 24'd2) begin
      join_cover <= 1'b1;
      join_timer <= 30'd0;
      join_seek_sent <= 1'b0;
      join_seen <= 1'b0;
      join_origin_low <= 1'b0;
     end else
      join_cover <= 1'b0;
    end
    if (rx_rescan) begin
     direct_mount_pending <= 1'b0;
     channel_browsing <= 1'b0;
     music_mode <= 1'b0;
     music_art_valid <= 1'b0;
     channel_busy <= 1'b0;
     channel_rescan <= 1'b1;
    end
   end else if ((rx_len < 6'd32) && (rx_byte >= 8'h20) && (rx_byte < 8'h7F)) begin
    nb[rx_len] <= rx_byte;
    rx_len <= rx_len + 6'd1;
   end
  end

  if ((menu_uart_left == 0) && (uart_qn != 0)) begin
   menu_uart_frame <= {1'b1, uart_q0, 1'b0};
   menu_uart_left <= 4'd10;
   menu_uart_div <= 8'd0;
   menu_uart_tx <= 1'b0;
   if (do_push && (uart_qn == 2'd1)) begin
    uart_q0 <= pushb;
   end else if (do_push) begin
    uart_q0 <= uart_q1;
    uart_q1 <= pushb;
   end else begin
    uart_q0 <= uart_q1;
    uart_qn <= uart_qn - 2'd1;
   end
  end else begin
   if (menu_uart_left == 0)
    menu_uart_tx <= 1'b1;
   else if (menu_uart_div == 8'd173) begin
    menu_uart_div <= 8'd0;
    menu_uart_frame <= {1'b1, menu_uart_frame[9:1]};
    menu_uart_left <= menu_uart_left - 4'd1;
    menu_uart_tx <= menu_uart_frame[1];
   end else
    menu_uart_div <= menu_uart_div + 8'd1;
   if (do_push && (uart_qn < 2'd2)) begin
    if (uart_qn == 0) uart_q0 <= pushb;
    else uart_q1 <= pushb;
    uart_qn <= uart_qn + 2'd1;
   end
  end
 end
end
// M mutes the movie. Core reset clears it. A new file does not.
reg mute_toggle=0;
always @(posedge clk_sys) begin
 if(RESET) begin
  audio_mute<=1'b0;
  m_down<=1'b0;
  mute_toggle<=ps2_key[10];
 end else begin
  mute_toggle<=ps2_key[10];
  if(mute_toggle!=ps2_key[10] && ps2_key[8:0]==9'h03a) begin
   m_down<=ps2_key[9];
   if(ps2_key[9] && !m_down && !media_osd_sync[2]) audio_mute<=!audio_mute;
  end
 end
end
(* preserve, altera_attribute="-name AUTO_SHIFT_REGISTER_RECOGNITION OFF; -name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [1:0] aspect_sync=2'b11;
always @(posedge clk_video) aspect_sync<={aspect_sync[0],aspect_wide};
wire ar=aspect_sync[1];
assign VIDEO_ARX = xbr_video ? {1'b1,12'd1024} : trinitron_video ? {1'b1,12'd960} :
                   compact_video ? {1'b1,12'd832} : ar ? 13'd16 : 13'd4;
assign VIDEO_ARY = xbr_video ? {1'b1,12'd720} : compact_video ? {1'b1,12'd624} : ar ? 13'd9 : 13'd3;
assign PLAYER_META_STATE={playlist_active&&playlist_ui_visible&&!playlist_scan_busy,playlist_count,playlist_track+8'd1};
assign PLAYER_UI_CLOCK=clk_sys;
media_ui_state player_ui_state(
 .clk(clk_sys),.reset(RESET),.new_file(media_new_file),
 .loaded(media_file_size!=0 && !playlist_scan_busy && !media_duration_busy && !media_fifo_reset),
 .duration_known(media_duration_known),
 .seeking(media_seek_sys),
 .elapsed_q(media_elapsed_sys),.target_q(media_target_sys),
 .duration_q(media_duration_q),.duration_valid(media_duration_valid),.scene_state(PLAYER_UI_STATE));
media_session_control #(.ENABLE_START_READY(1)) media_session_control (
 .clk_sys(clk_sys),.clk_mpeg2(clk_mpeg2),.reset(RESET),.restart(media_restart),
 .reader_idle(media_reader_idle),.ddr_idle(media_ddr_idle),
 .start_ready(!music_mode && media_search_echo==media_search_tag && !media_duration_busy && !playlist_scan_busy),
 .reader_cancel(media_reader_cancel),.fifo_reset(media_fifo_reset),
 .reader_start(media_reader_start),.quiesce(media_quiesce),
 .decoder_reset(media_decoder_reset),.generation(media_generation)
);
media_file_reader media_file_reader (
 .clk(clk_sys),.reset(RESET),.start(playlist_scan_busy ? playlist_scan_start : (media_duration_busy ? media_duration_start : (media_reader_start && media_file_size!=0))),
 .cancel(playlist_scan_busy ? playlist_scan_cancel : (media_duration_busy ? media_duration_cancel : (media_reader_cancel || media_fatal_sys || channel_hold))),.suspend(1'b0),
 .file_base(playlist_scan_busy ? 64'd0 : media_file_base),
 .file_size(playlist_scan_busy ? playlist_scan_end : (media_duration_busy ? media_duration_size : media_file_size)),
 .start_offset(playlist_scan_busy ? playlist_scan_offset : (media_duration_busy ? media_duration_offset : {23'd0,media_start_offset})),
 .sd_lba(media_sd_lba[0]),.sd_blk_cnt(media_sd_blocks[0]),.sd_rd(media_sd_rd[0]),
 .sd_ack(media_sd_ack[0]),.sd_buff_wr(media_reader_wr[0]),
 .sd_buff_addr(media_sd_addr),.sd_buff_dout(media_sd_data),
 .stream_data(media_stream_data),.stream_valid(media_stream_valid),
 .stream_ready(playlist_scan_busy ? playlist_stream_ready : (media_duration_busy ? media_duration_ready : (!mpeg2_stream_full && !media_fifo_reset))),.idle(media_reader_idle),
 .byte_position(media_byte_position),.requests(),
 .completions(),.max_wait(),.error(media_error)
);
always @(posedge clk_sys) begin
 if(media_fifo_reset) media_prefill<=0;
 else begin
  if(media_fifo_used>=4096 || (media_stream_valid && media_stream_data[8])) media_prefill<=1;
 end
end
video_config_cdc #(.WIDTH(1)) media_prefill_config (
 .src_clk(clk_sys),.dst_clk(clk_mpeg2),.src_data(media_prefill),.dst_data(media_prefill_mpeg));
video_config_cdc #(.WIDTH(1)) media_fatal_config (
 .src_clk(clk_mpeg2),.dst_clk(clk_sys),.src_data(mpeg2_new_transport_fatal_error),.dst_data(media_fatal_sys));
// Reader failure participates in seek termination; preserve that functional
// event without carrying the former 256-bit statistics snapshot.
video_config_cdc #(.WIDTH(1)) reader_error_config (
 .src_clk(clk_sys),.dst_clk(clk_mpeg2),
 .src_data(|media_error),.dst_data(media_reader_error_mpeg));
wire        mpeg2_stream_full;
wire        mpeg2_stream_empty;
wire [7:0]  mpeg2_fifo_data;
wire [7:0]  mpeg2_stream_data;
wire        mpeg2_new_system_input_ready;
wire        mpeg2_new_system_input_valid;
wire        mpeg2_stream_rd;
wire        mpeg2_stream_wr;
wire        mpeg2_new_decode_stream_valid;
wire        mpeg2_new_stream_ready;
wire        mpeg2_new_decoder_stream_ready;
wire        mpeg2_new_b_presentation_hold;
wire        mpeg2_new_p_destination_ownership_hold;

media_sd_owner mounted_file_owner(.clk(clk_sys),.reset(RESET),.request(media_sd_rd),.ack(media_sd_ack),
 .subtitle_archive(subtitle_archive),.reader_lba(media_sd_lba),.reader_blocks(media_sd_blocks),
 .host_lba(media_host_lba),.host_blocks(media_host_blocks),.host_ack(media_host_ack),
 .buff_wr(media_sd_wr),.host_request(media_host_rd),.reader_wr(media_reader_wr));
wire[36:0] subtitle_elapsed_q;
wire subtitle_before_start,subtitle_retime;
wire [6:0] subtitle_offset_code,subtitle_speed_code;
media_subtitle_select subtitle_select(.clk(clk_sys),.reset(RESET),
 .offset_select(status[57:7]),.speed_select(status[108:58]),
 .offset_code(subtitle_offset_code),.speed_code(subtitle_speed_code));
media_subtitle_time subtitle_time(.clk(clk_sys),.reset(RESET||media_new_file),
 .elapsed_q(media_elapsed_sys),.offset_code(subtitle_offset_code),.speed_code(subtitle_speed_code),
 .subtitle_q(subtitle_elapsed_q),.before_start(subtitle_before_start),.restart(subtitle_retime));
media_subtitles subtitles(.clk(clk_sys),.reset(RESET),.new_movie(media_new_file),
 .mount(media_img_mounted[1]),.mount_size(media_img_size),
 .auto_load(playlist_selected&&playlist_active),.auto_base(playlist_subtitle_base),.auto_size(playlist_subtitle_size),.archive_source(subtitle_archive),
 .loaded(PLAYER_UI_STATE[74]),.seeking(media_seek_sys||subtitle_retime),.enabled(!status[120]&&!subtitle_before_start),
 .suspend(playlist_scan_busy || media_duration_busy || media_seek_sys || (media_fifo_occupancy<16'd8192 && !media_reader_idle)),
 .elapsed_q(subtitle_elapsed_q),.epoch(PLAYER_UI_STATE[90:75]),
 .sd_lba(media_sd_lba[1]),.sd_blocks(media_sd_blocks[1]),.sd_rd(media_sd_rd[1]),
 .sd_ack(media_sd_ack[1]),.sd_wr(media_reader_wr[1]),.sd_addr(media_sd_addr),.sd_data(media_sd_data),
 .command(PLAYER_SUBTITLE_COMMAND),.command_ack(PLAYER_SUBTITLE_ACK),.warning());

hps_io #(.CONF_STR(CONF_STR), .CONF_STR_BRAM(1), .WIDE(1), .VDNUM(2)) hps_io
(
	.clk_sys(clk_sys),
	.HPS_BUS(HPS_BUS),
	.EXT_BUS(),
	.gamma_bus(),

	.forced_scandoubler(forced_scandoubler),

	.buttons(buttons),
	.status(status),
	.status_menumask(16'd0),
	.ps2_key(ps2_key),

    .img_mounted(media_img_mounted),.img_size(media_img_size),
    .sd_lba(media_host_lba),.sd_blk_cnt(media_host_blocks),
    .sd_rd(media_host_rd),.sd_wr(2'b0),.sd_ack(media_host_ack),
    .sd_buff_addr(media_sd_addr),.sd_buff_dout(media_sd_data),
    .sd_buff_din(media_sd_unused),.sd_buff_wr(media_sd_wr),
    .ioctl_download(ioctl_download),
    .ioctl_index(ioctl_index),
    .ioctl_wr(ioctl_wr),
    .ioctl_dout(ioctl_dout),
    .ioctl_wait(ioctl_wait)

);

