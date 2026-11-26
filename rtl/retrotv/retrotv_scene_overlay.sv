// HDMI art plane. ARM composes the static room and cabinet into one ARGB1555
// image, leaving the native video window clear. The spare RAM port streams
// the currently selected bank while the other bank can be updated.
module retrotv_scene_overlay #(
    parameter FRAME_BURSTS = 16200
)(
    input wire reset,
    input wire video_clk,
    input wire mem_clk,
    input wire [1:0] scene, // {enabled, bank}, synchronized to video_clk
    input wire [23:0] rgb,
    input wire hs, vs, de, border,
    output reg [23:0] rgb_out,
    output reg hs_out, vs_out, de_out, border_out,
    output reg [28:0] read_address = 0,
    output reg read_request = 0,
    input wire [63:0] read_data,
    input wire read_valid
);
    localparam [28:0] BANK0 = 29'h06C00000; // bytes 0x36000000
    localparam [28:0] BANK1 = 29'h06C80000; // bytes 0x36400000
    localparam BURST_WORDS = 32;

    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
    reg [1:0] video_reset = 2'b11, mem_reset = 2'b11;
    always @(posedge video_clk) video_reset <= {video_reset[0], reset};
    always @(posedge mem_clk) mem_reset <= {mem_reset[0], reset};

    reg old_vs = 0, frame_token = 0;
    reg [1:0] frame_scene = 0;
    wire frame_start = vs && !old_vs;
    wire [2:0] request_mem;

    video_config_cdc #(.WIDTH(3)) scene_frame_cdc (
        .src_clk(video_clk), .dst_clk(mem_clk),
        .src_data({frame_token, frame_scene}), .dst_data(request_mem)
    );

    reg [1:0] lane = 0;
    reg starved = 0;
    wire fifo_empty, fifo_full;
    wire [8:0] fifo_level;
    wire [63:0] pixels;
    wire drawing = frame_scene[1] && de && !starved;
    wire pop = drawing && lane == 2'd2;
    reg [15:0] art_pixel;
    always @* begin
        case (lane)
            2'd0: art_pixel = pixels[15:0];
            2'd1: art_pixel = pixels[31:16];
            2'd2: art_pixel = pixels[47:32];
            2'd3: art_pixel = pixels[63:48];
        endcase
    end

    always @(posedge video_clk) begin
        old_vs <= vs;
        hs_out <= hs;
        vs_out <= vs;
        de_out <= de;
        border_out <= border;
        if (drawing && (lane != 0 || !fifo_empty) && art_pixel[15]) begin
            rgb_out <= {art_pixel[14:10], 3'b000, art_pixel[9:5], 3'b000, art_pixel[4:0], 3'b000};
            border_out <= 0;
        end else
            rgb_out <= rgb;

        if (video_reset[1]) begin
            frame_scene <= 0;
            frame_token <= 0;
            lane <= 0;
            starved <= 0;
        end else if (frame_start) begin
            frame_scene <= scene;
            frame_token <= ~frame_token;
            lane <= 0;
            starved <= 0;
        end else if (drawing) begin
            lane <= lane + 1'd1;
            if (lane == 0 && fifo_empty)
                starved <= 1;
        end
    end

    reg active_token = 0;
    wire frame_changed = request_mem[2] != active_token;
    reg [5:0] in_flight = 0;
    reg [13:0] bursts_left = 0;
    reg [28:0] next_address = 0;
    wire restart = frame_changed && in_flight == 0;
    wire push = read_valid && in_flight != 0 && !frame_changed;

    retrotv_pixel_fifo #(.DATA_WIDTH(64)) scene_pixels (
        .wr_clk(mem_clk), .wr_reset(mem_reset[1] || restart),
        .wr_data(read_data), .wr_en(push),
        .wr_full(fifo_full), .wr_level(fifo_level),
        .rd_clk(video_clk), .rd_reset(video_reset[1] || frame_start),
        .rd_en(pop), .rd_empty(fifo_empty), .rd_data(pixels)
    );

    always @(posedge mem_clk) begin
        if (mem_reset[1]) begin
            active_token <= 0;
            in_flight <= 0;
            bursts_left <= 0;
            next_address <= 0;
            // Preserve the request toggle so resetting this client does not
            // produce a fresh request before the DDR service sees it.
        end else if (restart) begin
            active_token <= request_mem[2];
            bursts_left <= request_mem[1] ? FRAME_BURSTS : 0;
            next_address <= request_mem[0] ? BANK1 : BANK0;
        end else if (in_flight != 0) begin
            if (read_valid)
                in_flight <= in_flight - 1'd1;
        end else if (bursts_left != 0 && fifo_level <= 9'd223 && !fifo_full) begin
            read_address <= next_address;
            read_request <= ~read_request;
            next_address <= next_address + 29'd32;
            in_flight <= BURST_WORDS;
            bursts_left <= bursts_left - 1'd1;
        end
    end
endmodule
