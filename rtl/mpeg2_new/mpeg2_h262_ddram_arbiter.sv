//============================================================================
// MiSTer Media Player - Phase 1S/1T DDR request arbiter
//
// kate - Phase 1R introduced concurrent decoder writes and presentation reads.
// Phase 1S repeats the two-bank ping-pong cycle, so the arbiter must also enforce
// frame-bank ownership: a new picture may not overwrite the bank still owned by
// the display reader.
//
// Reader requests have priority.  A bounded ordered descriptor queue retains
// response owner and burst length while DDR services accepted commands.  The
// display reader's accepted bank transfers presentation ownership; prediction
// reads never alter that ownership. Production defaults to depth four;
// simulation may override the shared descriptor-depth macro.
//
// kate - Phase 1T-f adds one decoder-side prediction reader. Display reads keep
// highest priority, prediction reads are next, and writes remain lowest priority.
// Response-ready is demultiplexed by the recorded read owner so the framebuffer
// cannot consume a prediction response and vice versa.
//
// kate - Phase 1T-o removes the temporary Phase 1T-m/n prediction-write command.
// The first reconstructed P block now uses the ordinary block writer, so this
// arbiter returns to three explicit clients: presentation read, prediction read,
// and reconstruction write. No prediction-side write encoding remains.
//
// RetroTV adds cabinet read owner 3. It never claims a frame bank. Display
// reads outrank it. Decoder clients do not. Cabinet reads continue through
// a per-file decoder reset so the bezel stays up between commercials.
//
// Commit 142 extends display ownership to the B scratch frame.  Entry 276 adds
// a third retained reference at region 100.  Writer exclusion therefore keeps
// all three region bits [18:16]; truncating the tag would alias reference bank
// two with bank zero and can permanently block the next reference write.
//============================================================================

`ifndef H262_PREDICTION_DESCRIPTOR_DEPTH
`define H262_PREDICTION_DESCRIPTOR_DEPTH 4
`endif

module mpeg2_h262_ddram_arbiter #(parameter ENABLE_QUIESCE=0, parameter ENABLE_DISPLAY_RELEASE=0)
(
    input  wire        clk,
    input  wire        reset,
    input wire quiesce,
    output wire idle,

    input  wire [7:0]  writer_burstcnt,
    input  wire [28:0] writer_addr,
    input  wire        writer_rd,
    input  wire [63:0] writer_din,
    input  wire [7:0]  writer_be,
    input  wire        writer_we,
    output wire        writer_busy,

    input  wire [7:0]  reader_burstcnt,
    input  wire [28:0] reader_addr,
    input  wire        reader_rd,
    output wire        reader_busy,
    output wire        reader_dout_ready,

    input  wire [7:0]  prediction_burstcnt,
    input  wire [28:0] prediction_addr,
    input  wire        prediction_rd,
    output wire        prediction_busy,
    output wire        prediction_dout_ready,

    // Low-priority compressed stream reservoir; never claims a frame bank.
    input wire [28:0] stream_addr,
    input wire [63:0] stream_din,
    input wire stream_rd, stream_we,
    output wire stream_busy, stream_dout_ready,

    // Lowest priority. Cabinet pixels live above the frame banks.
    input  wire [7:0]  cabinet_burstcnt,
    input  wire [28:0] cabinet_addr,
    input  wire [63:0] cabinet_din,
    input  wire        cabinet_rd,
    input  wire        cabinet_we,
    // High while the raw picture is still being stored. Those writes must
    // land before a movie mount, so they are not held behind decoder quiesce.
    input  wire        cabinet_preload,
    output wire        cabinet_busy,
    output wire        cabinet_dout_ready,

    input  wire        ddram_busy,
    input  wire        ddram_dout_ready,
    output wire [7:0]  ddram_burstcnt,
    output wire [28:0] ddram_addr,
    output wire        ddram_rd,
    output wire [63:0] ddram_din,
    output wire [7:0]  ddram_be,
    output wire        ddram_we,

    // Assert only while display reads are stopped (seeking, not ordinary pause).
    input wire release_display_bank
);

localparam integer DESCRIPTOR_DEPTH=`H262_PREDICTION_DESCRIPTOR_DEPTH;
localparam integer DESCRIPTOR_POINTER_WIDTH=
    (DESCRIPTOR_DEPTH<=2)?1:$clog2(DESCRIPTOR_DEPTH);
localparam integer DESCRIPTOR_COUNT_WIDTH=$clog2(DESCRIPTOR_DEPTH+1);

reg [DESCRIPTOR_COUNT_WIDTH-1:0] read_descriptor_count;
reg [DESCRIPTOR_COUNT_WIDTH-1:0] mpeg_descriptor_count;
reg mpeg_write_active;
reg [DESCRIPTOR_POINTER_WIDTH-1:0]
    read_descriptor_head,read_descriptor_tail;
reg [2:0] read_descriptor_owner [0:DESCRIPTOR_DEPTH-1];
reg [7:0] read_descriptor_words [0:DESCRIPTOR_DEPTH-1];
reg       reader_bank_valid;
reg [2:0] reader_frame_region;

wire read_outstanding=(read_descriptor_count!=0);
wire [2:0] read_owner=read_outstanding?
    read_descriptor_owner[read_descriptor_head]:3'd0;
wire [7:0] read_words_remaining=read_outstanding?
    read_descriptor_words[read_descriptor_head]:8'd0;
wire response_existing=ddram_dout_ready&&read_outstanding;
wire response_finishes=response_existing&&(read_words_remaining<=8'd1);
wire read_descriptor_room=(read_descriptor_count<DESCRIPTOR_DEPTH)||
    response_finishes;

wire writer_targets_reader_region =
    reader_bank_valid && (writer_addr[18:16] == reader_frame_region);

wire stopping=ENABLE_QUIESCE ? quiesce : 1'b0;

wire grant_reader =
    !stopping && read_descriptor_room && reader_rd;

// Steady-state cabinet reads sit above the decoder and below the display.
// The display still wins on reader_rd, and it accepts on reader_busy, so a
// cabinet request must not be granted on a cycle the display also requests.
// During decoder quiesce the display is stopped. Cabinet reads continue so
// the television does not go black while the next commercial is opened.
// Decoder clients accept on their own busy flags. Those flags include
// cabinet_rd so a stolen cycle cannot look like their request was accepted.
wire grant_cabinet_read = read_descriptor_room && cabinet_rd &&
    (stopping || !reader_rd);

wire grant_prediction =
    !stopping && read_descriptor_room && !reader_rd && !cabinet_rd &&
    prediction_rd;

wire grant_writer =
    !stopping && !read_outstanding && !reader_rd && !cabinet_rd &&
    !prediction_rd && writer_we && !writer_targets_reader_region;

wire grant_stream_read = !stopping && read_descriptor_room && !reader_rd &&
    !cabinet_rd && !prediction_rd && !grant_writer && stream_rd;
wire grant_stream_write = !stopping && !read_outstanding && !reader_rd &&
    !cabinet_rd && !prediction_rd && !grant_writer && !stream_rd && stream_we;
assign stream_busy = stopping || ddram_busy || reader_rd || cabinet_rd ||
    prediction_rd || grant_writer ||
    (stream_rd ? !read_descriptor_room : read_outstanding);

// The one-time picture store stays behind every other client. It ignores
// decoder quiesce: Main sends the file before a movie is mounted, and a
// quiesce wait there stalls ioctl_wait.
wire grant_cabinet_write = !read_outstanding && !cabinet_rd && cabinet_we &&
    !reader_rd && !prediction_rd && !writer_we && !stream_rd && !stream_we &&
    (cabinet_preload || !stopping);
// Reads do not wait on the decoder. Writes still do, and the store FSM
// advances on !cabinet_busy, so the write term has to match that grant.
wire cabinet_read_busy = ddram_busy || !read_descriptor_room ||
    (reader_rd && !stopping);
wire cabinet_write_busy = ddram_busy || read_outstanding || reader_rd ||
    prediction_rd || writer_we || stream_rd || stream_we ||
    (cabinet_preload ? 1'b0 : stopping);
assign cabinet_busy = cabinet_rd ? cabinet_read_busy : cabinet_write_busy;

// Busy reports capacity/priority independently of the corresponding request.
// This is a ready/valid boundary: acceptance below remains request-qualified,
// but no client valid may feed back combinationally into its own readiness.
assign reader_busy = stopping || !read_descriptor_room||ddram_busy;

assign prediction_busy =
    stopping||!read_descriptor_room||reader_rd||cabinet_rd||ddram_busy;

assign writer_busy = stopping||read_outstanding||reader_rd||cabinet_rd||
    prediction_rd||writer_targets_reader_region||ddram_busy;

assign ddram_burstcnt =
    grant_reader ? reader_burstcnt :
    grant_prediction ? prediction_burstcnt :
    grant_writer ? writer_burstcnt :
    (grant_stream_read || grant_stream_write) ? 8'd1 :
    (grant_cabinet_read || grant_cabinet_write) ? cabinet_burstcnt : 8'd0;

assign ddram_addr =
    grant_reader ? reader_addr :
    grant_prediction ? prediction_addr :
    grant_writer ? writer_addr :
    (grant_stream_read || grant_stream_write) ? stream_addr :
    (grant_cabinet_read || grant_cabinet_write) ? cabinet_addr : 29'd0;

assign ddram_rd =
    grant_reader ? 1'b1 :
    grant_prediction ? 1'b1 :
    grant_stream_read ? 1'b1 : grant_cabinet_read;

assign ddram_din =
    grant_writer ? writer_din :
    grant_cabinet_write ? cabinet_din : stream_din;

assign ddram_be =
    grant_writer ? writer_be : 8'hFF;

assign ddram_we =
    grant_writer ? writer_we :
    grant_cabinet_write ? 1'b1 : grant_stream_write;

wire reader_accept=grant_reader&&!ddram_busy;
wire prediction_accept=grant_prediction&&!ddram_busy;
wire stream_accept=grant_stream_read&&!ddram_busy;
wire cabinet_accept=grant_cabinet_read&&!ddram_busy;
wire read_accept=reader_accept||prediction_accept||stream_accept||cabinet_accept;
wire [2:0] accepted_owner=reader_accept?3'd0:prediction_accept?3'd1:stream_accept?3'd2:3'd3;
wire [7:0] accepted_words=reader_accept?reader_burstcnt:
    prediction_accept?prediction_burstcnt:
    cabinet_accept?cabinet_burstcnt:8'd1;
wire direct_response=ddram_dout_ready&&!read_outstanding&&read_accept;
wire direct_response_finishes=direct_response&&(accepted_words<=8'd1);
wire descriptor_push=read_accept&&!direct_response_finishes;
wire descriptor_pop=response_finishes;
wire [7:0] pushed_words=direct_response?
    (accepted_words-8'd1):accepted_words;
wire [DESCRIPTOR_POINTER_WIDTH-1:0] read_descriptor_head_next=
    (read_descriptor_head==(DESCRIPTOR_DEPTH-1))?
    {DESCRIPTOR_POINTER_WIDTH{1'b0}}:read_descriptor_head+1'b1;
wire [DESCRIPTOR_POINTER_WIDTH-1:0] read_descriptor_tail_next=
    (read_descriptor_tail==(DESCRIPTOR_DEPTH-1))?
    {DESCRIPTOR_POINTER_WIDTH{1'b0}}:read_descriptor_tail+1'b1;

assign reader_dout_ready =
    (response_existing&&(read_owner==0))||
    (direct_response&&reader_accept);

assign prediction_dout_ready =
    (response_existing&&(read_owner==1))||
    (direct_response&&prediction_accept);

assign stream_dout_ready =
    (response_existing&&(read_owner==2))||(direct_response&&stream_accept);

assign cabinet_dout_ready =
    (response_existing&&(read_owner==3))||(direct_response&&cabinet_accept);

// The session drain waits for decoder DDR only. Cabinet reads stay active
// between commercials, and that traffic must not hold decoder_reset off.
wire push_mpeg = descriptor_push && (accepted_owner != 3'd3);
wire pop_mpeg = descriptor_pop && (read_owner != 3'd3);
wire mpeg_write_accept = (grant_writer || grant_stream_write) && !ddram_busy;
assign idle = (mpeg_descriptor_count == 0) && !mpeg_write_active;

integer descriptor_index;
always @(posedge clk) begin
    if (reset) begin
        read_descriptor_count <= {DESCRIPTOR_COUNT_WIDTH{1'b0}};
        mpeg_descriptor_count <= {DESCRIPTOR_COUNT_WIDTH{1'b0}};
        mpeg_write_active     <= 1'b0;
        read_descriptor_head  <= {DESCRIPTOR_POINTER_WIDTH{1'b0}};
        read_descriptor_tail  <= {DESCRIPTOR_POINTER_WIDTH{1'b0}};
        for(descriptor_index=0;descriptor_index<DESCRIPTOR_DEPTH;
            descriptor_index=descriptor_index+1)begin
            read_descriptor_owner[descriptor_index] <= 3'd0;
            read_descriptor_words[descriptor_index] <= 8'd0;
        end
        reader_bank_valid     <= 1'b0;
        reader_frame_region   <= 3'b000;
    end
    else begin
        if(descriptor_push)begin
            read_descriptor_owner[read_descriptor_tail]<=
                accepted_owner;
            read_descriptor_words[read_descriptor_tail]<=pushed_words;
            read_descriptor_tail<=read_descriptor_tail_next;
        end
        if(descriptor_pop)
            read_descriptor_head<=read_descriptor_head_next;
        else if(response_existing)
            read_descriptor_words[read_descriptor_head]<=
                read_words_remaining-8'd1;

        case({descriptor_push,descriptor_pop})
            2'b10:read_descriptor_count<=read_descriptor_count+1'b1;
            2'b01:read_descriptor_count<=read_descriptor_count-1'b1;
            default:read_descriptor_count<=read_descriptor_count;
        endcase

        case({push_mpeg,pop_mpeg})
            2'b10:mpeg_descriptor_count<=mpeg_descriptor_count+1'b1;
            2'b01:mpeg_descriptor_count<=mpeg_descriptor_count-1'b1;
            default:mpeg_descriptor_count<=mpeg_descriptor_count;
        endcase

        if(mpeg_write_accept)
            mpeg_write_active<=1'b1;
        else if(mpeg_write_active && !ddram_busy)
            mpeg_write_active<=1'b0;

        if(reader_accept)begin
            reader_bank_valid<=1'b1;
            reader_frame_region<=reader_addr[18:16];
        end else if(((ENABLE_DISPLAY_RELEASE && release_display_bank) || quiesce) &&
                    (mpeg_descriptor_count==0) && !mpeg_write_active && !push_mpeg)begin
            // Keep descriptor ownership intact until every decoder response
            // has retired. Cabinet traffic does not own a frame bank. A
            // per-file quiesce releases the old picture so the next
            // commercial can write any bank without resetting this arbiter.
            reader_bank_valid<=1'b0;
        end
    end
end

wire unused_writer_rd = writer_rd;

endmodule
