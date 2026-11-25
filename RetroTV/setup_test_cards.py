#!/usr/bin/env python3
"""Download the optional RetroTV test-card slideshow to a channels directory."""

import argparse
from hashlib import sha256
from pathlib import Path
import ssl
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

CARD_ROOT = Path("/media/fat")
CHANNELS = CARD_ROOT / "games/RetroTV/channels"
CERTIFICATE = CARD_ROOT / "linux/retrotv-news-ca.pem"
CHANNEL_NAME = "CH 51 - Test Cards"
USER_AGENT = "RetroTV-TestCards/1.0 (https://github.com/datagod/RetroTV)"
MAX_IMAGE_BYTES = 4 * 1024 * 1024
CARDS = (
    (
        "01-Canada-CBC-Montreal.png",
        "https://upload.wikimedia.org/wikipedia/commons/9/90/Philips_circle_pattern_CBC_Montreal_recreation.png",
        "696d5a9108c28fe6eeac553191c259922fc4af8061161e154b72250e9d2afcf6",
    ),
    (
        "02-USA-RCA-Indian-Head.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/1/1b/RCA_Indian_Head_test_pattern.JPG",
        "4b486d37de32e58912c60c685d423695deda2e4fb9995a2baa71d24fd0e1a0fc",
    ),
    (
        "03-UK-BBC-Test-Card-F.jpg",
        "https://professionalmoron.com/wp-content/uploads/2019/05/bbc-test-card-f.jpg",
        "9c50d47d4cc53ae08d84aca1987eb2e645f8e1599757e9c2ae9b7d16225a2ad3",
    ),
    (
        "04-UK-BBC-Test-Card-C.jpg",
        "https://tvark.org/media/1998i/2018-12-06/464b1c146ba8514c20a961fbff807d20172a48fd.jpg",
        "8ac170d5a8fdf7d84d38e44aaa1046a6d56a8cb3845433b264fe179bb07e18ba",
    ),
    (
        "05-Europe-TMC-819-lines.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/2/25/Mire_tmc_819_lignes.jpg",
        "ce73976c2852e1d700d75385e41d8837b46e254fbb9fc7eefb0cd8ea4db0c609",
    ),
    (
        "06-Germany-Telefunken-FuBK.png",
        "https://thumb.wikimedia.org/wikipedia/commons/thumb/1/1c/FuBK_testcard_vectorized.svg/960px-FuBK_testcard_vectorized.svg.png",
        "f474fe4021b057e5f0989b06741ad1d7b07adde318af4f6a8de483b4812eb200",
    ),
    (
        "07-Australia-STW9-Perth-1974.jpg",
        "https://cdn.sanity.io/images/dhoneoxg/production/0516fe78f9d7d33021af5bc913df70971b94fc9b-768x576.jpg",
        "5a196b0b8b09533325f7673057baac0feca8de7ecab2d123ddd66428c5f2fe31",
    ),
)


def install(channels, credits):
    if not channels.is_dir():
        raise ValueError(f"Channels directory does not exist: {channels}")
    channel = channels / CHANNEL_NAME
    context = None
    if CERTIFICATE.is_file():
        context = ssl.create_default_context(cafile=str(CERTIFICATE))
        context.set_alpn_protocols(["http/1.1"])
    with TemporaryDirectory(prefix=".retrotv-test-cards-", dir=channels) as temp:
        staging = Path(temp)
        for name, url, digest in CARDS:
            target = channel / name
            if target.exists():
                if sha256(target.read_bytes()).hexdigest() != digest:
                    raise ValueError(f"Existing image differs: {target}")
                continue

            print(f"Downloading {name}", flush=True)
            request = Request(url)
            if url.startswith(("https://upload.wikimedia.org/", "https://thumb.wikimedia.org/")):
                request.add_header("User-Agent", USER_AGENT)
            try:
                with urlopen(request, timeout=20, context=context) as response:
                    data = response.read(MAX_IMAGE_BYTES + 1)
            except OSError as error:
                raise ValueError(f"Could not download {name}: {error}") from error
            if len(data) > MAX_IMAGE_BYTES or sha256(data).hexdigest() != digest:
                raise ValueError(f"The source returned different image bytes for {name}.")
            (staging / name).write_bytes(data)

        credits_target = channel / "SOURCES.md"
        if not credits_target.exists():
            (staging / credits_target.name).write_bytes(credits)
        channel.mkdir(exist_ok=True)
        for staged in staging.iterdir():
            target = channel / staged.name
            if not target.exists():
                staged.replace(target)

    print(f"CH 51 is ready at {channel}. Run Analyze RetroTV Channels on your MiSTer.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "channels", nargs="?", type=Path, default=CHANNELS,
        help="path to the RetroTV channels directory (defaults to the MiSTer SD card)",
    )
    args = parser.parse_args()
    credits_path = Path(__file__).with_name("TEST_CARDS.md")
    try:
        install(args.channels, credits_path.read_bytes())
    except (OSError, ValueError) as error:
        parser.exit(1, f"CH 51 setup failed: {error}\n")
