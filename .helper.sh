#!/usr/bin/env bash
set -eu

SCRIPT="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname ${SCRIPT})"

prepare_env() {
    echo bla
    if [ -f "${SCRIPT_DIR}/.env.sh" ]; then
        . "${SCRIPT_DIR}/.env.sh"
        reexport_env
    else
        >&2 echo "Error: .env.sh is not missing"
        exit 1
    fi

    # Disable DXVK logs, we don't need em
    export DXVK_LOG_LEVEL=none
}

reexport_env() {
    export TERM
    export WINEDEBUG
    export WINEDLLPATH
    export LD_LIBRARY_PATH
    export WINEPREFIX
    export WINEESYNC
    export WINEFSYNC
    export SteamGameId
    export SteamAppId
    export WINEDLLOVERRIDES
    export STEAM_COMPAT_CLIENT_INSTALL_PATH
    export WINE_LARGE_ADDRESS_AWARE
    export GST_PLUGIN_SYSTEM_PATH_1_0
    export WINE_GST_REGISTRY_DIR
    export MEDIACONV_AUDIO_DUMP_FILE
    export MEDIACONV_AUDIO_TRANSCODED_FILE
    export MEDIACONV_VIDEO_DUMP_FILE
    export MEDIACONV_VIDEO_TRANSCODED_FILE
}

run_ea() {
    prepare_env
    # Trick EA Desktop app into authenticating and keeping running
    wine64 c:\\windows\\system32\\steam.exe "link2ea://launchgame/0?platform=steam&theme=tf2"
}

gdb_ns() {
    prepare_env

    export WINELOADERNOEXEC=1
    wine64 wineconsole NorthstarLauncher.exe &

    until pid=$(pidof NorthstarLauncher.exe)
    do   
        sleep 0.1
    done

    gdb -x "${SCRIPT_DIR}/gdbinit" -p ${pid}

}
