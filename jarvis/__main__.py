"""Entry point: python -m jarvis"""
import uvicorn

from . import config as config_mod

BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
        Just A Rather Very Intelligent System
"""


def main():
    print(BANNER)
    cfg = config_mod.load()
    uvicorn.run("jarvis.server:app", host="127.0.0.1", port=cfg["port"], log_level="warning")


if __name__ == "__main__":
    main()
