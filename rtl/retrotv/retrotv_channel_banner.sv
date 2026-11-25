// Channel title drawn over the cabinet output.
// Glyphs are the same 5x7 overlay font, doubled so the name reads on a TV.
// The label sits in the upper right of the tube. The name is stable in the
// system clock long before name_tog flips.
module retrotv_channel_banner (
    input  wire        clk_vid,
    input  wire        reset_vid,
    input  wire [11:0] h_pos,
    input  wire [11:0] v_pos,
    input  wire [7:0]  r_in,
    input  wire [7:0]  g_in,
    input  wire [7:0]  b_in,
    input  wire        hs_in,
    input  wire        vs_in,
    input  wire        de_in,
    input  wire [255:0] name_flat,
    input  wire [5:0]  name_len,
    input  wire        name_tog,
    input  wire        hold_in,
    input  wire        compact,
    input  wire        trinitron,
    input  wire        xbr,
    output wire [7:0]  r_out,
    output wire [7:0]  g_out,
    output wire [7:0]  b_out,
    output wire        hs_out,
    output wire        vs_out,
    output wire        de_out
);
    wire [11:0] glass_x0 = xbr ? 12'd152 : trinitron ? 12'd120 : compact ? 12'd96 : 12'd144;
    wire [11:0] glass_x1 = xbr ? 12'd871 : trinitron ? 12'd839 : compact ? 12'd735 : 12'd571;
    localparam [11:0] EDGE     = 12'd8;
    wire [11:0] bar_y0 = xbr ? 12'd113 : compact ? 12'd51 : 12'd18;
    wire [11:0] bar_y1 = xbr ? 12'd135 : compact ? 12'd73 : 12'd40;
    wire [11:0] text_y0 = xbr ? 12'd117 : compact ? 12'd55 : 12'd22;

    (* ramstyle = "M10K" *) reg [4:0] font [0:2047];
    initial $readmemb("rtl/media_overlay_font.mem", font);

    reg [7:0] chars [0:31];
    reg [5:0] len_q = 6'd0;
    reg [7:0] frames = 8'd0;
    reg       vs_d = 1'b0;
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED_IF_ASYNCHRONOUS" *)
    reg       tog1 = 1'b0;
    reg       tog2 = 1'b0;
    reg       tog3 = 1'b0;
    integer   copy_i;

    // Cabinet RGB already matches a coordinate delayed three video clocks.
    reg [11:0] h1 = 12'd0, h2 = 12'd0, h3 = 12'd0;
    reg [11:0] v1 = 12'd0, v2 = 12'd0, v3 = 12'd0;

    wire banner_on = (frames != 0) && (len_q != 0);
    wire [11:0] text_w = (len_q == 0) ? 12'd0 : ({6'd0, len_q} * 12'd12) - 12'd2;
    wire [11:0] text_left = glass_x1 - text_w - EDGE;
    wire [11:0] bar_l = (text_left > glass_x0 + 12'd6) ? text_left - 12'd6 : glass_x0;
    wire [11:0] bar_r_raw = text_left + text_w + 12'd6;
    wire [11:0] bar_r = (bar_r_raw > glass_x1) ? glass_x1 : bar_r_raw;
    // h_pos advances one pixel every video clock, so the cell index is a
    // counter reset at the first text pixel. A divider here misses timing.
    reg [5:0] scan_i = 6'd0;
    reg [3:0] scan_sub = 4'd0;
    wire        in_bar = banner_on && de_in && (v3 >= bar_y0) && (v3 < bar_y1) &&
                         (h3 >= bar_l) && (h3 < bar_r);
    wire        in_glyph = in_bar && (h3 >= text_left) && (h3 < text_left + text_w) &&
                           (scan_sub < 4'd10) && (v3 >= text_y0) && (v3 < text_y0 + 12'd14) &&
                           (scan_i < {1'b0, len_q});

    reg [7:0] p1_r = 8'd0, p1_g = 8'd0, p1_b = 8'd0;
    reg       p1_hs = 1'b1, p1_vs = 1'b1, p1_de = 1'b0;
    reg       p1_bar = 1'b0, p1_glyph = 1'b0;
    reg [2:0] p1_gx = 3'd0, p1_gy = 3'd0;
    reg [4:0] p1_glyph_i = 5'd0;

    reg [7:0] p2_r = 8'd0, p2_g = 8'd0, p2_b = 8'd0;
    reg       p2_hs = 1'b1, p2_vs = 1'b1, p2_de = 1'b0;
    reg       p2_bar = 1'b0, p2_glyph = 1'b0;
    reg [2:0] p2_gx = 3'd0;
    reg [10:0] font_addr = 11'd0;

    reg [7:0] p3_r = 8'd0, p3_g = 8'd0, p3_b = 8'd0;
    reg       p3_hs = 1'b1, p3_vs = 1'b1, p3_de = 1'b0;
    reg       p3_bar = 1'b0, p3_glyph = 1'b0;
    reg [2:0] p3_gx = 3'd0;
    reg [4:0] font_row = 5'd0;

    reg glyph_bit = 1'b0;
    always @* begin
        glyph_bit = 1'b0;
        if (p3_gx == 3'd0) glyph_bit = font_row[4];
        else if (p3_gx == 3'd1) glyph_bit = font_row[3];
        else if (p3_gx == 3'd2) glyph_bit = font_row[2];
        else if (p3_gx == 3'd3) glyph_bit = font_row[1];
        else if (p3_gx == 3'd4) glyph_bit = font_row[0];
    end
    wire glyph_on = p3_glyph && glyph_bit;

    assign r_out = glyph_on ? 8'hF2 : (p3_bar ? 8'h18 : p3_r);
    assign g_out = glyph_on ? 8'hF2 : (p3_bar ? 8'h18 : p3_g);
    assign b_out = glyph_on ? 8'hF2 : (p3_bar ? 8'h18 : p3_b);
    assign hs_out = p3_hs;
    assign vs_out = p3_vs;
    assign de_out = p3_de;

    always @(posedge clk_vid) begin
        if (reset_vid) begin
            frames <= 8'd0;
            len_q <= 6'd0;
            vs_d <= 1'b0;
            tog1 <= 1'b0;
            tog2 <= 1'b0;
            tog3 <= 1'b0;
            p1_de <= 1'b0;
            p2_de <= 1'b0;
            p3_de <= 1'b0;
            p1_bar <= 1'b0;
            p2_bar <= 1'b0;
            p3_bar <= 1'b0;
            p1_glyph <= 1'b0;
            p2_glyph <= 1'b0;
            p3_glyph <= 1'b0;
            scan_i <= 6'd0;
            scan_sub <= 4'd0;
        end else begin
            tog1 <= name_tog;
            tog2 <= tog1;
            tog3 <= tog2;
            vs_d <= vs_in;
            if (tog2 != tog3) begin
                frames <= 8'd180;
                len_q <= name_len;
                for (copy_i = 0; copy_i < 32; copy_i = copy_i + 1)
                    chars[copy_i] <= name_flat[copy_i * 8 +: 8];
            end else if (hold_in && (len_q != 0))
                frames <= 8'd180;
            else if (vs_in && !vs_d && frames != 0)
                frames <= frames - 8'd1;

            h1 <= h_pos;
            h2 <= h1;
            h3 <= h2;
            v1 <= v_pos;
            v2 <= v1;
            v3 <= v2;
            if (h2 == text_left) begin
                scan_sub <= 4'd0;
                scan_i <= 6'd0;
            end else if (scan_sub == 4'd11) begin
                scan_sub <= 4'd0;
                scan_i <= scan_i + 6'd1;
            end else
                scan_sub <= scan_sub + 4'd1;

            p1_r <= r_in;
            p1_g <= g_in;
            p1_b <= b_in;
            p1_hs <= hs_in;
            p1_vs <= vs_in;
            p1_de <= de_in;
            p1_bar <= in_bar;
            p1_glyph <= in_glyph;
            p1_gx <= scan_sub[3:1];
            p1_gy <= (v3 - text_y0) >> 1;
            p1_glyph_i <= scan_i[4:0];

            p2_r <= p1_r;
            p2_g <= p1_g;
            p2_b <= p1_b;
            p2_hs <= p1_hs;
            p2_vs <= p1_vs;
            p2_de <= p1_de;
            p2_bar <= p1_bar;
            p2_glyph <= p1_glyph;
            p2_gx <= p1_gx;
            font_addr <= {chars[p1_glyph_i], p1_gy};

            p3_r <= p2_r;
            p3_g <= p2_g;
            p3_b <= p2_b;
            p3_hs <= p2_hs;
            p3_vs <= p2_vs;
            p3_de <= p2_de;
            p3_bar <= p2_bar;
            p3_glyph <= p2_glyph;
            p3_gx <= p2_gx;
            font_row <= font[font_addr];
        end
    end
endmodule
