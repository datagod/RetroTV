#include "user_io.h"
#include "scaler.h"

#include <cerrno>
#include <cstdio>
#include <cstdint>
#include <ctime>
#include <cstdlib>
#include <cstring>
#include <limits.h>
#include <linux/input-event-codes.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace {
constexpr char socket_path[] = "/tmp/retrotv-video.sock";
constexpr char gallery_socket[] = "/tmp/retrotv-screenshots.sock";
constexpr char gallery_folder[] = "/media/fat/games/RetroTV/channels/CH - 50 Screenshots";
constexpr char channel_root[] = "/media/fat/games/RetroTV/channels/";

const char* core_filename()
{
    const char* path = get_rbf_path();
    const char* slash = std::strrchr(path, '/');
    return slash ? slash + 1 : path;
}

bool gallery_key(char command)
{
    static const int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) return false;
    sockaddr_un addr = {};
    addr.sun_family = AF_UNIX;
    std::memcpy(addr.sun_path, gallery_socket, sizeof(gallery_socket));
    return sendto(fd, &command, 1, MSG_DONTWAIT,
                  reinterpret_cast<const sockaddr*>(&addr), sizeof(addr)) == 1;
}

void capture_screenshot()
{
    if (mkdir(gallery_folder, 0755) && errno != EEXIST) {
        std::perror("RetroTV screenshot folder");
        return;
    }
    timespec now = {};
    if (clock_gettime(CLOCK_REALTIME, &now)) return;
    tm local = {};
    if (!localtime_r(&now.tv_sec, &local)) return;
    char date[24];
    if (!std::strftime(date, sizeof(date), "%Y%m%d_%H%M%S", &local)) return;
    char filename[160];
    std::snprintf(filename, sizeof(filename), "%s/%s_%09ld.png", gallery_folder, date, now.tv_nsec);
    request_screenshot(filename, 0, true);
}

int open_mount_socket()
{
    int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) return -1;

    sockaddr_un addr = {};
    addr.sun_family = AF_UNIX;
    std::memcpy(addr.sun_path, socket_path, sizeof(socket_path));
    unlink(socket_path);
    mode_t old_mask = umask(0077);
    int result = bind(fd, reinterpret_cast<const sockaddr*>(&addr), sizeof(addr));
    umask(old_mask);
    if (result == 0) return fd;

    std::perror("RetroTV mount socket");
    close(fd);
    return -1;
}

bool mount_movie(const char* requested)
{
    char canonical[PATH_MAX];
    if (!realpath(requested, canonical) ||
        std::strncmp(canonical, channel_root, sizeof(channel_root) - 1))
        return false;

    size_t size = std::strlen(canonical);
    struct stat info = {};
    if (size < 4 || strcasecmp(canonical + size - 4, ".mpg") ||
        stat(canonical, &info) || !S_ISREG(info.st_mode) || info.st_size < 4)
        return false;

    user_io_bufferinvalidate(0);
    return user_io_file_mount(canonical, 0, 0, 0, true) != 0;
}
} // namespace

bool retrotv_keyboard(uint16_t key, int press)
{
    static const bool enabled = !strcasecmp(core_filename(), "RetroTV.mgl") ||
                                !strcasecmp(core_filename(), "RetroTV.rbf");
    if (!enabled) return false;
    if (key == KEY_SYSRQ || key == KEY_PRINT) {
        if (press == 1) {
            gallery_key('c');
            capture_screenshot();
        }
        return true;
    }
    if (press != 1) return false;
    if (user_io_osd_is_visible()) {
        gallery_key('c');
        return false;
    }

    switch (key) {
        case KEY_PAGEUP: return gallery_key('n');
        case KEY_PAGEDOWN: return gallery_key('p');
        case KEY_D: return gallery_key('d');
        default: gallery_key('c'); return false;
    }
}

void retrotv_mount_poll()
{
    static bool initialized = false;
    static int fd = -1;
    if (!initialized) {
        initialized = true;
        const char* name = core_filename();
        if (!strcasecmp(name, "RetroTV.mgl") || !strcasecmp(name, "RetroTV.rbf")) {
            constexpr char startup_bezel[] = "/media/fat/games/RetroTV/v2/cabinet.raw";
            // Index 2 fills the startup picture. Index 6 completes the FPGA's cabinet preload.
            if (!user_io_file_tx(startup_bezel, 2) || !user_io_file_tx(startup_bezel, 6))
                std::fprintf(stderr, "RetroTV could not load the startup bezel\n");
        } else if (strcasecmp(name, "RetroTV_2.rbf") && strcasecmp(name, "RetroTV_2.mgl")) {
            return;
        }
        fd = open_mount_socket();
    }
    if (fd < 0) return;

    sockaddr_un peer = {};
    socklen_t peer_len = sizeof(peer);
    char request[PATH_MAX];
    ssize_t size = recvfrom(fd, request, sizeof(request) - 1, MSG_TRUNC,
                            reinterpret_cast<sockaddr*>(&peer), &peer_len);
    if (size < 0) return;

    char response = 0;
    if (size > 0 && static_cast<size_t>(size) < sizeof(request) &&
        !std::memchr(request, '\0', size)) {
        request[size] = '\0';
        response = mount_movie(request) ? 1 : 0;
    }
    if (peer_len <= sizeof(peer))
        sendto(fd, &response, 1, MSG_DONTWAIT, reinterpret_cast<const sockaddr*>(&peer), peer_len);
}
