// Center a decoded picture within the selected progressive raster.
// Geometry is presentation policy only; coded coordinates remain unchanged.
module mpeg2_progressive_geometry
(
    input  wire        pixel_en,
    input  wire        compact,
    input  wire        trinitron,
    input  wire        xbr,
    input  wire [11:0] h_pos,
    input  wire [11:0] v_pos,
    input  wire [11:0] picture_width,
    input  wire [10:0] picture_height,
    output wire [11:0] origin_x,
    output wire [11:0] origin_y,
    output wire        source_window,
    output wire [11:0] source_x,
    output wire [11:0] source_y
);

wire [11:0] active_width = xbr ? 12'd1024 : trinitron ? 12'd960 : compact ? 12'd832 : 12'd720;
assign origin_x = (active_width - picture_width) >> 1;
assign origin_y = ((12'd480 - {1'b0, picture_height}) >> 1) +
    (xbr ? 12'd110 : compact ? 12'd48 : 12'd0);
assign source_window = pixel_en &&
    (picture_width != 12'd0) && (picture_width <= 12'd720) &&
    (picture_height != 11'd0) && (picture_height <= 11'd480) &&
    (!compact || trinitron || (h_pos >= 12'd96 && h_pos < 12'd736)) &&
    (h_pos >= origin_x) && (h_pos < (origin_x + picture_width)) &&
    (v_pos >= origin_y) &&
    (v_pos < (origin_y + {1'b0, picture_height}));
assign source_x = h_pos - origin_x;
assign source_y = v_pos - origin_y;

endmodule
