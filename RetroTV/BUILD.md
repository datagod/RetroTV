# Build and package RetroTV

## FPGA

Use Quartus Prime Lite 17.0 (the initial RetroTV build uses 17.0.0 Build
595). From the repository root run `quartus_sh --flow compile Raster`.
Keep the reports for the build you ship. The output is
`output_files/Raster.rbf`.

## MiSTer Main

Use the source archive attached to the corresponding RetroTV release, or
check out [MiSTer Main](https://github.com/MiSTer-devel/Main_MiSTer) at
`738cb7acc246c830739d02d862c0cc2a275738bb`. For a fresh checkout, apply
`mister-main/integration.patch` and copy `mister-main/retrotv_mount.cpp` to
the Main source root. With the Arm GNU Toolchain
`10.2-2020.11` for `arm-none-linux-gnueabihf` on PATH, run `make`
in that directory. The build writes `bin/MiSTer`.

## Installer package

Download the
[November 5, 2026 CA bundle](https://curl.se/ca/cacert-2026-11-05.pem),
then run this from the RetroTV repository root:

```sh
python3 RetroTV/package_release.py output_files/Raster.rbf /path/to/Main_MiSTer/bin/MiSTer cacert-2026-11-05.pem dist/RetroTV-mister.zip
```

The packager uses an explicit list of program files and artwork assets.
The release also supplies the patched MiSTer Main tree, including its
Makefile and license, and GitHub's tagged RetroTV source archive.

## Cabinet artwork

The source PNGs and generated frames are included. With Pillow installed,
regenerate the cabinet gallery and startup frame using
`python3 RetroTV/make_xbr_cabinets.py`.
