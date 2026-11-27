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
saves the previous file with a `.retrotv.bak` suffix. For an upgrade, return to the MiSTer menu first.
Then use the new ZIP and follow the same steps.

## Add your own channels

Create numbered folders in `/media/fat/games/RetroTV/channels/`. Use a
folder name like `CH 1 - Cartoons`, with a unique channel number. The
built-in channels use 0, 12–17, 21–22, and 50.

- **Video.** Use progressive MPEG-2 Program Stream `.mpg` files with MP2
  audio. The standard picture is 720×480 at 29.97 fps. Files play directly,
  in filename order, on the broadcast clock. After the last video, a
  random test card plays for 20 seconds before the first video starts again.
- **Pictures.** Use PNG or JPEG files. Images advance in filename order
  every 20 seconds. Use **Page Up** for the next image and **Page Down** for
  the previous image, including when the slideshow has music. A 720×480
  image fills the tube.
- **Music.** Add MP3s to a picture folder to play music during the slideshow.
  A music folder without pictures uses the included stock image.

Run **Scripts → Analyze RetroTV Channels** after adding, removing, or
replacing media. The analyzer updates the channel list and duration
indexes. It leaves the media files as supplied.

## Open the channel guide

Press **F1** for the channel guide, which lists up to 14 channels per page.
Type two digits to tune immediately,
such as `00` for Test Cards or `02` for Channel 2. You can also highlight a
channel with **Up** and **Down** and press **Enter**. **Esc** closes the guide.

## Add more test cards

Channel 0 uses a built-in test pattern and can play regional cards from
Canada, the United States, the United Kingdom, continental Europe, and
Australia. Cards advance every 20 seconds. RetroTV moves the old CH 51
collection to Channel 0 on upgrade. See the [card sources and credits](RetroTV/TEST_CARDS.md).

From the RetroTV source checkout, run this on a computer with Python 3.9+
and Internet access. Pass the path to the existing RetroTV channels folder
on your MiSTer file share or SD card.

```sh
python3 RetroTV/setup_test_cards.py "/path/to/games/RetroTV/channels"
```

You can also copy `setup_test_cards.py` and `TEST_CARDS.md` into the same
folder on your MiSTer and run `python3 setup_test_cards.py` there. The
script checks the downloaded images and preserves existing channel files.
Run **Scripts → Analyze RetroTV Channels** afterward, then tune to CH 0.

## Choose a cabinet and background

At 1920×1080 HDMI, **Up** and **Down** choose the cabinet. Hold **Shift**
with either key to cycle through the backgrounds. Choose from solid black,
ten living rooms from the 1940s–1960s, the original mid-century living room,
the retro media room, the spacecraft bay, five early-1980s arcades, a
tropical veranda, and an operational command center.
**F4** returns to the default XBR cabinet. The video opening is 720×480 pixels.
At 1080p, press **F4**, then **Down** once for the FPGATron upright or twice
for the Bubbatron upright.

On scrolling information channels, **Page Up** makes the text faster and
**Page Down** makes it slower. Each press adjusts the speed by 20% of the
normal rate, within a range of 20%–240%. The Moon channel is a still image.

CH 21 and CH 22 use the same scrolling controls. Each bulletin refreshes
once every 24 hours while the MiSTer is on, regardless of the selected
channel. The SD card keeps the last bulletin available offline. CH 22
labels recently accepted scores and Submission Watch stories separately.

## Capture and view screenshots

Press **Print Screen** in RetroTV to save a PNG of the cabinet and its
picture to `/media/fat/games/RetroTV/channels/CH - 50 Screenshots/`.
At 1080p the PNG includes the selected background.
CH 50 starts with the latest capture and advances every 20 seconds. The
current picture slides left as the next one enters from the right.

In CH 50, **Page Up** shows the next image and **Page Down** shows the
previous image. Press **D** twice to delete the current image. Pressing
any other key after the first **D** dismisses the confirmation.

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
