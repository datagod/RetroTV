// Playback scene state. The timeline group stays off.
// Session changes invalidate all future cue-provider state. Seeking invalidates
// cue selection; a future provider must reselect at the actual landing position.
module media_ui_state(
 input wire clk,reset,new_file,loaded,seeking,
 input wire [34:0] elapsed_q,target_q,duration_q,
 input wire duration_valid,
 output wire duration_known,
 output wire [90:0] scene_state
);
reg [15:0] session=0;
reg seeking_d=0;
reg [34:0] target_d=0;
reg invalid_duration=0;
wire known=duration_valid && !invalid_duration;
assign duration_known=known;
wire [34:0] display_elapsed=seeking?target_q:elapsed_q;
// Bits 72:71 are reserved after removal of playback-status labels.
// Bit 73 is the timeline group. It stays off: pause, seek, and a channel
// join must not draw the bar or its clocks.
assign scene_state={session,loaded,1'b0,2'b00,known,
 duration_q,display_elapsed};
always @(posedge clk) begin
 seeking_d<=seeking;target_d<=target_q;
 if(reset) begin session<=0;invalid_duration<=0;end
 else if(new_file) begin session<=session+1'b1;invalid_duration<=0;end
 else begin
  if(seeking && (!seeking_d || target_q!=target_d)) session<=session+1'b1;
  // A presented timestamp beyond the qualified endpoint contradicts the
  // continuous-timeline probe. Seek previews are not evidence of discontinuity.
  if(loaded && !seeking && duration_valid && elapsed_q>duration_q+35'd360000)
   invalid_duration<=1;
 end
end
endmodule
