// RetroTV cabinet compositor.
//
// The MPEG-2 picture arrives on fb_video_* two clocks after the coordinates
// produced by mpeg2_video_720x480p. Those counters already describe the
// 720x480 active raster, including the 50 Hz blanking extension, so the
// cabinet address is the delayed counter rather than a DE/VS edge tracker.
//
// Index 0 is transparent and the decoded pixel is kept. Any other index is
// a cabinet colour. The ROM is 144x96 because this core has eight M10K
// blocks free; each 4-bit entry consumes one 2048-deep block word.
// 144x96 leaves one block spare. A 360x240 image needs about 43 blocks.

module retrotv_compositor #(
    parameter integer ROM_W   = 144,
    parameter integer ROM_H   = 96,
    parameter integer VIDEO_W = 720,
    parameter integer VIDEO_H = 480
) (
    input  wire        clk,
    input  wire        reset,
    input  wire        enable,

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
    output wire        de_out
);

localparam integer SCALE = VIDEO_W / ROM_W;
localparam integer ROM_SIZE = ROM_W * ROM_H;

initial begin
    if ((VIDEO_W != ROM_W * SCALE) || (VIDEO_H != ROM_H * SCALE))
        $error("RetroTV ROM scale does not cover the 720x480 raster evenly.");
end

(* ramstyle = "M10K" *) reg [3:0] bezel_rom [0:ROM_SIZE-1];
(* ramstyle = "logic" *) reg [23:0] palette [0:15];

initial begin
    $readmemh("rtl/retrotv/bezel_pixels.mem", bezel_rom);
    $readmemh("rtl/retrotv/bezel_palette.mem", palette);
end

// Two registers line the timing counters up with fb_video_*.
reg [11:0] h_d = 0;
reg [11:0] v_d = 0;
reg [11:0] h_q = 0;
reg [11:0] v_q = 0;

always @(posedge clk) begin
    if (reset) begin
        h_d <= 12'd0;
        v_d <= 12'd0;
        h_q <= 12'd0;
        v_q <= 12'd0;
    end
    else begin
        h_d <= h_pos;
        v_d <= v_pos;
        h_q <= h_d;
        v_q <= v_d;
    end
end

wire        active = (h_q < VIDEO_W) && (v_q < VIDEO_H);
wire [11:0] h_vis  = active ? h_q : 12'd0;
wire [11:0] v_vis  = active ? v_q : 12'd0;
wire [7:0]  rom_x  = h_vis / SCALE;
wire [7:0]  rom_y  = v_vis / SCALE;
wire [31:0] rom_product = {6'd0, rom_y} * ROM_W;
wire [13:0] rom_addr = rom_product[13:0] + {6'd0, rom_x};

reg [3:0]  index_q = 0;
reg [23:0] video_q = 0;
reg        hs_q = 0;
reg        vs_q = 0;
reg        de_q = 0;
reg        enable_q = 0;

always @(posedge clk) begin
    index_q  <= bezel_rom[rom_addr];
    video_q  <= {r_in, g_in, b_in};
    hs_q     <= hs_in;
    vs_q     <= vs_in;
    de_q     <= de_in;
    enable_q <= enable;
end

wire [23:0] cabinet = palette[index_q];
wire        show_cabinet = enable_q && de_q && (index_q != 4'd0);
wire [23:0] rgb = show_cabinet ? cabinet : video_q;

assign r_out  = rgb[23:16];
assign g_out  = rgb[15:8];
assign b_out  = rgb[7:0];
assign hs_out = hs_q;
assign vs_out = vs_q;
assign de_out = de_q;

endmodule
