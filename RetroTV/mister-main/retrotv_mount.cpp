#include "user_io.h"
#include "scaler.h"
#include "input.h"
#include "osd.h"
#include "shmem.h"
#include "video.h"

#include <algorithm>
#include <cerrno>
#include <bitset>
#include <cstdio>
#include <cstdint>
#include <ctime>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits.h>
#include <linux/input-event-codes.h>
#include <string>
#include <strings.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <vector>

bool retrotv_video_1080p();

namespace {
constexpr char socket_path[] = "/tmp/retrotv-video.sock";
constexpr char gallery_socket[] = "/tmp/retrotv-screenshots.sock";
constexpr char slideshow_socket[] = "/tmp/retrotv-slideshow.sock";
constexpr char scene_socket[] = "/tmp/retrotv-scenes.sock";
constexpr char input_socket[] = "/tmp/retrotv-input.sock";
constexpr char catalogue_file[] = "/tmp/retrotv-chans";
constexpr char gallery_folder[] = "/media/fat/games/RetroTV/channels/CH - 50 Screenshots";
constexpr char channel_root[] = "/media/fat/games/RetroTV/channels/";
constexpr char last_channel_file[] = "/media/fat/games/RetroTV/channels/last";

const char* core_filename()
{
    const char* path = get_rbf_path();
    const char* slash = std::strrchr(path, '/');
    return slash ? slash + 1 : path;
}

bool send_control(const char* command, size_t length, const char* path)
{
    static const int fd = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) return false;
    sockaddr_un addr = {};
    addr.sun_family = AF_UNIX;
    std::strcpy(addr.sun_path, path);
    return sendto(fd, command, length, MSG_DONTWAIT,
                  reinterpret_cast<const sockaddr*>(&addr), sizeof(addr)) == static_cast<ssize_t>(length);
}

bool send_media_key(char command, const char* path = gallery_socket)
{
    return send_control(&command, 1, path);
}

bool send_input(const std::string& command)
{
    return send_control(command.data(), command.size(), input_socket);
}

int channel_number(const std::string& name)
{
    const char* next = name.c_str();
    if (strncasecmp(next, "CH ", 3)) return -1;
    next += 3;
    while (*next == ' ') ++next;
    if (*next == '-') ++next;
    while (*next == ' ') ++next;
    if (*next < '0' || *next > '9') return -1;
    char* end = nullptr;
    const long number = std::strtol(next, &end, 10);
    return number <= 99 && (!*end || *end == ' ' || *end == '-') ? static_cast<int>(number) : -1;
}

int number_key(uint16_t key)
{
    if (key == KEY_0) return 0;
    if (key >= KEY_1 && key <= KEY_9) return key - KEY_1 + 1;
    constexpr uint16_t keypad[] = {KEY_KP0, KEY_KP1, KEY_KP2, KEY_KP3, KEY_KP4,
                                  KEY_KP5, KEY_KP6, KEY_KP7, KEY_KP8, KEY_KP9};
    for (int i = 0; i < 10; ++i)
        if (keypad[i] == key) return i;
    return -1;
}

class ChannelGuide {
    static constexpr size_t page_size = 14;

    std::vector<std::string> channels;
    std::bitset<KEY_MAX + 1> consumed;
    std::string digits, message;
    size_t selected = 0;
    bool open = false;
    int previous_size = 8;

    void paint() const
    {
        const size_t page = selected / page_size;
        const size_t pages = (channels.size() + page_size - 1) / page_size;
        auto row = [](int line, const std::string& text, bool selected = false) {
            OsdWrite(line, text.substr(0, 30).c_str(), selected);
        };
        row(0, "Type 2 digits   Page " + std::to_string(page + 1) + "/" + std::to_string(pages ? pages : 1));
        for (size_t position = 0; position < page_size; ++position) {
            const size_t index = page * page_size + position;
            const int line = 1 + static_cast<int>(position);
            if (index < channels.size()) row(line, channels[index], selected == index);
            else row(line, "");
        }
        row(15, message.empty() ? "CH " + digits + std::string(2 - digits.size(), '_') +
                                  "  Up/Down Enter Esc" : message);
    }

    void show()
    {
        send_media_key('c');
        std::ifstream input(catalogue_file);
        channels.clear();
        for (std::string name; std::getline(input, name);)
            if (!name.empty()) channels.push_back(name);
        selected = 0;
        std::ifstream last(last_channel_file);
        std::string current;
        if (std::getline(last, current)) {
            const auto entry = std::find(channels.begin(), channels.end(), current);
            if (entry != channels.end()) selected = entry - channels.begin();
        }
        digits.clear();
        message.clear();
        if (channels.empty()) message = "No channels available";
        previous_size = OsdGetSize();
        OsdSetSize(16);
        OsdClear();
        OsdSetTitle("Channel Guide");
        paint();
        OsdUpdate();
        OsdEnable(DISABLE_KEYBOARD);
        open = true;
    }

    void hide()
    {
        OsdDisable();
        OsdSetSize(previous_size);
        open = false;
    }

    void tune(size_t index)
    {
        if (index < channels.size() && send_input("tune " + channels[index])) hide();
        else message = "Channel is unavailable";
    }

public:
    bool keyboard(uint16_t key, int press)
    {
        if (key <= KEY_MAX && consumed.test(key) && press != 1) {
            if (!press) consumed.reset(key);
            return true;
        }
        if (!open) {
            if (key != KEY_F1 || press != 1 || user_io_osd_is_visible()) return false;
            show();
        } else {
            if (key == KEY_F12 || key == KEY_MENU) {
                if (press == 1) hide();
                return false;
            }
            if (press != 1) return true;
            if (key == KEY_F1 || key == KEY_ESC) hide();
            else if (key == KEY_UP && selected) --selected;
            else if (key == KEY_DOWN && selected + 1 < channels.size()) ++selected;
            else if (key == KEY_PAGEUP && selected >= page_size) selected -= page_size;
            else if (key == KEY_PAGEDOWN && (selected / page_size + 1) * page_size < channels.size())
                selected = std::min(selected + page_size, channels.size() - 1);
            else if (key == KEY_ENTER || key == KEY_KPENTER) tune(selected);
            else if (key == KEY_BACKSPACE) {
                if (!digits.empty()) digits.pop_back();
                message.clear();
            } else {
                const int digit = number_key(key);
                if (digit >= 0) {
                    message.clear();
                    digits += static_cast<char>('0' + digit);
                    if (digits.size() == 2) {
                        const int number = 10 * (digits[0] - '0') + digits[1] - '0';
                        size_t index = 0;
                        while (index < channels.size() && channel_number(channels[index]) != number) ++index;
                        if (index == channels.size()) message = "Channel " + digits + " unavailable";
                        else tune(index);
                        digits.clear();
                    }
                }
            }
            if (open) paint();
        }
        if (key <= KEY_MAX) consumed.set(key);
        return true;
    }

};

ChannelGuide channel_guide;

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
    if (channel_guide.keyboard(key, press)) return true;
    if (key == KEY_SYSRQ || key == KEY_PRINT) {
        if (press == 1) {
            send_media_key('c');
            capture_screenshot();
        }
        return true;
    }
    if (key == KEY_UP || key == KEY_DOWN) {
        static unsigned shifted_arrows = 0;
        const unsigned flag = key == KEY_UP ? 1 : 2;
        if (shifted_arrows & flag) {
            if (!press) shifted_arrows &= ~flag;
            return true;
        }
        if (press == 1 && !user_io_osd_is_visible()) {
            if ((get_key_mod() & (LSHIFT | RSHIFT)) &&
                send_media_key(key == KEY_UP ? '+' : '-', scene_socket)) {
                shifted_arrows |= flag;
                send_media_key('c');
                return true;
            }
            send_media_key(key == KEY_UP ? 'u' : 'd', scene_socket);
        }
    }
    if (press != 1) return false;
    if (user_io_osd_is_visible()) {
        send_media_key('c');
        return false;
    }

    if (key == KEY_F4) send_media_key('0', scene_socket);

    switch (key) {
        case KEY_N:
            send_media_key('c');
            return send_input("next");
        case KEY_PAGEUP: return send_media_key('n') || send_media_key('n', slideshow_socket);
        case KEY_PAGEDOWN: return send_media_key('p') || send_media_key('p', slideshow_socket);
        case KEY_D: return send_media_key('d');
        default: send_media_key('c'); return false;
    }
}

bool retrotv_scene_screenshot(unsigned char* output, int width, int height, int scaled_width, int scaled_height)
{
    if (width != 1024 || height != 720 || scaled_width != 1024 || scaled_height != 720)
        return false;
    if (strcasecmp(core_filename(), "RetroTV.mgl") && strcasecmp(core_filename(), "RetroTV.rbf"))
        return false;
    if (!retrotv_video_1080p() || video_is_direct() || video_fb_state())
        return false;

    const int state = open("/tmp/retrotv-scene-bank", O_RDONLY | O_CLOEXEC);
    if (state < 0) return false;
    char bank = 0;
    const auto count = read(state, &bank, 1);
    close(state);
    if (count != 1 || (bank != '0' && bank != '1')) return false;

    constexpr int screen_width = 1920, screen_height = 1080;
    constexpr int video_width = 720, video_height = 480;
    constexpr int frame_bytes = screen_width * screen_height * 2;
    const uint32_t address = 0x36000000 + (bank - '0') * 0x400000;
    auto scene = static_cast<const uint16_t*>(shmem_map(address, frame_bytes));
    if (!scene) return false;

    std::vector<unsigned char> picture(video_width * video_height * 4);
    for (int row = 0; row < video_height; ++row) {
        auto source = output + 4 * ((110 + row) * width + 152);
        auto target = picture.data() + 4 * row * video_width;
        std::memcpy(target, source, 4 * video_width);
    }

    for (int index = 0; index < screen_width * screen_height; ++index) {
        uint16_t pixel = scene[index];
        output[4 * index]     = (pixel & 31) << 3;
        output[4 * index + 1] = ((pixel >> 5) & 31) << 3;
        output[4 * index + 2] = ((pixel >> 10) & 31) << 3;
        output[4 * index + 3] = 255;
    }
    shmem_unmap(const_cast<uint16_t*>(scene), frame_bytes);

    for (int row = 0; row < video_height; ++row) {
        auto source = picture.data() + 4 * row * video_width;
        auto target = output + 4 * ((290 + row) * screen_width + 600);
        std::memcpy(target, source, 4 * video_width);
    }
    return true;
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
