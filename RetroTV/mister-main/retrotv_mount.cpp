#include "user_io.h"

#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits.h>
#include <strings.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace {
constexpr char socket_path[] = "/tmp/retrotv-video.sock";
constexpr char channel_root[] = "/media/fat/games/RetroTV/channels/";

const char* core_filename()
{
    const char* path = get_rbf_path();
    const char* slash = std::strrchr(path, '/');
    return slash ? slash + 1 : path;
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

void retrotv_mount_poll()
{
    static bool initialized = false;
    static int fd = -1;
    if (!initialized) {
        initialized = true;
        const char* name = core_filename();
        if (!strcasecmp(name, "RetroTV.rbf")) {
            // The FPGA needs its startup bezel before switching to the DDR gallery.
            if (!user_io_file_tx("/media/fat/games/RetroTV/v2/cabinet.raw", 2))
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
