//============================================================================
//
//  This program is free software; you can redistribute it and/or modify it
//  under the terms of the GNU General Public License as published by the Free
//  Software Foundation; either version 2 of the License, or (at your option)
//  any later version.
//
//  This program is distributed in the hope that it will be useful, but WITHOUT
//  ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
//  FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
//  more details.
//
//  You should have received a copy of the GNU General Public License along
//  with this program; if not, write to the Free Software Foundation, Inc.,
//  51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
//
//============================================================================

module emu
(
	`include "sys/emu_ports.vh"
);

///////// Default values for ports not used in this core /////////

assign ADC_BUS  = 'Z;
assign USER_OUT = '1;
// Declared here, before the ports that use them. The Escape sender and the
// M-key toggle live with the other keyboard logic further down the module.
reg menu_uart_tx = 1'b1;
reg audio_mute = 1'b0;
// Held from a channel key until the new clip is selected. Blacks the glass.
reg channel_hold = 1'b0;
// Held after that selection until a join seek lands. Blacks the glass and
// mutes, but does not reset the reader, so the seek can run underneath.
reg join_cover = 1'b0;
// One sysclk pulse. ORed into the playlist open so the mounted tar is reread.
reg channel_rescan = 1'b0;
reg music_mode = 1'b0;
reg music_art_valid = 1'b0;
reg music_art_bank = 1'b0;
reg news_art = 1'b0;
assign {UART_RTS, UART_DTR} = 2'b0;
assign UART_TXD = menu_uart_tx;
assign {SD_SCK, SD_MOSI, SD_CS} = 'Z;
assign {SDRAM_DQ, SDRAM_A, SDRAM_BA, SDRAM_CLK, SDRAM_CKE,
        SDRAM_DQML, SDRAM_DQMH, SDRAM_nWE, SDRAM_nCAS,
        SDRAM_nRAS, SDRAM_nCS} = 'Z;

assign VGA_SL = 0;
assign VGA_F1 = 0;
assign VGA_SCALER  = 0;
assign VGA_DISABLE = 0;
assign HDMI_FREEZE = 0;
assign HDMI_BLACKOUT = 0;
assign HDMI_BOB_DEINT = 0;

// Movie PCM is signed stereo, scheduled in the CLK_AUDIO domain by the MP2
// sink and passed through the normal MiSTer audio output/filter path.
wire [15:0] audio_pcm_output_l;
wire [15:0] audio_pcm_output_r;
assign AUDIO_S = 1'b1;
assign AUDIO_L = (audio_mute || channel_hold || join_cover || music_mode) ? 16'd0 : audio_pcm_output_l;
assign AUDIO_R = (audio_mute || channel_hold || join_cover || music_mode) ? 16'd0 : audio_pcm_output_r;
assign AUDIO_MIX = 2'd0;

assign BUTTONS = 0;

//////////////////////////////////////////////////////////////////

`include "build_id.v"
// Status bits 3:1 remain reserved after removal of Audio test. Bit 121 is
// reserved after moving the aspect ratio switch to the A key.
localparam CONF_STR = {
	"RetroTV;;",
	"S0,MPGTAR,Load movie or playlist;",
`include "Raster_subtitle_menu.svh"
	"-;",
	"-;",
	"O[6],Refresh rate,59.94 Hz,50 Hz;",
	"O[5:4],Color matrix,Auto,BT.601,BT.709;",

	"-;",
	"T[0],Reset;",
	"R[0],Reset and close OSD;",
	"v,2;",
	"V,v",`BUILD_DATE
};

wire forced_scandoubler;
wire   [1:0] buttons;
wire [127:0] status;
wire  [10:0] ps2_key;

