// Startup title. The core's first frames are black until the fifth cabinet
// image has been stored. This paints "Retro TV Loading..." on that black
// and then passes the picture through unchanged.
// Glyphs are the same 5x7 overlay font, doubled, and the string is fixed
// so the video clock never divides.
module retrotv_splash (
    input  wire        clk_vid,
    input  wire        reset_vid,
    input  wire        active,
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
    localparam [11:0] TEXT_LEFT = 12'd247;
    localparam [11:0] TEXT_W    = 12'd226;
    localparam [11:0] TEXT_Y0   = 12'd233;
    localparam [4:0]  TEXT_LEN  = 5'd19;

    // Row 0 is bits[34:30]. The left pixel is the high bit of each row.
    function [4:0] glyph_row;
        input [4:0] idx;
        input [2:0] row;
        reg [34:0] bits;
        begin
            case (idx)
                5'd0:  bits = 35'b11110100011000111110101001001010001;
                5'd1:  bits = 35'b00000000000111010001111111000001110;
                5'd2:  bits = 35'b01000010001111001000010000100100110;
                5'd3:  bits = 35'b00000000001011011001100001000010000;
                5'd4:  bits = 35'b00000000000111010001100011000101110;
                5'd5:  bits = 35'b00000000000000000000000000000000000;
                5'd6:  bits = 35'b11111001000010000100001000010000100;
                5'd7:  bits = 35'b10001100011000110001100010101000100;
                5'd8:  bits = 35'b00000000000000000000000000000000000;
                5'd9:  bits = 35'b10000100001000010000100001000011111;
                5'd10: bits = 35'b00000000000111010001100011000101110;
                5'd11: bits = 35'b00000000000111000001011111000101111;
                5'd12: bits = 35'b00001000010111110001100011000101111;
                5'd13: bits = 35'b00100000000110000100001000010001110;
                5'd14: bits = 35'b00000000001111010001100011000110001;
                5'd15: bits = 35'b00000000000111110001011110000101110;
                5'd16: bits = 35'b00000000000000000000000000000000100;
                5'd17: bits = 35'b00000000000000000000000000000000100;
                5'd18: bits = 35'b00000000000000000000000000000000100;
                default: bits = 35'd0;
            endcase
            case (row)
                3'd0: glyph_row = bits[34:30];
                3'd1: glyph_row = bits[29:25];
                3'd2: glyph_row = bits[24:20];
                3'd3: glyph_row = bits[19:15];
                3'd4: glyph_row = bits[14:10];
                3'd5: glyph_row = bits[9:5];
                3'd6: glyph_row = bits[4:0];
                default: glyph_row = 5'd0;
            endcase
        end
    endfunction

    reg [11:0] h1 = 12'd0, h2 = 12'd0, h3 = 12'd0;
    reg [11:0] v1 = 12'd0, v2 = 12'd0, v3 = 12'd0;
    reg [4:0]  scan_i = 5'd0;
    reg [3:0]  scan_sub = 4'd0;

    wire [11:0] gy_pix = (v3 >= TEXT_Y0) ? (v3 - TEXT_Y0) : 12'd0;
    wire in_glyph = active && de_in &&
                    (v3 >= TEXT_Y0) && (v3 < TEXT_Y0 + 12'd14) &&
                    (h3 >= TEXT_LEFT) && (h3 < TEXT_LEFT + TEXT_W) &&
                    (scan_sub < 4'd10) && (scan_i < TEXT_LEN);

    reg        p1_cover = 1'b0, p1_glyph = 1'b0;
    reg [2:0]  p1_gx = 3'd0, p1_gy = 3'd0;
    reg [4:0]  p1_idx = 5'd0;
    reg [7:0]  p1_r = 8'd0, p1_g = 8'd0, p1_b = 8'd0;
    reg        p1_hs = 1'b1, p1_vs = 1'b1, p1_de = 1'b0;

    reg        p2_cover = 1'b0, p2_glyph = 1'b0;
    reg [2:0]  p2_gx = 3'd0;
    reg [4:0]  p2_row = 5'd0;
    reg [7:0]  p2_r = 8'd0, p2_g = 8'd0, p2_b = 8'd0;
    reg        p2_hs = 1'b1, p2_vs = 1'b1, p2_de = 1'b0;

    reg        p3_cover = 1'b0, p3_glyph = 1'b0;
    reg [2:0]  p3_gx = 3'd0;
    reg [4:0]  p3_row = 5'd0;
    reg [7:0]  p3_r = 8'd0, p3_g = 8'd0, p3_b = 8'd0;
    reg        p3_hs = 1'b1, p3_vs = 1'b1, p3_de = 1'b0;

    reg glyph_bit = 1'b0;
    always @* begin
        glyph_bit = 1'b0;
        if (p3_gx == 3'd0) glyph_bit = p3_row[4];
        else if (p3_gx == 3'd1) glyph_bit = p3_row[3];
        else if (p3_gx == 3'd2) glyph_bit = p3_row[2];
        else if (p3_gx == 3'd3) glyph_bit = p3_row[1];
        else if (p3_gx == 3'd4) glyph_bit = p3_row[0];
    end
    wire ink = p3_cover && p3_de && p3_glyph && glyph_bit;
    wire paper = p3_cover && p3_de;

    assign r_out = ink ? 8'hF2 : (paper ? 8'h00 : p3_r);
    assign g_out = ink ? 8'hF2 : (paper ? 8'h00 : p3_g);
    assign b_out = ink ? 8'hF2 : (paper ? 8'h00 : p3_b);
    assign hs_out = p3_hs;
    assign vs_out = p3_vs;
    assign de_out = p3_de;

    always @(posedge clk_vid) begin
        if (reset_vid) begin
            scan_i <= 5'd0;
            scan_sub <= 4'd0;
            p1_de <= 1'b0;
            p2_de <= 1'b0;
            p3_de <= 1'b0;
            p1_cover <= 1'b0;
            p2_cover <= 1'b0;
            p3_cover <= 1'b0;
            p1_glyph <= 1'b0;
            p2_glyph <= 1'b0;
            p3_glyph <= 1'b0;
        end else begin
            h1 <= h_pos;
            h2 <= h1;
            h3 <= h2;
            v1 <= v_pos;
            v2 <= v1;
            v3 <= v2;
            if (h2 == TEXT_LEFT) begin
                scan_sub <= 4'd0;
                scan_i <= 5'd0;
            end else if (scan_sub == 4'd11) begin
                scan_sub <= 4'd0;
                scan_i <= scan_i + 5'd1;
            end else
                scan_sub <= scan_sub + 4'd1;

            p1_cover <= active;
            p1_glyph <= in_glyph;
            p1_gx <= scan_sub[3:1];
            p1_gy <= gy_pix[3:1];
            p1_idx <= scan_i;
            p1_r <= r_in;
            p1_g <= g_in;
            p1_b <= b_in;
            p1_hs <= hs_in;
            p1_vs <= vs_in;
            p1_de <= de_in;

            p2_cover <= p1_cover;
            p2_glyph <= p1_glyph;
            p2_gx <= p1_gx;
            p2_row <= glyph_row(p1_idx, p1_gy);
            p2_r <= p1_r;
            p2_g <= p1_g;
            p2_b <= p1_b;
            p2_hs <= p1_hs;
            p2_vs <= p1_vs;
            p2_de <= p1_de;

            p3_cover <= p2_cover;
            p3_glyph <= p2_glyph;
            p3_gx <= p2_gx;
            p3_row <= p2_row;
            p3_r <= p2_r;
            p3_g <= p2_g;
            p3_b <= p2_b;
            p3_hs <= p2_hs;
            p3_vs <= p2_vs;
            p3_de <= p2_de;
        end
    end
endmodule
