// Startup title and shortcuts use the existing 5x7 overlay glyphs, doubled.
// Constant text and glyphs require no additional FPGA block RAM.
module retrotv_splash (
    input  wire        clk_vid,
    input  wire        reset_vid,
    input  wire        active,
    input  wire        xbr,
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
    localparam [11:0] TEXT_W = 12'd408;
    wire [11:0] text_left = xbr ? 12'd308 : 12'd156;
    wire [11:0] text_top = xbr ? 12'd156 : 12'd56;

    function [271:0] keyboard_line;
        input [3:0] number;
        begin
            case (number)
                4'd0: keyboard_line = "RETROTV LOADING...                ";
                4'd2: keyboard_line = "LEFT / RIGHT     CHANNEL          ";
                4'd3: keyboard_line = "UP / DOWN        TV CABINET       ";
                4'd4: keyboard_line = "SHIFT + UP/DOWN  BACKGROUND       ";
                4'd5: keyboard_line = "F4               DEFAULT TV       ";
                4'd6: keyboard_line = "N / P            NEXT / PREV CLIP ";
                4'd7: keyboard_line = "SPACE / M        PAUSE / MUTE     ";
                4'd8: keyboard_line = "PGUP / PGDN      IMAGE OR SCROLL  ";
                4'd9: keyboard_line = "PRINT SCREEN     SAVE SCREENSHOT  ";
                4'd10: keyboard_line = "D (TWICE)        DELETE IN CH 50  ";
                4'd11: keyboard_line = "ESC              MISTER MENU      ";
                default: keyboard_line = 272'd0;
            endcase
        end
    endfunction

    // Row 0 is bits[34:30]. The left pixel is the high bit of each row.
    function [4:0] glyph_row;
        input [7:0] ascii;
        input [2:0] row;
        reg [34:0] bits;
        begin
            case (ascii)
                "(": bits = 35'b00010001000100001000010000010000010;
                ")": bits = 35'b01000001000001000010000100010001000;
                "+": bits = 35'b00000001000010011111001000010000000;
                ".": bits = 35'b00000000000000000000000000000000100;
                "/": bits = 35'b00001000010001000100010001000010000;
                "0": bits = 35'b01110100011001110101110011000101110;
                "4": bits = 35'b00010001100101010010111110001000010;
                "5": bits = 35'b11111100001000011110000010000111110;
                "A": bits = 35'b01110100011000111111100011000110001;
                "B": bits = 35'b11110100011000111110100011000111110;
                "C": bits = 35'b01110100011000010000100001000101110;
                "D": bits = 35'b11110100011000110001100011000111110;
                "E": bits = 35'b11111100001000011110100001000011111;
                "F": bits = 35'b11111100001000011110100001000010000;
                "G": bits = 35'b01110100011000010111100011000101111;
                "H": bits = 35'b10001100011000111111100011000110001;
                "I": bits = 35'b11111001000010000100001000010011111;
                "K": bits = 35'b10001100101010011000101001001010001;
                "L": bits = 35'b10000100001000010000100001000011111;
                "M": bits = 35'b10001110111010110101100011000110001;
                "N": bits = 35'b10001110011010110011100011000110001;
                "O": bits = 35'b01110100011000110001100011000101110;
                "P": bits = 35'b11110100011000111110100001000010000;
                "R": bits = 35'b11110100011000111110101001001010001;
                "S": bits = 35'b01111100001000001110000010000111110;
                "T": bits = 35'b11111001000010000100001000010000100;
                "U": bits = 35'b10001100011000110001100011000101110;
                "V": bits = 35'b10001100011000110001100010101000100;
                "W": bits = 35'b10001100011000110101101011010101010;
                "X": bits = 35'b10001100010101000100010101000110001;
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
    reg [5:0]  scan_i = 6'd0;
    reg [3:0]  scan_sub = 4'd0;

    wire [11:0] gy_pix = v3 - text_top;
    wire in_glyph = active && de_in && gy_pix < 12'd384 &&
                    (h3 >= text_left) && (h3 < text_left + TEXT_W) &&
                    (gy_pix[4:0] < 5'd14) && (scan_sub < 4'd10);
    reg [271:0] line_ascii = 272'd0;
    wire [7:0] glyph_ascii = line_ascii[271 - {scan_i,3'b000} -: 8];

    reg        p1_cover = 1'b0, p1_glyph = 1'b0;
    reg [2:0]  p1_gx = 3'd0, p1_gy = 3'd0;
    reg [7:0]  p1_char = 8'd0;
    reg        p1_title = 1'b0, p2_title = 1'b0, p3_title = 1'b0;
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

    assign r_out = ink ? (p3_title ? 8'hFF : 8'hF2) : (paper ? 8'h00 : p3_r);
    assign g_out = ink ? (p3_title ? 8'hB8 : 8'hF2) : (paper ? 8'h00 : p3_g);
    assign b_out = ink ? (p3_title ? 8'h58 : 8'hF2) : (paper ? 8'h00 : p3_b);
    assign hs_out = p3_hs;
    assign vs_out = p3_vs;
    assign de_out = p3_de;

    always @(posedge clk_vid) begin
        if (reset_vid) begin
            scan_i <= 6'd0;
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
            line_ascii <= keyboard_line(gy_pix[8:5]);
            if (h2 == text_left) begin
                scan_sub <= 4'd0;
                scan_i <= 6'd0;
            end else if (scan_sub == 4'd11) begin
                scan_sub <= 4'd0;
                scan_i <= scan_i + 6'd1;
            end else
                scan_sub <= scan_sub + 4'd1;

            p1_cover <= active;
            p1_glyph <= in_glyph;
            p1_gx <= scan_sub[3:1];
            p1_gy <= gy_pix[3:1];
            p1_char <= glyph_ascii;
            p1_title <= gy_pix[8:5] == 4'd0;
            p1_r <= r_in;
            p1_g <= g_in;
            p1_b <= b_in;
            p1_hs <= hs_in;
            p1_vs <= vs_in;
            p1_de <= de_in;

            p2_cover <= p1_cover;
            p2_glyph <= p1_glyph;
            p2_gx <= p1_gx;
            p2_row <= glyph_row(p1_char, p1_gy);
            p2_title <= p1_title;
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
            p3_title <= p2_title;
            p3_r <= p2_r;
            p3_g <= p2_g;
            p3_b <= p2_b;
            p3_hs <= p2_hs;
            p3_vs <= p2_vs;
            p3_de <= p2_de;
        end
    end
endmodule
