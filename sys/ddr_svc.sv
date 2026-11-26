//
// Copyright (c) 2020 Alexey Melnikov
//
//
// This source file is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published
// by the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version. 
//
// This source file is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of 
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the 
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License 
// along with this program.  If not, see <http://www.gnu.org/licenses/>.
//
// ------------------------------------------
//

// 16-bit version

module ddr_svc
(
	input         clk,

	input         ram_waitrequest,
	output  [7:0] ram_burstcnt,
	output [28:0] ram_addr,
	input  [63:0] ram_readdata,
	input         ram_read_ready,
	output reg    ram_read,
	output [63:0] ram_writedata,
	output  [7:0] ram_byteenable,
	output reg    ram_write,

	output reg [7:0] ram_bcnt,

	input  [31:3] ch0_addr,
	input   [7:0] ch0_burst,
	output [63:0] ch0_data,
	input         ch0_req,
	output        ch0_ready,
	
	input  [31:3] ch1_addr,
	input   [7:0] ch1_burst,
	output [63:0] ch1_data,
	input         ch1_req,
	output        ch1_ready,

	input  [31:3] ch2_addr,
	input   [7:0] ch2_burst,
	output [63:0] ch2_data,
	input         ch2_req,
	output        ch2_ready
);

assign ram_burstcnt   = ram_burst;
assign ram_byteenable = 8'hFF;
assign ram_addr       = ram_address;
assign ram_writedata  = 0;

assign ch0_data  = ram_q[0];
assign ch1_data  = ram_q[1];
assign ch2_data  = ram_q[2];
assign ch0_ready = ready[0];
assign ch1_ready = ready[1];
assign ch2_ready = ready[2];

reg  [7:0] ram_burst;
reg [63:0] ram_q[3];
reg [31:3] ram_address;
reg  [2:0] ack = 0;
reg  [2:0] ready = 0;
reg        state = 0;
reg  [1:0] ch = 0;

wire [2:0] pending = {ch2_req, ch1_req, ch0_req} ^ ack;
// Audio and palette transfers are serviced before the bounded scenery bursts.
wire [1:0] next_channel = pending[0] ? 2'd0 : pending[1] ? 2'd1 : 2'd2;

always @(posedge clk) begin
	ready <= 0;
	if (!ram_waitrequest) begin
		ram_read <= 0;
		ram_write <= 0;
		if (!state && pending != 0) begin
			ack[next_channel] <= ~ack[next_channel];
			case (next_channel)
				2'd0: {ram_address, ram_burst} <= {ch0_addr, ch0_burst};
				2'd1: {ram_address, ram_burst} <= {ch1_addr, ch1_burst};
				default: {ram_address, ram_burst} <= {ch2_addr, ch2_burst};
			endcase
			ch <= next_channel;
			ram_bcnt <= 8'hFF;
			ram_read <= 1;
			state <= 1;
		end
	end
	// waitrequest throttles commands, not data returned for a prior read.
	if (state && ram_read_ready) begin
		ram_bcnt <= ram_bcnt + 1'd1;
		ram_q[ch] <= ram_readdata;
		ready[ch] <= 1;
		if ((ram_bcnt + 8'd2) == ram_burst)
			state <= 0;
	end
end

endmodule
