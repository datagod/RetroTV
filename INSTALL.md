# Install RetroTV on MiSTer

## Download and install

1. Download the `RetroTV-*-mister.zip` asset from the
   [latest RetroTV release](https://github.com/datagod/RetroTV/releases/latest).
2. Extract it into a new `RetroTV-Install` folder at the root of your MiSTer SD
   card. Inside it you should see `install.py` and `payload`. You can do this
   over the MiSTer file share or with the SD card in your computer.
3. On the MiSTer Linux console or over SSH, run:

   ```sh
   cd /media/fat/RetroTV-Install
   python3 install.py
   ```
4. Reboot the MiSTer. In the core menu, open **Other → RetroTV**. Set your
   MiSTer HDMI output to 1920×1080 for the native-size cabinet view.

Use a DE10-Nano or compatible Cyclone V MiSTer with an up-to-date Linux
image and Python 3.9 or newer. The music and slideshow features use the
MiSTer Linux versions of `mpg123`, `libmpg123.so.0`, and
`libImlib2.so.1`. An Internet connection and accurate system clock are
needed for the channels that fetch live data.

The installer adds the launcher and core, installs a RetroTV-specific Main
binary and startup helper, and creates the six information channels. It
preserves existing media, channel settings, and other startup entries.
When it changes an existing `MiSTer.ini` or `linux/user-startup.sh`, it
saves the previous file with a `.retrotv.bak` suffix. For upgrades, use
the new ZIP and follow the same steps.

## Add your own channels

Create numbered folders in `/media/fat/games/RetroTV/channels/`. Use a
folder name like `CH 1 - Cartoons`, with a unique channel number. The
built-in channels use numbers 12–17.

- **Video.** Use progressive MPEG-2 Program Stream `.mpg` files with MP2
  audio. The standard picture is 720×480 at 29.97 fps. Files play directly,
  in filename order, on the broadcast clock.
- **Pictures.** Use PNG or JPEG files. Images advance in filename order
  every 20 seconds. A 720×480 image fills the tube.
- **Music.** Add MP3s to a picture folder to play music during the slideshow.
  A music folder without pictures uses the included stock image.

Run **Scripts → Analyze RetroTV Channels** after adding, removing, or
replacing media. The analyzer updates the channel list and duration
indexes. It leaves the media files as supplied.

## Set the local weather and sky location

Weather, Space Desk, and Moon use the MiSTer's approximate public-IP
location by default. To enter a location yourself, create
`weather-location.txt` inside `CH 14 - Weather`. Put one line in the file
using this format:

```text
latitude, longitude | City, Region | country code
```

Use decimal coordinates and a two-letter country code. Space Desk and Moon
inherit this setting and also accept their own `weather-location.txt`.
Times are shown in the MiSTer's configured timezone. Moon takes one
snapshot per local calendar day.

## Troubleshooting

- If **RetroTV** is absent from **Other**, check that the installer created
  `/media/fat/_Other/RetroTV.mgl`.
- If channels stay blank after launch, confirm you rebooted after installing
  and check `/tmp/retrotv-menu.log` on the MiSTer.
- If a new media folder does not appear, run **Analyze RetroTV Channels**
  and confirm the folder starts with `CH` and its channel number.
- If the display does not use the XBR view, check that HDMI is at
  1920×1080 and wait for the cabinet to load.
