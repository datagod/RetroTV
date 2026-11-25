# MiSTer-Raster architecture

Raster keeps MPEG video, MP2 movie audio, subtitles and transport controls.
The current source removes the former standalone FLAC/visualizer path.
Resource, timing and hardware-acceptance records for every build are in
[QUALIFICATION.md](QUALIFICATION.md); new claims require a new fitted build.

## Integration

`sys_top` instantiates `emu`, the MiSTer scaler/video processing, the player
overlay, and the platform OSD. `Raster.sv` assembles the emu body from
ports, file, session, clocks, container, decoder, prediction, framebuffer and
output includes. `Raster_top_file.svh` holds the shared file/session
signals that previously lived in a music-named include.

The core exposes ordinary video/audio signals plus `PLAYER_UI_CLOCK`,
`PLAYER_UI_STATE`, and `PLAYER_SUBTITLE_COMMAND/ACK`. The HDMI path feeds
scaled/processed movie pixels directly to `media_player_overlay`, then OSD.
RGB, sync, DE and layout DE enter the overlay at the same pipeline stage.
`media_aspect_toggle` turns the A key into the 4:3/16:9 choice. Core reset
selects 16:9. A two-flop synchronizer carries that level to `VIDEO_ARX/ARY`.

## MPEG and MP2

The mounted-file reader fills the compressed stream FIFO. MPEG ingress
separates Program Stream video and MP2 audio. Video bytes and PTS/EOF metadata
use a DDR reservoir ahead of the H.262 parsing, inverse quantization, shared
IDCT and I/P/B reconstruction logic. Frame storage and presentation scheduling
retain reference-bank ownership and B-picture display-order handling.

MP2 decoding and synthesis use on-chip storage. `Raster_av.svh` connects
the audio FIFO, decoder, PCM clock-domain FIFO and timestamped PCM sink.
The movie audio clock, origin timestamps and seek coordination are retained.
EOF waits for both final video presentation and the final audio sample.

`sys/audio_out.sv` retains platform volume/filtering and serialization. Its
I2S, S/PDIF and DAC outputs feed the platform output connections directly;
HDMI MCLK uses the existing movie audio PLL. HPS owns HDMI I2C through the
open-drain pad drive/readback path. The CD PLL and music handoff controller
have been removed.

## DDR and session ownership

The movie DDR arbiter retains picture-store, scanout, prediction and compressed
stream clients. Its output now connects directly to the core DDR interface,
without the FLAC owner mux. Quiesce, physical DDR busy, response-valid and idle
still govern draining before decoder reset/restart.

`media_session_control` retains reader/DDR draining and generation changes.
`media_duration_probe` owns the reader during MPEG head/tail preflight;
`media_seek_search` and `media_seek_point` retain sequence/GOP-based seeking.
Keyboard intent and presentation time remain separate. The qualified duration
flag still rejects duration claims contradicted by actual presentation time.

## Subtitles and UI

Movie and linked subtitle members share mounted slot 0; manual subtitles use
slot 1. `media_sd_owner` serializes both logical readers and latches their
physical slot until each response drains. SRT parsing, timing adjustment and delivery
remain separate from decoding. The transport/subtitle renderer retains the
91-bit player state, loaded flag and session/seek epoch so stale scenes cannot
survive a file change or seek. Overlay activity lasts three seconds and remains
visible during seeking. Track/album UI branches have been removed.

## RetroTV video channels

The RetroTV launcher loads the cabinet artwork and starts without a movie.
The Linux controller lists the original MPG files in each channel folder in
case-insensitive filename order. It probes MPEG timestamps and stores only
file signatures and durations in each folder's small `.retrotv-times.json`.
**Analyze RetroTV Channels** refreshes these indexes and music manifests.

The broadcast position is the elapsed time since the shared boot epoch modulo
the total duration of a channel. Walk the clip durations from the first file
to find the clip and offset. Tuning mounts that file read-only in slot 0 and
the FPGA seeks from its start. EOF and N/P ask Linux to mount the adjacent
original file. The channel wraps at either end.

Use MiSTer Main's per-core INI setting for the host executable:

```ini
[RetroTV]
main=linux/retrotv-main
```

Build that binary from upstream Main revision
`738cb7acc246c830739d02d862c0cc2a275738bb`, which is release 20261010.
Apply `RetroTV/mister-main/integration.patch`, copy
`RetroTV/mister-main/retrotv_mount.cpp` to the Main source root, then build
with the upstream ARM GNU toolchain. Main creates a local mount socket for
the RetroTV launcher. The UART hold command stops the old read session.
Main then announces the new file size and the controller sends the existing
channel seek frame. The standalone movie reader uses that size for EOF and
seeking.

## Manual playlist selection

`media_movie_playlist` walks USTAR headers and parses the embedded M3U before
starting a movie session. Member tables hold movie and optional SRT bounds.
A selected member triggers the same drain/reset path as loading a new movie.
The reader translates member-relative duration/seek/playback positions to
physical archive LBAs. Decoder internals remain independent of the archive.
See [TAR/M3U playlists](PLAYLISTS.md).

## RetroTV slideshows and music channels

A folder with PNG or JPEG images plays a silent slideshow when it has no
active music or MPG video. Run **Analyze RetroTV Channels** to refresh the
channel list. Add MP3s to the same folder and run the analyzer again to
index the tracks for music playback. An indexed MP3 channel displays
`assets/music-stock.png` if it has no artwork. Each tune starts with the
first image in filename order. The slideshow advances every 20 seconds
and wraps independently of the current track.

Music playback needs the ALSA-enabled RetroTV build, `mpg123`, and
`libImlib2.so.1`. Deploy the matching menu and music scripts together.
The menu expects `/media/fat/linux/retrotv-music.py` and the stock image
at `/media/fat/linux/assets/music-stock.png`. The last video file stays mounted while tuned to music.

A persistent UART listener previews Left and Right on dark glass. Each
label stays visible for at least 100 ms. A playback worker looks up the
selected channel's indexed clips during browsing. RetroTV waits until
250 ms after the last press and displays any remaining labels before
mounting the selected clip or starting the slideshow. N and P change
tracks in music mode. Space
pauses and M mutes. Up continues to select cabinets. The first track starts
at the broadcast clock position, and subsequent tracks advance and wrap.
The Linux worker stops on tune away, Escape, or when the daemon loses the core.

The ARM decodes the original MP3 through mpg123 and ALSA. It renders each
still directly to one of two ARGB1555 surfaces in DDR at physical
`0x30E80000` and `0x30ED0000`, after the MPEG ingress buffer. Each is
428×379, with a 0x50000-byte allocation. A UART message publishes the
completed bank. The cabinet reader switches at the top of the glass and
reuses its line RAM. It continues to fetch the selected cabinet borders.
During music playback, the MPEG session drains and stays quiesced. A video
rescan returns ownership to that session.

## Cabinet gallery

The default cabinet is a late-1980s Trinitron XBR-inspired set on a black
1920×1080 canvas. The centered 1024×720 cabinet starts at (448,180).
Its 720×480 transparent opening starts at (600,290). Native clips use
one HDMI pixel per source pixel. Up and Down cycle through six
cabinets. F4 returns to the default cabinet. F5–F8 seek within a movie.

The launcher loads a startup bezel via MiSTer Main. The controller
preloads the gallery into DDR and signals the FPGA to enable the XBR
view. The six frames start at 0x31B00000 with a 2 MiB stride, sharing
the 720×480 still-image banks at 0x31900000 and 0x31A00000.

## RetroTV news channel

A channel directory containing a .retrotv-news marker displays the
scrolling blue bulletin. Analyze RetroTV Channels includes this folder
in the channel list along with video, music, and still-image channels.
Numbered CH folders tune in numeric order.

The Linux worker retrotv-news.py fetches headlines from BBC World News, NPR
World, and Deutsche Welle over HTTPS. It alternates sources, identifies
each headline by source, and removes duplicate titles. It fetches on first
use and updates every ten minutes by default while tuned. Set
news-refresh-minutes.txt in the news channel folder to a whole number
of minutes and retune to apply it immediately. The worker uses the
retrotv-news-ca.pem CA bundle and the board's clock. It saves the last
successful headlines and timestamp in a small .latest-bulletin.json
file inside the news channel and retries after one minute if all feeds fail.
Deploy the core and controller together with retrotv-news.py, the CA
bundle, and rtl/media_overlay_font.mem as retrotv-news-font.mem in
/media/fat/linux.

The worker draws 4096-row strips for the 428, 640, and 720 pixel-wide
openings and fills the inactive bank. News pages occupy 0x32800000
through 0x357FFFFF, with two 8 MiB banks per layout and rows 2048
bytes apart. The core selects the new page at frame prefetch and
advances one row on three of every four input frames. UART D4 and D5 publish the two
scrolling pages, while CC and CD keep publishing fixed slides.

## RetroTV stock news channel

CH 13 - Stock News uses the same scrolling renderer. Write stock in the
channel's .retrotv-news marker to enable its price board and technology,
AI, and space headlines from CNBC Tech, TechCrunch AI, and SpaceNews.
The board repeats in the scroll and shows last sales and percentage
changes from Nasdaq, in US dollars, with the quote time in Eastern Time.
Unavailable symbols keep their last saved quote with an asterisk.
The default refresh for this channel is five minutes while tuned.
Set news-refresh-minutes.txt in the channel folder to change that interval.

## RetroTV weather channel

A channel folder with weather in its .retrotv-news marker runs CH 14 using
retrotv_weather.py alongside retrotv-news.py. It estimates the locality from
the MiSTer's public network address via IPWho.is, caching the resulting
city and coordinates locally for up to a day. It does not save the address.
To override the locality, put latitude, longitude | City, Region | country
code in weather-location.txt. Use auto, or omit the file, for IP location.
Retune after changing the file.

The weather bulletin displays the nearest recent surface observations
available from ECCC in Canada or NOAA's worldwide METAR network. It shows
the station name, distance, and observation time. When a nearby station
is unavailable it labels the Open-Meteo current estimate as model data.
Open-Meteo supplies the four-day forecast. The weather channel refreshes
every ten minutes while tuned by default. A weather channel folder can set
a different interval in news-refresh-minutes.txt.

## RetroTV program guide and Space Desk

CH 15 - What's On Now uses guide in its .retrotv-news marker. It reads the
published channel list and uses the same indexed durations, playlist order,
and broadcast epoch as channel tuning. It shows scheduled titles and time
left for video and music, next start times, and a description for slideshows
and information channels. Manual playback overrides only affect the
channel being watched. The guide updates once a minute while tuned and
keeps its schedule in memory.

CH 16 - Space Desk uses space in its .retrotv-news marker. It shows
upcoming launches from Launch Library 2, ISS visibility predictions from
Pollux Labs, and NASA ISS and Artemis headlines. When the visibility
service is unavailable, ISS-in.space can provide overhead passes, with
optical visibility unconfirmed. Space Desk uses CH 14's weather location
unless its own weather-location.txt is set. Times use the MiSTer's local
timezone. The display updates every two minutes while tuned. The worker
requests fresh feeds every 20 minutes and retries a failed feed at the
next refresh after five minutes.

Install retrotv_guide.py and retrotv_space.py alongside the existing
news worker and weather module. Both channels use the existing FPGA
scrolling renderer.

## RetroTV Moon Channel

CH 17 - Moon uses moon in its .retrotv-news marker. It draws an observer-
oriented Moon, its illuminated fraction, compass bearing and elevation,
and the next moonrise, moonset and high point. Times use the MiSTer's
local timezone. The channel inherits CH 14's location unless its own
weather-location.txt overrides it. Retune to apply a location change.

Astronomy Engine computes the position and events locally. NASA SVS
Dial-A-Moon provides the textured image for the current hour; the worker
rotates it from celestial north to the observer's vertical. If that image
is unavailable, a locally shaded phase diagram displays the same phase.
The screen uses a single snapshot per local calendar date and shows when
it was taken. The first tune of a new day takes that day's snapshot. When
left tuned, it updates at local midnight. The worker stores only the most
recent compressed snapshot so retuning or restarting preserves it.
It uses the fixed slideshow banks and UART CC/CD.

Deploy retrotv_moon.py and astronomy_engine-2.1.19-py3-none-any.whl
alongside the news and weather workers under /media/fat/linux.
The wheel is unmodified and includes Astronomy Engine's MIT license.
