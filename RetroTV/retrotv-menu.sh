#!/bin/sh
# RetroTV UART helper. ttyS1 is the core UART. ttyS0 is the kernel console
# and is never opened here.
#
# UART control for RetroTV's channel controller.
# Core to Linux: A5 menu, A6/A8 next/previous channel, A9/AA next/previous clip.
# The standalone MPG mount uses D0 (hold) followed by CA (selected file's offset).
# Browser previews and music commands use the same protocol as the playlist core.
LOG=/tmp/retrotv-menu.log
CMD=/dev/MiSTer_cmd
TTY=/dev/ttyS1
ROOT=/media/fat/games/RetroTV/channels
LAST=$ROOT/last
ACTIVE_PID=/tmp/retrotv-active-mpg-pid
RESCAN=/tmp/retrotv-rescan-mpg
BC=/media/fat/linux/retrotv-broadcast.py
MUSIC=/media/fat/linux/retrotv-music.py

log() {
    echo "$(date '+%H:%M:%S') $1" >> "$LOG"
}

mister_pid() {
    ps w | awk '/\/media\/fat\/(MiSTer|linux\/retrotv-main) / && !/awk/ {print $1; exit}'
}

core_line() {
    pid=$1
    tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null
}

cmd_open() {
    pid=$1
    for fd in /proc/"$pid"/fd/*; do
        target=$(readlink "$fd" 2>/dev/null) || continue
        case "$target" in
            *MiSTer_cmd*) return 0 ;;
        esac
    done
    return 1
}

setup_tty() {
    stty -F "$TTY" 115200 cs8 -cstopb -parenb raw -echo clocal -ixon min 0 time 0
}

flush_tty() {
    dd if="$TTY" of=/dev/null bs=64 count=4 2>/dev/null
}

read_folders() {
    mkdir -p "$ROOT/CH - 50 Screenshots" || return 1
    find "$ROOT" -mindepth 1 -maxdepth 1 -type d ! -name cache ! -name live ! -name '.*' \
        ! -name 'CH 51 - Test Cards' -printf '%f\n' | sort -f > /tmp/retrotv-folders
}

read_chans() {
    mkdir -p "$ROOT/CH - 50 Screenshots" || return 1
    chanlist=/tmp/retrotv-chans
    chanlist_tmp=$(mktemp "${chanlist}.XXXXXX") || return 1
    if python3 "$BC" channels "$ROOT" > "$chanlist_tmp" &&
       mv "$chanlist_tmp" "$chanlist"; then
        return 0
    fi
    rm -f "$chanlist_tmp"
    return 1
}

one_line() {
    if [ -f "$1" ]; then
        awk 'NR==1 { sub(/\r/, ""); print; exit }' "$1"
    fi
}

has_media() {
    media_folder=$1
    shift
    [ -n "$(find "$media_folder" -maxdepth 1 -type f \( "$@" \) -print -quit)" ]
}

has_images() {
    has_media "$1" -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg'
}

process_channels() {
    echo "Looking for images, music, videos, and news channels."
    read_folders
    failed=0
    found=0
    selected=$(one_line "$LAST")
    selected_updated=0
    while IFS= read -r one; do
        [ -n "$one" ] || continue
        folder="$ROOT/$one"
        if [ "$one" = "CH - 50 Screenshots" ]; then
            found=1
            result="Screenshots ready"
        elif [ -f "$folder/.retrotv-news" ]; then
            found=1
            result="News ready"
        elif has_media "$folder" ! -name '.*' -iname '*.mp3'; then
            found=1
            echo "Indexing music $one"
            if python3 "$MUSIC" index "$folder"; then
                result=Updated
            else
                result=Failed
            fi
        elif has_media "$folder" -iname '*.mpg'; then
            found=1
            result=$(python3 "$BC" index "$folder") || result=Failed
        elif has_images "$folder"; then
            found=1
            result="Updated slideshow"
        else
            continue
        fi
        echo "$one: $result"
        case "$result" in
            Failed) failed=1 ;;
            Updated*) if [ "$selected" = "$one" ]; then selected_updated=1; fi ;;
        esac
    done < /tmp/retrotv-folders
    if [ "$found" -eq 0 ]; then
        echo "No playable channels found."
        return 1
    fi
    read_chans || return 1
    if [ "$selected_updated" -eq 1 ]; then
        pid=$(mister_pid)
        if [ -n "$pid" ]; then
            case "$(core_line "$pid")" in
                */retrotv-main*RetroTV.rbf\ *|*/retrotv-main*RetroTV_2.rbf\ *)
                    request=$(mktemp "$RESCAN.XXXXXX") || return 1
                    printf '%s\n' "$selected" > "$request"
                    mv "$request" "$RESCAN" || return 1
                    ;;
            esac
        fi
    fi
    return "$failed"
}

if [ "$1" = "--prepare" ]; then
    python3 "$BC" clock && read_chans
    exit $?
fi

if [ "$1" = "--process" ]; then
    process_channels
    exit $?
fi

exec 9>/tmp/retrotv-menu.lock
flock -n 9 || exit 0

log "start"
log "broadcast"
python3 "$BC" clock >> "$LOG" 2>&1 || log "broadcast clock initialization failed"
read_chans

preload_cabinets() {
    ready_codes=
    compact="$ROOT/../compact"
    xbr="$compact/trinitron-xbr-1989.raw"
    if [ -s "$xbr" ]; then
        if [ -s "$compact/jvc-d-series.raw" ] &&
           gallery_codes=$(python3 "$MUSIC" load-xbr-gallery "$compact" --tty "$TTY" 2>> "$LOG"); then
            ready_codes=${gallery_codes:-d2}
        elif python3 "$MUSIC" load-xbr "$xbr" --tty "$TTY" >> "$LOG" 2>&1; then
            ready_codes=d1
        else
            log "XBR bezel preload failed"
        fi
    fi
}

stop_listener() {
    if [ -n "$listener_pid" ]; then
        kill "$listener_pid" 2>/dev/null
        wait "$listener_pid" 2>/dev/null
        listener_pid=
    fi
}

listener_pid=
legacy_pid=
seen=
saw_gap=0
trap stop_listener EXIT
trap 'exit 0' HUP INT TERM
while true; do
    pid=$(mister_pid)
    line=
    if [ -n "$pid" ]; then
        line=$(core_line "$pid")
    fi
    if [ "$line" != "$seen" ]; then
        log "core ${line:-none}"
        seen=$line
    fi
    case "$line" in
        */retrotv-main*RetroTV.rbf\ *|*/retrotv-main*RetroTV_2.rbf\ *)
            legacy_pid=
            if [ ! -S /tmp/retrotv-video.sock ] || ! cmd_open "$pid"; then
                sleep 1
                continue
            fi
            if ! setup_tty; then
                log "ttyS1 setup failed"
                sleep 1
                continue
            fi
            flush_tty
            preload_cabinets
            startup=random
            if [ "$saw_gap" -eq 0 ]; then
                if [ "$(one_line "$ACTIVE_PID")" = "$pid" ]; then
                    startup=keep
                else
                    startup=resume
                fi
            else
                read_chans
            fi
            log "armed pid $pid ($startup)"
            python3 -u "$BC" listen "$ROOT" "$TTY" "$pid" "$startup" "$ready_codes" >> "$LOG" 2>&1 &
            listener_pid=$!
            wait "$listener_pid"
            listener_pid=
            sleep 1
            ;;
        *RetroTV_DDR*)
            if [ "$legacy_pid" != "$pid" ]; then
                setup_tty && flush_tty
                stty -F "$TTY" min 0 time 10 >/dev/null 2>&1
                legacy_pid=$pid
            fi
            flat=$(dd if="$TTY" bs=1 count=1 2>/dev/null | od -An -tx1 | tr -s ' ' | sed 's/^ //;s/ $//')
            if [ "$flat" = a5 ] && cmd_open "$pid"; then
                log "escape"
                printf 'load_core /media/fat/menu.rbf\n' > "$CMD"
                log "loaded menu"
                legacy_pid=
            fi
            ;;
        *)
            legacy_pid=
            saw_gap=1
            sleep 1
            ;;
    esac
done
