// Fixed 27 MHz progressive rasters, negative sync.
// Default: 858x525 total (60000/1001 Hz). Optional: 864x625 (50 Hz).
// The 50 Hz mode is an internal scaler input with extended vertical blanking,
// not a 576-line decoding mode. Requests apply after the last pixel of a frame.
module mpeg2_video_720x480p #(parameter ENABLE_REFRESH_SELECTION=0)
(
	input  wire        clk,
	input  wire        reset,

	output wire [11:0] h_pos,
	output wire [11:0] v_pos,
	output wire        pixel_en,
	output wire        h_sync,
	output wire        v_sync,
	input  wire        refresh_50_request,
	output reg         refresh_50_active = 0,
	input  wire        compact_request,
	output reg         compact_active = 0,
	input  wire        trinitron_request,
	output reg         trinitron_active = 0,
	input  wire        xbr_request,
	output reg         xbr_active = 0
);

wire [11:0] h_active = xbr_active ? 12'd1024 : trinitron_active ? 12'd960 : compact_active ? 12'd832 : 12'd720;
wire [11:0] v_active = xbr_active ? 12'd720 : compact_active ? 12'd624 : 12'd480;
localparam integer V_FRONT  = 9;
localparam integer V_SYNC   = 6;

// Both native cabinet timings have 900900 total clocks per frame.
wire [11:0] h_last = xbr_active ? 12'd1169 : compact_active ? 12'd1299 : refresh_50_active ? 12'd863 : 12'd857;
wire [11:0] v_last = xbr_active ? 12'd769 : compact_active ? 12'd692 : refresh_50_active ? 12'd624 : 12'd524;
// Keep the active origin and vertical sync start fixed. The extra lines are
// blanking; no line cache or decoder geometry changes with refresh rate.
wire [11:0] hs_start = xbr_active ? 12'd1048 : trinitron_active ? 12'd984 : compact_active ? 12'd856 : refresh_50_active ? 12'd732 : 12'd736;
wire [11:0] hs_end = xbr_active ? 12'd1110 : trinitron_active ? 12'd1046 : compact_active ? 12'd918 : refresh_50_active ? 12'd796 : 12'd798;

reg [11:0] h_count;
reg [11:0] v_count;

always @(posedge clk) begin
	if (reset) begin
		h_count <= 12'd0;
		v_count <= 12'd0;
		refresh_50_active <= 1'b0;
		compact_active <= 1'b0;
		trinitron_active <= 1'b0;
		xbr_active <= 1'b0;
	end
	else if (h_count == h_last) begin
		h_count <= 12'd0;

		if (v_count == v_last) begin
			v_count <= 12'd0;
			refresh_50_active <= ENABLE_REFRESH_SELECTION ? refresh_50_request : 1'b0;
			compact_active <= compact_request;
			trinitron_active <= trinitron_request;
			xbr_active <= xbr_request;
		end
		else
			v_count <= v_count + 12'd1;
	end
	else begin
		h_count <= h_count + 12'd1;
	end
end

assign h_pos = h_count;
assign v_pos = v_count;

assign pixel_en =
	(h_count < h_active) &&
	(v_count < v_active);

assign h_sync = !(
	(h_count >= hs_start) &&
	(h_count < hs_end));

assign v_sync = !(
	(v_count >= v_active + V_FRONT) &&
	(v_count <  v_active + V_FRONT + V_SYNC));

endmodule
