// RetroTV photographic cabinet.
//
// Five 720x480 ARGB1555 frames live at word 29'h06060000, stride 18'h15180
// (physical 0x30300000, 691200 bytes each). The fifth frame ends at word
// 29'h060C977F. The compressed stream starts at 29'h060D0000. Bit 15 is
// the glass mask: 0 passes the decoded pixel, 1 is cabinet colour expanded
// as {5 bits, 3'b0}.
//
// Main loads index 2, then 3, 4, 5, then 6. A later file does not erase an
// earlier slot. Up (extended 0x75) cycles the slot and wraps after the
// fifth. While a picture is stored, new line fetches wait so the store can
// finish. Two line banks are kept. Glass rows (y 15..393) fetch the bezel
// around the 4:3 picture: words 31..35 and 143..148. The hole is words
// 36..142 (pixels 144..571). Pixels outside the set stay clear for a later
// wall. A missed line stays transparent.

module retrotv_pixel_fifo (
    input  wire        wr_clk,
    input  wire        wr_reset,
    input  wire [15:0] wr_data,
    input  wire        wr_en,
    output wire        wr_full,
    output wire [8:0]  wr_level,

    input  wire        rd_clk,
    input  wire        rd_reset,
    input  wire        rd_en,
    output wire        rd_empty,
    output reg  [15:0] rd_data
);
    (* ramstyle = "M10K" *) reg [15:0] mem [0:255];

    reg [8:0] wr_bin;
    reg [8:0] wr_gray;
    reg [8:0] rd_bin;
    reg [8:0] rd_gray;

    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
    reg [8:0] rd_gray_w1;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
    reg [8:0] rd_gray_w2;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
    reg [8:0] wr_gray_r1;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
    reg [8:0] wr_gray_r2;

    wire [8:0] wr_bin_next = wr_bin + 9'd1;
    wire [8:0] wr_gray_next = wr_bin_next ^ {1'b0, wr_bin_next[8:1]};
    wire [8:0] rd_bin_next = rd_bin + 9'd1;
    wire [8:0] rd_gray_next = rd_bin_next ^ {1'b0, rd_bin_next[8:1]};

    assign wr_full = (wr_gray_next == {~rd_gray_w2[8:7], rd_gray_w2[6:0]});
    assign rd_empty = (rd_gray == wr_gray_r2);

    // 9-bit pointers: the difference is the occupancy, and 256 (full) fits.
    wire [8:0] rd_bin_sync = {
        rd_gray_w2[8],
        rd_gray_w2[8] ^ rd_gray_w2[7],
        rd_gray_w2[8] ^ rd_gray_w2[7] ^ rd_gray_w2[6],
        rd_gray_w2[8] ^ rd_gray_w2[7] ^ rd_gray_w2[6] ^ rd_gray_w2[5],
        rd_gray_w2[8] ^ rd_gray_w2[7] ^ rd_gray_w2[6] ^ rd_gray_w2[5] ^ rd_gray_w2[4],
        rd_gray_w2[8] ^ rd_gray_w2[7] ^ rd_gray_w2[6] ^ rd_gray_w2[5] ^ rd_gray_w2[4] ^ rd_gray_w2[3],
        rd_gray_w2[8] ^ rd_gray_w2[7] ^ rd_gray_w2[6] ^ rd_gray_w2[5] ^ rd_gray_w2[4] ^ rd_gray_w2[3] ^ rd_gray_w2[2],
        rd_gray_w2[8] ^ rd_gray_w2[7] ^ rd_gray_w2[6] ^ rd_gray_w2[5] ^ rd_gray_w2[4] ^ rd_gray_w2[3] ^ rd_gray_w2[2] ^ rd_gray_w2[1],
        rd_gray_w2[8] ^ rd_gray_w2[7] ^ rd_gray_w2[6] ^ rd_gray_w2[5] ^ rd_gray_w2[4] ^ rd_gray_w2[3] ^ rd_gray_w2[2] ^ rd_gray_w2[1] ^ rd_gray_w2[0]
    };
    assign wr_level = wr_bin - rd_bin_sync;

    // Keep the RAM template free of pointer and reset logic so it infers M10K.
    wire fifo_we = wr_en && !wr_full && !wr_reset;

    always @(posedge wr_clk) begin
        if (fifo_we)
            mem[wr_bin[7:0]] <= wr_data;
    end

    always @(posedge rd_clk) begin
        rd_data <= mem[rd_bin[7:0]];
    end

    always @(posedge wr_clk) begin
        if (wr_reset) begin
            wr_bin <= 9'd0;
            wr_gray <= 9'd0;
            rd_gray_w1 <= 9'd0;
            rd_gray_w2 <= 9'd0;
        end
        else begin
            rd_gray_w1 <= rd_gray;
            rd_gray_w2 <= rd_gray_w1;
            if (fifo_we) begin
                wr_bin <= wr_bin_next;
                wr_gray <= wr_gray_next;
            end
        end
    end

    // Registered read: rd_data is the word addressed while rd_en was high.
    always @(posedge rd_clk) begin
        if (rd_reset) begin
            rd_bin <= 9'd0;
            rd_gray <= 9'd0;
            wr_gray_r1 <= 9'd0;
            wr_gray_r2 <= 9'd0;
        end
        else begin
            wr_gray_r1 <= wr_gray;
            wr_gray_r2 <= wr_gray_r1;
            if (rd_en && !rd_empty) begin
                rd_bin <= rd_bin_next;
                rd_gray <= rd_gray_next;
            end
        end
    end
endmodule

module retrotv_line_ram (
    input  wire        wr_clk,
    input  wire        wr_en,
    input  wire [8:0]  wr_addr,
    input  wire [63:0] wr_data,
    input  wire        rd_clk,
    input  wire [8:0]  rd_addr,
    output reg  [63:0] rd_data
);
    // 512 deep so the two 180-word banks can sit at {bank, word}.
    (* ramstyle = "M10K" *) reg [63:0] mem [0:511];

    always @(posedge wr_clk) begin
        if (wr_en)
            mem[wr_addr] <= wr_data;
    end

    always @(posedge rd_clk) begin
        rd_data <= mem[rd_addr];
    end
endmodule

module retrotv_cabinet (
    input  wire        clk_sys,
    input  wire        clk_mem,
    input  wire        clk_vid,
    input  wire        reset_sys,
    input  wire        reset_mem,
    input  wire        reset_vid,

    input  wire        osd_open,
    input  wire [10:0] ps2_key,

    input  wire        compact,
    input  wire        trinitron,
    input  wire        xbr,
    input  wire        xbr_requested,
    input  wire        xbr_gallery,
    input  wire [2:0]  music_art,
    input  wire        ioctl_download,
    input  wire [15:0] ioctl_index,
    input  wire        ioctl_wr,
    input  wire [15:0] ioctl_dout,
    output wire        ioctl_wait,

    output wire [7:0]  cabinet_burstcnt,
    output wire [28:0] cabinet_addr,
    output wire [63:0] cabinet_din,
    output wire        cabinet_rd,
    output wire        cabinet_we,
    output wire        cabinet_preload,
    input  wire        cabinet_busy,
    input  wire        cabinet_dout_ready,
    input  wire [63:0] ddram_dout,

    input  wire [11:0] h_pos,
    input  wire [11:0] v_pos,
    input  wire [7:0]  r_in,
    input  wire [7:0]  g_in,
    input  wire [7:0]  b_in,
    input  wire        hs_in,
    input  wire        vs_in,
    input  wire        de_in,

    output wire [7:0]  r_out,
    output wire [7:0]  g_out,
    output wire [7:0]  b_out,
    output wire        hs_out,
    output wire        vs_out,
    output wire        de_out,
    output wire        cabinets_ready
);

localparam [28:0] CABINET_BASE = 29'h06060000;
localparam [16:0] CABINET_LAST = 17'd86399;

// 86400 words per picture. Index 6 is the fifth set. Its offset is 19 bits,
// so the slot number is no longer the low two bits of the ioctl index.
function [18:0] cabinet_slot_words;
    input [2:0] slot;
    begin
        case (slot)
            3'd0: cabinet_slot_words = 19'h00000;
            3'd1: cabinet_slot_words = 19'h15180;
            3'd2: cabinet_slot_words = 19'h2A300;
            3'd3: cabinet_slot_words = 19'h3F480;
            default: cabinet_slot_words = 19'h54600;
        endcase
    end
endfunction

localparam [2:0] PK_POP   = 3'd0;
localparam [2:0] PK_CAP   = 3'd1;
localparam [2:0] PK_WRITE = 3'd2;
localparam [2:0] PK_DRAIN = 3'd3;
localparam [2:0] PK_DROP  = 3'd4;

localparam [2:0] ST_IDLE   = 3'd0;
localparam [2:0] ST_ZERO   = 3'd1;
localparam [2:0] ST_ISSUE  = 3'd2;
localparam [2:0] ST_RECV   = 3'd3;
localparam [2:0] ST_COMMIT = 3'd4;
localparam [2:0] ST_ADDR = 3'd5;

// Picture pixels are 144..570. The hole runs through pixel 571 so both
// bezels start on a word. Left fetch is words 31..35. Right is 143..148.
localparam [7:0] BEZ_L_WORD = 8'd31;
localparam [7:0] BEZ_L_LEN  = 8'd5;
localparam [7:0] BEZ_L_END  = 8'd36;
localparam [7:0] BEZ_R_WORD = 8'd143;
localparam [7:0] BEZ_R_LEN  = 8'd6;

function [9:0] add_display_line;
    input [9:0] value;
    input [1:0] delta;
    input [10:0] limit;
    reg [10:0] sum;
    begin
        sum = {1'b0, value} + {9'd0, delta};
        add_display_line = sum >= limit ? sum - limit : sum;
    end
endfunction

// ---------------------------------------------------------------------
// ioctl index 2..6 -> pixel FIFO. Main accepts one CONF_STR file digit.
// A new download clears the packer only. Earlier slots stay in DDR.
// ---------------------------------------------------------------------
wire our_file = ioctl_download && (ioctl_index[5:0] >= 6'd2) &&
                (ioctl_index[5:0] <= 6'd6);

reg        our_d = 1'b0;
reg [5:0]  reset_cnt = 6'd0;
reg [2:0]  slot_sys = 3'd0;
reg [2:0]  xbr_slot_sys = 3'd0;
reg [2:0]  wr_slot_sys = 3'd0;
reg        key_toggle = 1'b0;
reg        up_down = 1'b0;
reg        down_down = 1'b0;

always @(posedge clk_sys) begin
    if (reset_sys) begin
        our_d <= 1'b0;
        reset_cnt <= 6'd0;
        slot_sys <= 3'd0;
        xbr_slot_sys <= 3'd0;
        wr_slot_sys <= 3'd0;
        up_down <= 1'b0;
        down_down <= 1'b0;
        key_toggle <= ps2_key[10];
    end
    else begin
        our_d <= our_file;
        if (our_file && !our_d) begin
            reset_cnt <= 6'd32;
            case (ioctl_index[5:0])
                6'd2: wr_slot_sys <= 3'd0;
                6'd3: wr_slot_sys <= 3'd1;
                6'd4: wr_slot_sys <= 3'd2;
                6'd5: wr_slot_sys <= 3'd3;
                default: wr_slot_sys <= 3'd4;
            endcase
        end
        else if (reset_cnt != 6'd0)
            reset_cnt <= reset_cnt - 6'd1;
        key_toggle <= ps2_key[10];
        if (key_toggle != ps2_key[10]) begin
            case (ps2_key[8:0])
                9'h00c: begin // F4 returns to the default XBR cabinet.
                    if (ps2_key[9] && !osd_open)
                        xbr_slot_sys <= 3'd0;
                end
                9'h175: begin
                    up_down <= ps2_key[9];
                    if (ps2_key[9] && !up_down && !osd_open) begin
                        if (!xbr_requested)
                            slot_sys <= slot_sys == 3'd4 ? 3'd0 : slot_sys + 3'd1;
                        else if (xbr_gallery)
                            xbr_slot_sys <= xbr_slot_sys == 3'd5 ? 3'd0 : xbr_slot_sys + 3'd1;
                    end
                end
                9'h172: begin
                    down_down <= ps2_key[9];
                    if (ps2_key[9] && !down_down && !osd_open && xbr_requested && xbr_gallery)
                        xbr_slot_sys <= xbr_slot_sys == 3'd0 ? 3'd5 : xbr_slot_sys - 3'd1;
                end
                default: ;
            endcase
        end
        if (!xbr_gallery)
            xbr_slot_sys <= 3'd0;
    end
end

wire fifo_reset_sys = reset_sys || (reset_cnt != 6'd0);

(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg fifo_reset_m1 = 1'b1;
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg fifo_reset_mem = 1'b1;
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg rst_m1 = 1'b1;
reg rst_mem = 1'b1;
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [2:0] slot_m1 = 3'd0;
reg [2:0] slot_m2 = 3'd0;
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [2:0] wr_m1 = 3'd0;
reg [2:0] wr_m2 = 3'd0;

always @(posedge clk_mem) begin
    fifo_reset_m1 <= fifo_reset_sys;
    fifo_reset_mem <= fifo_reset_m1;
    rst_m1 <= reset_sys;
    rst_mem <= rst_m1;
    slot_m1 <= slot_sys;
    slot_m2 <= slot_m1;
    wr_m1 <= wr_slot_sys;
    wr_m2 <= wr_m1;
end

wire        fifo_full;
wire [8:0]  fifo_level;
wire        fifo_empty;
wire [15:0] fifo_q;
reg         fifo_rd;

retrotv_pixel_fifo pixel_fifo (
    .wr_clk   (clk_sys),
    .wr_reset (fifo_reset_sys),
    .wr_data  (ioctl_dout),
    .wr_en    (our_file && ioctl_wr && !fifo_reset_sys),
    .wr_full  (fifo_full),
    .wr_level (fifo_level),
    .rd_clk   (clk_mem),
    .rd_reset (fifo_reset_mem),
    .rd_en    (fifo_rd),
    .rd_empty (fifo_empty),
    .rd_data  (fifo_q)
);

// Leave headroom for ioctl words already in flight when wait is observed.
assign ioctl_wait = our_file && (fifo_reset_sys || fifo_full || (fifo_level >= 9'd128));

// ---------------------------------------------------------------------
// Pack four pixels into a 64-bit word and store it. Fetch after that.
// ---------------------------------------------------------------------
reg [2:0]  pack = PK_POP;
reg [1:0]  pix_n = 2'd0;
reg [16:0] word_i = 17'd0;
reg [63:0] pack_word = 64'd0;
reg        loaded = 1'b0;
reg        storing = 1'b0;
reg [2:0]  view_slot = 3'd0;
reg [2:0]  view_xbr_slot = 3'd0;
wire [2:0] xbr_slot_mem;
video_config_cdc #(.WIDTH(3)) xbr_slot_config (
    .src_clk(clk_sys), .dst_clk(clk_mem), .src_data(xbr_slot_sys), .dst_data(xbr_slot_mem));

reg [2:0]  state = ST_IDLE;
reg [9:0]  fill_line = 10'd0;
reg [7:0]  zero_idx = 8'd0;
reg [2:0]  span_idx = 3'd0;
reg [7:0]  recv_count = 8'd0;
reg        drop_line = 1'b0;
reg [1:0]  prefill_count = 2'd0;
reg        steady = 1'b0;
reg        pending = 1'b0;
reg [9:0]  pending_line = 10'd0;
reg [1:0]  bank_valid = 2'b00;
reg [9:0]  bank_line0 = 10'd0;
reg [9:0]  bank_line1 = 10'd0;

reg        line_we = 1'b0;
reg [8:0]  line_waddr = 9'd0;
reg [63:0] line_wdata = 64'd0;

// Video-domain line event. Declared here so the memory FSM can synchronize it.
reg        line_toggle = 1'b0;
reg [9:0]  finished_line = 10'd0;

(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg        tog_m1 = 1'b0;
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg        tog_m2 = 1'b0;
reg        tog_seen = 1'b0;
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [9:0]  fin_m1 = 10'd0;
reg [9:0]  fin_m2 = 10'd0;

wire toggle_edge = (tog_m2 != tog_seen);
wire [2:0] layout_mem;
video_config_cdc #(.WIDTH(3)) cabinet_fill_config(
    .src_clk(clk_vid), .dst_clk(clk_mem), .src_data({xbr, trinitron, compact}), .dst_data(layout_mem));
reg [2:0] fill_layout = 3'b000;
wire fill_compact = fill_layout[0];
wire fill_trinitron = fill_layout[1];
wire fill_xbr = fill_layout[2];
wire [10:0] fill_height = fill_xbr ? 11'd720 : fill_compact ? 11'd624 : 11'd480;
reg [1:0] bank_art = 2'b00;
wire [9:0] display_now = add_display_line(fin_m2, 2'd1, fill_height);
wire catchup = toggle_edge && (state != ST_IDLE) && (display_now == fill_line);

wire glass = fill_xbr ? (fill_line >= 10'd110 && fill_line < 10'd590) :
    fill_compact ? (fill_line >= 10'd48 && fill_line < 10'd528) :
    (fill_line >= 10'd15 && fill_line < 10'd394);
wire [9:0] art_top = fill_xbr ? 10'd110 : fill_compact ? 10'd48 : 10'd15;
// The XBR layout uses the native 720x480 still-image banks.
// HPS writes only the inactive slot. Sample the published bank at the
// first glass line so a track transition cannot split a displayed still.
localparam [28:0] ART_BASE0 = 29'h061D0000; // physical 0x30E80000
localparam [28:0] ART_BASE1 = 29'h061DA000; // physical 0x30ED0000
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [2:0] art_m1 = 3'b000, art_m2 = 3'b000;
reg [2:0] art_frame = 3'b000;
reg [11:0] news_scroll = 12'd0;
reg [1:0]  news_frame_phase = 2'd0;
reg [11:0] news_line = 12'd0;
reg        news_line_bank = 1'b0;
reg [9:0]  news_outgoing_rows = 10'd0;
wire       news_step = (news_frame_phase != 2'd0);
wire [9:0] news_view_height = fill_compact ? 10'd480 : 10'd379;
reg [16:0] art_line_off = 17'd0;
wire art_line = glass && art_frame[1];
wire art_span = art_line && span_idx != 0 &&
    (fill_compact ? span_idx < 3'd4 : span_idx < 3'd3);
reg [7:0] span_word, span_len;
reg [2:0] span_last;
wire [7:0] native_bezel_words = fill_xbr ? 8'd38 : fill_trinitron ? 8'd30 : 8'd24;

always @* begin
    if (fill_compact && glass) begin
        span_last = art_line ? 3'd4 : 3'd1;
        if (span_idx == 0) begin
            span_word = 8'd0;
            span_len = native_bezel_words;
        end
        else if (art_span) begin
            span_word = native_bezel_words + {span_idx[1:0] - 2'd1, 6'b0};
            span_len = span_idx == 3'd3 ? (fill_trinitron ? 8'd52 : 8'd32) : 8'd64;
        end
        else begin
            span_word = fill_xbr ? 8'd218 : fill_trinitron ? 8'd210 : 8'd184;
            span_len = native_bezel_words;
        end
    end
    else if (glass) begin
        span_last = art_line ? 3'd3 : 3'd1;
        span_word = art_span ? (span_idx == 3'd1 ? BEZ_L_END : 8'd100) :
                               (span_idx == 0 ? BEZ_L_WORD : BEZ_R_WORD);
        span_len = art_span ? (span_idx == 3'd1 ? 8'd64 : 8'd43) :
                              (span_idx == 0 ? BEZ_L_LEN : BEZ_R_LEN);
    end
    else begin
        span_last = fill_compact ? 3'd3 : 3'd2;
        span_word = {span_idx[1:0], 6'b0};
        span_len = span_idx == span_last ?
            (fill_xbr ? 8'd64 : fill_trinitron ? 8'd48 : fill_compact ? 8'd16 : 8'd52) : 8'd64;
    end
end

wire [17:0] line_number = {8'd0,fill_line};
wire [17:0] line_off = fill_xbr ? (line_number << 8) :
    (line_number << 7) + (line_number << 4) +
    (fill_compact ? (line_number << 6) : ((line_number << 5) + (line_number << 2))) +
    (fill_trinitron ? (line_number << 5) : 18'd0);
// Six gallery frames at physical 0x31B00000, each with a 2 MiB stride.
wire [28:0] xbr_frame_base = 29'h06360000 + {8'd0,view_xbr_slot,18'd0};
wire [28:0] cabinet_frame_base = fill_xbr ? xbr_frame_base :
    fill_trinitron ? 29'h062E0000 : // physical 0x31700000
    fill_compact ? (29'h06200000 + {9'd0,view_slot,17'd0}) :
    (CABINET_BASE + {10'd0,cabinet_slot_words(view_slot)});
wire [28:0] art_frame_base = fill_trinitron ?
    (art_frame[0] ? 29'h06340000 : 29'h06320000) : // physical 0x31A00000 / 0x31900000
    fill_compact ? (art_frame[0] ? 29'h062C0000 : 29'h062A0000) :
    (art_frame[0] ? ART_BASE1 : ART_BASE0);
// Each news row uses one of the two 4096-row buffers for this layout.
wire [2:0] news_page = fill_trinitron ? {2'b10,news_line_bank} :
    fill_compact ? {2'b01,news_line_bank} : {2'b00,news_line_bank};
wire [28:0] news_line_addr = 29'h06500000 + {6'd0,news_page,news_line,8'd0};
wire [28:0] art_line_addr = art_frame[2] ? news_line_addr :
    art_frame_base + {12'd0,art_line_off};
wire [28:0] fetch_addr = art_span ?
    art_line_addr +
        (span_idx == 3'd3 ? 29'd128 : span_idx == 3'd2 ? 29'd64 : 29'd0) :
    cabinet_frame_base + {11'd0,line_off} + {21'd0,span_word};
reg [28:0] fetch_addr_q = 29'd0;
reg [7:0] fetch_len_q = 8'd0;
wire [28:0] store_addr = CABINET_BASE +
    {10'd0, cabinet_slot_words(wr_m2)} + {12'd0, word_i};

// The decoder reset is still held while Main sends the picture. Holding
// stores for that reset stalls ioctl_wait and never reaches the movie mount.
// A later cabinet file resets the packer only. The television keeps fetching.
wire store_hold = fifo_reset_mem;
wire fetch_hold = rst_mem;
wire nf_mem = fifo_reset_mem && !rst_mem;
// Preload stays high for every picture, not just the first, so a quiesced
// decoder cannot stall the later ioctl files.
assign cabinet_preload = storing || !loaded;
assign cabinet_we = (pack == PK_WRITE) && !store_hold;
assign cabinet_rd = (state == ST_ISSUE) && !fetch_hold && !catchup;
// An open fetch keeps its length even if a store word is ready. The write
// grant already requires cabinet_rd to be low, and the packer waits out
// ST_ISSUE so that word is not retired as a completed store.
assign cabinet_burstcnt = cabinet_rd ? fetch_len_q : cabinet_we ? 8'd1 : 8'd0;
assign cabinet_addr = cabinet_rd ? fetch_addr_q :
                      cabinet_we ? store_addr : 29'd0;
assign cabinet_din = pack_word;

wire [9:0] pending_target = add_display_line(
    toggle_edge ? fin_m2 : pending_line, 2'd2, fill_height);
wire [16:0] art_row = {7'd0,pending_target} - {7'd0,art_top};
// During a refresh, the old strip continues above the join. Row zero of
// the new strip follows it, so the join moves with the ordinary scroll.
wire [10:0] incoming_news_row = {1'b0,art_row[9:0]} - {1'b0,news_outgoing_rows};
wire news_use_old_bank = (news_outgoing_rows != 10'd0) && incoming_news_row[10];
wire news_use_incoming_row = (news_outgoing_rows != 10'd0) && !incoming_news_row[10];
wire [16:0] art_row_words = fill_trinitron ?
    (art_row << 7) + (art_row << 5) + (art_row << 4) + (art_row << 2) :
    fill_compact ? (art_row << 7) + (art_row << 5) :
    (art_row << 6) + (art_row << 5) + (art_row << 3) + (art_row << 1) + art_row;

always @(posedge clk_mem) begin
    art_m1 <= music_art;
    art_m2 <= art_m1;
    line_we <= 1'b0;
    fifo_rd <= 1'b0;

    if (rst_mem) begin
        art_frame <= 3'b000;
        news_scroll <= 12'd0;
        news_frame_phase <= 2'd0;
        news_line <= 12'd0;
        news_line_bank <= 1'b0;
        news_outgoing_rows <= 10'd0;
        art_line_off <= 17'd0;
        fill_layout <= 3'b000;
        bank_art <= 2'b00;
        pack <= PK_POP;
        pix_n <= 2'd0;
        word_i <= 17'd0;
        loaded <= 1'b0;
        storing <= 1'b0;
        view_slot <= 3'd0;
        view_xbr_slot <= 3'd0;
        state <= ST_IDLE;
        zero_idx <= 8'd0;
        span_idx <= 3'd0;
        recv_count <= 8'd0;
        drop_line <= 1'b0;
        prefill_count <= 2'd0;
        steady <= 1'b0;
        pending <= 1'b0;
        bank_valid <= 2'b00;
        tog_m1 <= 1'b0;
        tog_m2 <= 1'b0;
        tog_seen <= 1'b0;
        fin_m1 <= 10'd0;
        fin_m2 <= 10'd0;
    end
    else begin
        tog_m1 <= line_toggle;
        tog_m2 <= tog_m1;
        fin_m1 <= finished_line;
        fin_m2 <= fin_m1;
        if (toggle_edge) begin
            tog_seen <= tog_m2;
            pending <= 1'b1;
            pending_line <= fin_m2;
        end
        if (state == ST_IDLE)
            view_slot <= slot_m2;

        if (nf_mem) begin
            pack <= PK_POP;
            pix_n <= 2'd0;
            word_i <= 17'd0;
            storing <= 1'b1;
        end
        else case (pack)
            PK_POP: begin
                if (storing && !fifo_empty) begin
                    fifo_rd <= 1'b1;
                    pack <= PK_CAP;
                end
            end
            PK_CAP: begin
                case (pix_n)
                    2'd0: pack_word[15:0] <= fifo_q;
                    2'd1: pack_word[31:16] <= fifo_q;
                    2'd2: pack_word[47:32] <= fifo_q;
                    default: pack_word[63:48] <= fifo_q;
                endcase
                if (pix_n == 2'd3) begin
                    pix_n <= 2'd0;
                    pack <= PK_WRITE;
                end
                else begin
                    pix_n <= pix_n + 2'd1;
                    pack <= PK_POP;
                end
            end
            PK_WRITE: begin
                // cabinet_busy follows the fetch while ST_ISSUE is open.
                // Retiring the word on that busy flag would skip the store.
                if (!cabinet_busy && (state != ST_ISSUE)) begin
                    if (word_i == CABINET_LAST) begin
                        storing <= 1'b0;
                        pack <= PK_DRAIN;
                        // Five pictures arrive as separate files. Revealing
                        // the set after the first one draws a piece of the
                        // bezel, then black, for every later file. Slot 4
                        // is the last file in the launcher.
                        if (wr_m2 == 3'd4)
                            loaded <= 1'b1;
                    end
                    else begin
                        word_i <= word_i + 17'd1;
                        pack <= PK_POP;
                    end
                end
            end
            PK_DRAIN: begin
                if (!fifo_empty) begin
                    fifo_rd <= 1'b1;
                    pack <= PK_DROP;
                end
            end
            PK_DROP: begin
                pack <= PK_DRAIN;
            end
            default: begin
                pack <= PK_POP;
            end
        endcase

        case (state)
            ST_IDLE: begin
                // Finish the open line, then let a picture store use the bus.
                // Pausing here keeps the last bezels on screen.
                if (fill_layout != layout_mem) begin
                    fill_layout <= layout_mem;
                    view_xbr_slot <= xbr_slot_mem;
                    bank_valid <= 2'b00;
                    pending <= 1'b0;
                    prefill_count <= 2'd0;
                    steady <= 1'b0;
                end
                else if (loaded && !storing && !steady && (prefill_count < 2'd2)) begin
                    fill_line <= (prefill_count == 2'd0) ? 10'd0 : 10'd1;
                    bank_valid[prefill_count[0]] <= 1'b0;
                    zero_idx <= 8'd0;
                    span_idx <= 3'd0;
                    drop_line <= 1'b0;
                    if (prefill_count == 2'd1)
                        steady <= 1'b1;
                    prefill_count <= prefill_count + 2'd1;
                    // Request DDR immediately. Blanking 180 words first made
                    // the refill miss the line it was meant to catch.
                    state <= ST_ADDR;
                end
                else if (loaded && !storing && (pending || toggle_edge)) begin
                    steady <= 1'b1;
                    pending <= 1'b0;
                    fill_line <= pending_target;
                    // Latch before fetching line zero so an arrow cannot split a frame.
                    if (fill_xbr && pending_target == 10'd0)
                        view_xbr_slot <= xbr_slot_mem;
                    art_line_off <= art_row_words;
                    news_line <= news_use_incoming_row ?
                        {2'b00,incoming_news_row[9:0]} : news_scroll + {2'b00,art_row[9:0]};
                    news_line_bank <= art_frame[0] ^ news_use_old_bank;
                    if (pending_target == 10'd0) begin
                        art_frame <= art_m2;
                        if (art_m2[2:1] != 2'b11 || art_frame[2:1] != 2'b11) begin
                            news_scroll <= 12'd0;
                            news_frame_phase <= 2'd0;
                            news_outgoing_rows <= 10'd0;
                        end else begin
                            news_frame_phase <= news_frame_phase + 2'd1;
                            if (art_m2[0] != art_frame[0])
                                news_outgoing_rows <= news_view_height - {9'd0,news_step};
                            else if (news_outgoing_rows != 10'd0 && news_step)
                                news_outgoing_rows <= news_outgoing_rows - 10'd1;

                            // Advance on three of every four input frames.
                            if (news_step)
                                news_scroll <= (news_outgoing_rows == 10'd1) ?
                                    12'd0 : news_scroll + 12'd1;
                        end
                    end else if (pending_target <= art_top && !art_m2[2] && !art_frame[2]) begin
                        art_frame <= art_m2;
                    end
                    bank_valid[pending_target[0]] <= 1'b0;
                    zero_idx <= 8'd0;
                    span_idx <= 3'd0;
                    drop_line <= 1'b0;
                    state <= ST_ADDR;
                end
            end

            ST_ZERO: begin
                // Glass only, after the left bezel burst. No DDR request is
                // open, so the line can be abandoned. Words outside 31..35
                // are cleared, including the right bezel. The next burst
                // rewrites words 143..148.
                if (catchup) begin
                    state <= ST_IDLE;
                end
                else begin
                    if ((zero_idx < BEZ_L_WORD) || (zero_idx >= BEZ_L_END)) begin
                        line_we <= 1'b1;
                        line_waddr <= {fill_line[0], zero_idx};
                        line_wdata <= 64'd0;
                    end
                    if (zero_idx == 8'd179) begin
                        span_idx <= 3'd1;
                        state <= ST_ADDR;
                    end
                    else
                        zero_idx <= zero_idx + 8'd1;
                end
            end

            ST_ADDR: begin
                if (catchup)
                    state <= ST_IDLE;
                else begin
                    fetch_addr_q <= fetch_addr;
                    fetch_len_q <= span_len;
                    state <= ST_ISSUE;
                end
            end

            ST_ISSUE: begin
                // cabinet_rd drops on catchup, so this cycle is not accepted.
                if (catchup) begin
                    state <= ST_IDLE;
                end
                else if (!cabinet_busy) begin
                    recv_count <= 8'd0;
                    state <= ST_RECV;
                end
            end

            ST_RECV: begin
                // Finish an accepted burst so its descriptor cannot be
                // counted as a later line. A late line is not published.
                if (catchup)
                    drop_line <= 1'b1;
                if (cabinet_dout_ready) begin
                    if (!(drop_line || catchup)) begin
                        line_we <= 1'b1;
                        line_waddr <= {fill_line[0], span_word + recv_count};
                        line_wdata <= ddram_dout;
                    end
                    if (recv_count == (fetch_len_q - 8'd1)) begin
                        if (drop_line || catchup)
                            state <= ST_IDLE;
                        else if (glass && !fill_compact && !art_line && (span_idx == 0)) begin
                            zero_idx <= 8'd0;
                            state <= ST_ZERO;
                        end
                        else if (span_idx == span_last)
                            state <= ST_COMMIT;
                        else begin
                            span_idx <= span_idx + 3'd1;
                            state <= ST_ADDR;
                        end
                    end
                    else
                        recv_count <= recv_count + 8'd1;
                end
            end

            default: begin
                if (!(catchup || drop_line)) begin
                    if (fill_line[0])
                        bank_line1 <= fill_line;
                    else
                        bank_line0 <= fill_line;
                    bank_valid[fill_line[0]] <= 1'b1;
                    bank_art[fill_line[0]] <= art_line;
                end
                state <= ST_IDLE;
            end
        endcase
    end
end

// ---------------------------------------------------------------------
// Video. h/v are delayed twice so they match fb_video_*, then the line
// RAM adds the same one-clock delay the old ROM compositor used.
// ---------------------------------------------------------------------
reg [3:0]  arm_sr = 4'd0;
reg [11:0] h_d = 12'd0;
reg [11:0] v_d = 12'd0;
reg [11:0] h_q = 12'd0;
reg [11:0] v_q = 12'd0;
wire [11:0] active_height = xbr ? 12'd720 : compact ? 12'd624 : 12'd480;
wire line_finished = (h_pos == 12'd0) && (h_d != 12'd0) && (v_d < active_height);

always @(posedge clk_vid) begin
    if (reset_vid) begin
        line_toggle <= 1'b0;
        finished_line <= 10'd0;
        arm_sr <= 4'd0;
        h_d <= 12'd0;
        v_d <= 12'd0;
    end
    else begin
        h_d <= h_pos;
        v_d <= v_pos;
        arm_sr <= {arm_sr[2:0], line_finished};
        if (line_finished)
            finished_line <= v_d[9:0];
        if (arm_sr[3])
            line_toggle <= ~line_toggle;
    end
    h_q <= h_d;
    v_q <= v_d;
end

(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg        loaded_m1 = 1'b0;
reg        loaded_m2 = 1'b0;
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [1:0]  bv_m1 = 2'b00;
reg [1:0]  bv_m2 = 2'b00;
reg [1:0]  ba_m1 = 2'b00, ba_m2 = 2'b00;
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [9:0]  bl0_m1 = 10'd0;
reg [9:0]  bl0_m2 = 10'd0;
(* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
reg [9:0]  bl1_m1 = 10'd0;
reg [9:0]  bl1_m2 = 10'd0;

reg [1:0]  lane_q = 2'd0;
reg [11:0] h_qq = 12'd0;
reg [11:0] v_qq = 12'd0;
reg [23:0] video_q = 24'd0;
reg        hs_q = 1'b1;
reg        vs_q = 1'b1;
reg        de_q = 1'b0;
reg        loaded_q = 1'b0;
reg        valid_q = 1'b0;
reg        line_art_q = 1'b0;
reg [9:0]  line_q = 10'd0;

wire [11:0] active_width = xbr ? 12'd1024 : trinitron ? 12'd960 : compact ? 12'd832 : 12'd720;
wire [7:0] vid_word = h_q < active_width ? h_q[9:2] : 8'd0;
wire [63:0] cab_word;

retrotv_line_ram line_ram (
    .wr_clk  (clk_mem),
    .wr_en   (line_we),
    .wr_addr (line_waddr),
    .wr_data (line_wdata),
    .rd_clk  (clk_vid),
    .rd_addr ({v_q[0], vid_word}),
    .rd_data (cab_word)
);

always @(posedge clk_vid) begin
    loaded_m1 <= loaded;
    loaded_m2 <= loaded_m1;
    bv_m1 <= bank_valid;
    bv_m2 <= bv_m1;
    ba_m1 <= bank_art;
    ba_m2 <= ba_m1;
    bl0_m1 <= bank_line0;
    bl0_m2 <= bl0_m1;
    bl1_m1 <= bank_line1;
    bl1_m2 <= bl1_m1;

    lane_q <= h_q[1:0];
    h_qq <= h_q;
    v_qq <= v_q;
    video_q <= {r_in, g_in, b_in};
    hs_q <= hs_in;
    vs_q <= vs_in;
    de_q <= de_in;
    loaded_q <= loaded_m2;
    valid_q <= bv_m2[v_q[0]];
    line_art_q <= ba_m2[v_q[0]];
    line_q <= v_q[0] ? bl1_m2 : bl0_m2;
end

wire [15:0] cab_pix =
    (lane_q == 2'd0) ? cab_word[15:0] :
    (lane_q == 2'd1) ? cab_word[31:16] :
    (lane_q == 2'd2) ? cab_word[47:32] :
                       cab_word[63:48];

wire [11:0] pane_left = xbr ? 12'd152 : trinitron ? 12'd120 : 12'd96;
wire [11:0] pane_right = xbr ? 12'd872 : trinitron ? 12'd840 : 12'd736;
wire [11:0] pane_top = xbr ? 12'd110 : 12'd48;
wire [11:0] pane_bottom = xbr ? 12'd590 : 12'd528;
wire compact_pane = h_qq >= pane_left && h_qq < pane_right &&
    v_qq >= pane_top && v_qq < pane_bottom;
wire legacy_cabinet_bounds = h_qq < 12'd720 && v_qq < 12'd480 &&
    ((v_qq < 12'd15) || (v_qq >= 12'd394) ||
        ((h_qq >= 12'd124) && (h_qq < 12'd596)));
wire compact_cabinet_bounds = h_qq < active_width && v_qq < active_height &&
    (!compact_pane || line_art_q);
wire show_cabinet = loaded_q && valid_q && de_q && cab_pix[15] &&
    (v_qq[9:0] == line_q) &&
    (compact ? compact_cabinet_bounds : legacy_cabinet_bounds);

wire [23:0] cabinet_rgb = {
    cab_pix[14:10], 3'b000,
    cab_pix[9:5],   3'b000,
    cab_pix[4:0],   3'b000
};

wire [23:0] rgb = loaded_q ? (show_cabinet ? cabinet_rgb : video_q) : 24'd0;

assign cabinets_ready = loaded_q;
assign r_out = rgb[23:16];
assign g_out = rgb[15:8];
assign b_out = rgb[7:0];
assign hs_out = hs_q;
assign vs_out = vs_q;
assign de_out = de_q;

endmodule
