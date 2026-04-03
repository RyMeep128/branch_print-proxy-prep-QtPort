import os
import configparser

from constants import cwd

class GlobalConfig:
    def __init__(self):
        self.VibranceBump = False
        self.MaxDPI = 1200
        self.DefaultPageSize = "Letter"
        self.EnableUncrop = True
        self.DisplayColumns = 5
        self.HighResBackendURL = "https://mpcfill.com/"
        self.HighResCacheTTLSeconds = 60 * 60
        self.HighResSearchCacheMemoryMB = 24
        self.HighResImageCacheMemoryMB = 64


def load_config() -> GlobalConfig:
    cfg_path = os.path.join(cwd, "config.ini")
    config_parser = configparser.ConfigParser()

    parsed_config = GlobalConfig()
    if config_parser.read(cfg_path):
        def_cfg = config_parser["DEFAULT"]
        parsed_config.VibranceBump = def_cfg.getboolean("Vibrance.Bump", False)
        parsed_config.MaxDPI = def_cfg.getint("Max.DPI", 1200)
        parsed_config.DefaultPageSize = def_cfg.get("Page.Size", "Letter")
        parsed_config.EnableUncrop = def_cfg.getboolean("Enable.Uncrop", True)
        parsed_config.DisplayColumns = def_cfg.getint("Display.Columns", 5)
        parsed_config.HighResBackendURL = def_cfg.get(
            "HighRes.BackendURL", "https://mpcfill.com/"
        )
        parsed_config.HighResCacheTTLSeconds = def_cfg.getint(
            "HighRes.CacheTTLSeconds", 60 * 60
        )
        parsed_config.HighResSearchCacheMemoryMB = def_cfg.getint(
            "HighRes.SearchCacheMemoryMB", 24
        )
        parsed_config.HighResImageCacheMemoryMB = def_cfg.getint(
            "HighRes.ImageCacheMemoryMB", 64
        )

    return parsed_config


def save_config(cfg):
    cfg_path = os.path.join(cwd, "config.ini")

    config_parser = configparser.ConfigParser()

    def_cfg = config_parser["DEFAULT"]
    def_cfg["Vibrance.Bump"] = str(cfg.VibranceBump)
    def_cfg["Max.DPI"] = str(cfg.MaxDPI)
    def_cfg["Page.Size"] = cfg.DefaultPageSize
    def_cfg["Enable.Uncrop"] = str(cfg.EnableUncrop)
    def_cfg["Display.Columns"] = str(cfg.DisplayColumns)
    def_cfg["HighRes.BackendURL"] = cfg.HighResBackendURL
    def_cfg["HighRes.CacheTTLSeconds"] = str(cfg.HighResCacheTTLSeconds)
    def_cfg["HighRes.SearchCacheMemoryMB"] = str(cfg.HighResSearchCacheMemoryMB)
    def_cfg["HighRes.ImageCacheMemoryMB"] = str(cfg.HighResImageCacheMemoryMB)

    with open(cfg_path, "w") as configfile:
        config_parser.write(configfile)


CFG = load_config()
