#!/usr/bin/env python3

from abc import ABC, abstractmethod
import os
import argparse
import subprocess
import ntpath
from pathlib import Path
import logging
import sys
from io import BytesIO
from zipfile import ZipFile
from urllib.request import urlopen
import time

import psutil
try:
    from protontricks import *
except ImportError:
    raise Exception("nsgdb needs Protontricks to function")

SCRIPT = os.path.abspath(os.path.dirname(__file__))
CACHE_DIR = os.path.join(SCRIPT, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def prepend_args(x, y, delim):
    return (y + delim + x) if y else x

def append_args(x, y, delim):
    return (x + delim + y) if y else x

def enable_logging(info=False):
    level = logging.DEBUG if info else logging.INFO
    logging.basicConfig(
        stream=sys.stderr, level=level,
        format="%(name)s (%(levelname)s): %(message)s")

    # make Protontricks less verbose
    pt_log = logging.getLogger("protontricks")
    pt_log.setLevel(logging.WARNING)

def get_args():
    parser = argparse.ArgumentParser(
        prog="nsdbg",
        description="Script to help debugging Northstar on Linux"
    )

    parser.add_argument("--compat", choices=["wine", "proton"], default="proton", help="Selects what compatibility layer will be used")
    parser.add_argument("debugger", choices=["x64dbg"], help="Specify which debugger you want to run the game in")
    parser.add_argument("--install-ea", action="store_true", help="Install EA Desktop app if needed")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--kill-ea", action="store_true", help="Kill EA Desktop on exit")

    args = parser.parse_args()
    return args

pargs = get_args()
enable_logging(pargs.verbose)

log = logging.getLogger("nsgdb")

if pargs.compat == "wine":
    log.warning("Stock wine is known to have problems with the EA App")

if pargs.install_ea and pargs.compat == "proton":
    log.warning("Not installing EA Desktop into Proton prefix")

### Game ###

TITANFALL2_APPID = 1237970
class Game:

    def __init__(self):
        self.log = logging.getLogger("nsgdb.game")

        self.game_dir = self.find_titanfall2()

    def find_titanfall2(self):
        game_dir = os.getenv("TF2_GAME_DIR")
        if not game_dir:
            self.log.info("TF2_GAME_DIR not specified, checking steam")
            game_dir = self.__find_titanfall2_steam()

        return game_dir

    def __find_titanfall2_steam(self):
        steam_path, steam_root = find_steam_path()

        steam_lib_paths = get_steam_lib_paths(steam_path)
        if not steam_lib_paths:
            raise Exception("Could not find Steam libraries")

        steam_apps = get_steam_apps(steam_root, steam_path, steam_lib_paths)
        if not steam_apps:
            raise Exception("Could not find any steam apps")

        for a in steam_apps:
            if a.appid == TITANFALL2_APPID:
                return a.install_path

        return None

### Game/ ###

### Compat ###

class CompatBase(ABC):

    def __init__(self, game):
        self.log = logging.getLogger("nsgdb.compat")
        self.log.debug(f"Using {self.__class__.__name__}")

        self.game = game

    @abstractmethod
    def run(self, *args, **kwargs):
        ...

    @abstractmethod
    def start_ea(self):
        ...

    def maybe_start_ea(self):
        possible_names = [
            "EADesktop.exe",
            "EABackgroundSer"
        ]

        ea_desktop_running = any(p.name() for p in psutil.process_iter(attrs=['name']) if p.name() in possible_names)

        if ea_desktop_running:
            self.log.debug("EA App already running, not starting it again")
            return None

        return self.start_ea()

class CompatWine(CompatBase):
    # Program Files\Electronic Arts\EA Desktop\EA Desktop
    ea_desktop_path = ("Program Files", "Electronic Arts", "EA Desktop", "EA Desktop")
    ea_desktop_exe = "EADesktop.exe"

    def run(self, *args, **kwargs):
        env_vars = dict(os.environ)
        env_vars.setdefault("WINEDEBUG", "-all")

        kwargs.update({
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
            "env": env_vars
        })

        cmd = ["wine"] + list(args)
        log.debug(f"Running {cmd}")
        return subprocess.Popen(
            cmd,
            **kwargs
        )

    def __get_wineprefix(self) -> str:
        p = os.getenv("WINEPREFIX")
        if p:
            return p

        # Wine explicitly uses $HOME
        home = os.getenv("HOME")
        if not home:
            raise Exception("Unable to find Wine prefix")

        return os.path.join(home, ".wine")

    def __ea_installed(self) -> bool:
        prefix_ea_exe = os.path.join(self.__get_wineprefix(), "drive_c", *self.ea_desktop_path, self.ea_desktop_exe)

        return os.path.isfile(prefix_ea_exe)

    def start_ea(self):
        if not self.__ea_installed():
            global pargs
            if not pargs.install_ea:
                raise Exception("The EA Desktop app is not available")

            installer = os.path.join(self.game.game_dir, "__Installer", "Origin", "redist", "internal", "EAappInstaller.exe")

            self.log.info("Installing EA Desktop")
            self.run(installer).wait()

            if not self.__ea_installed():
                raise Exception("Failed to install EA Desktop")

        ea_path = ntpath.join("C:\\", *self.ea_desktop_path, self.ea_desktop_exe)
        return self.run(ea_path)

class CompatProton(CompatBase):
    compatdir = None
    compattool = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.steam_path, steam_root = find_steam_path()

        steam_lib_paths = get_steam_lib_paths(self.steam_path)
        if not steam_lib_paths:
            raise Exception("Could not find Steam libraries")

        steam_apps = get_steam_apps(steam_root, self.steam_path, steam_lib_paths)
        if not steam_apps:
            raise Exception("Could not find any steam apps")

        for a in steam_apps:
            if a.appid == TITANFALL2_APPID and a.prefix_path:
                self.compatdir = a.prefix_path
                break

        if not self.compatdir:
            raise Exception("Failed to find Titanfall 2 prefix")

        if self.compatdir.name == "pfx":
            self.compatdir = (self.compatdir / "..").resolve()

        self.log.debug(f"Compatibility directory: {self.compatdir}")

        proton_app = find_proton_app(self.steam_path, steam_apps, TITANFALL2_APPID)
        self.compattool = proton_app.install_path

        if not self.compattool:
            print("Failed to find Proton version")
        self.log.debug(f"Compatibility tool: {self.compattool}")

    def run(self, *args, **kwargs):
        env_vars = dict(os.environ)
        env_vars.setdefault("TERM", "xterm")
        env_vars["PATH"] = append_args(f"{self.compattool}/files/bin", env_vars.get("PATH"), ":")
        env_vars.setdefault("WINEDEBUG", "-all")
        env_vars["WINEDLLPATH"] = prepend_args(f"{self.compattool}/files/lib64/wine:{self.compattool}/files/lib/wine", env_vars.get("WINEDLLPATH"), ":")
        env_vars.setdefault("LD_LIBRARY_PATH", append_args(f"{self.compattool}/files/lib64/:{self.compattool}/files/lib/:{self.game.game_dir}", env_vars.get("LD_LIBRARY_PATH"), ":"))
        env_vars.setdefault("WINEPREFIX", str(os.path.join(self.compatdir, "pfx")))
        env_vars.setdefault("WINEESYNC", "1")
        env_vars.setdefault("WINEFSYNC", "1")
        env_vars.setdefault("SteamGameId", str(TITANFALL2_APPID))
        env_vars.setdefault("SteamAppId", str(TITANFALL2_APPID))
        env_vars["WINEDLLOVERRIDES"] = append_args("wsock32=n,b;steam.exe=b;dotnetfx35.exe=b;dotnetfx35setup.exe=b;beclient.dll=b,n;beclient_x64.dll=b,n;d3d11=n;d3d10core=n;d3d9=n;dxgi=n;d3d12=n;d3d12core=n", env_vars.get("WINEDLLOVERRIDES"), ";")
        env_vars.setdefault("STEAM_COMPAT_CLIENT_INSTALL_PATH", self.steam_path)
        env_vars.setdefault("WINE_LARGE_ADDRESS_AWARE", "1")
        env_vars["GST_PLUGIN_SYSTEM_PATH_1_0"] = prepend_args(f"{self.compattool}/files/lib64/gstreamer-1.0:{self.compattool}/files/lib/gstreamer-1.0", env_vars.get("GST_PLUGIN_SYSTEM_PATH_1_0"), ":")
        env_vars.setdefault("WINE_GST_REGISTRY_DIR", f"{self.compatdir}/gstreamer-1.0/")

        env_vars["DXVK_LOG_LEVEL"] = "none"

        self.log.debug(f"Using prefix: {env_vars.get('WINEPREFIX')}")

        kwargs.update({
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
            "env": env_vars
        })

        cmd = [f"{self.compattool}/files/bin/wine"] + list(args)
        self.log.debug(f"Running {cmd}")

        return subprocess.Popen(
            cmd,
            **kwargs
        )

    def start_ea(self):
        # link2ea implicitly authenticates via Steam
        p = self.run("steam.exe", "link2ea://launchgame/0?platform=steam&theme=tf2")

        # Give it a second to start up
        time.sleep(5)

        return p

compat_map = {
    "wine": CompatWine,
    "proton": CompatProton,
}
#x = CompatWine()
### Compat/ ###

### Debugger ###

class DebuggerBase(ABC):
    def __init__(self, game, compat):
        self.log = logging.getLogger("nsgdb.debugger")
        self.log.debug(f"Using {self.__class__.__name__}")

        self.game = game
        self.compat = compat

    @abstractmethod
    def run(self):
        ...

class DebuggerX64DBG(DebuggerBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.path = os.path.join(CACHE_DIR, "x64dbg")
        os.makedirs(self.path, exist_ok=True)

        path_64 = os.path.join(self.path, "release", "x64")
        self.path_64_exe = os.path.join(path_64, "x64dbg.exe")

        if not os.path.isfile(self.path_64_exe):
            self.__download()

    def __download(self):
        log.info("Downloading x64dbg")

        resp = urlopen("https://sourceforge.net/projects/x64dbg/files/latest/download")
        archive = ZipFile(BytesIO(resp.read()))

        log.info("Extracting x64dbg")
        archive.extractall(path=self.path)

    def run(self):
        return self.compat.run(self.path_64_exe, cwd=self.game.game_dir)

debug_map = {
    "x64dbg": DebuggerX64DBG,
}

### Debugger/ ###

def main():
    if os.name != "posix":
        raise Exception("Running on unsupported Operating System")

    g = Game()
    c = compat_map[pargs.compat](g)
    d = debug_map[pargs.debugger](g, c)

    ea = c.maybe_start_ea()
    d.run().wait()

    if pargs.kill_ea and ea:
        ea.kill()

if __name__ == "__main__":
    main()
