"""Entry point: python -m rocky"""
import uvicorn

from . import config as config_mod

BANNER = r"""
      ██████╗  ██████╗  ██████╗██╗  ██╗██╗   ██╗
      ██╔══██╗██╔═══██╗██╔════╝██║ ██╔╝╚██╗ ██╔╝
      ██████╔╝██║   ██║██║     █████╔╝  ╚████╔╝
      ██╔══██╗██║   ██║██║     ██╔═██╗   ╚██╔╝
      ██║  ██║╚██████╔╝╚██████╗██║  ██╗   ██║
      ╚═╝  ╚═╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝   ╚═╝
        Eridian engineer. Friend. "Good, good, good."
"""


def main():
    print(BANNER)
    cfg = config_mod.load()
    uvicorn.run("rocky.server:app", host="127.0.0.1", port=cfg["port"], log_level="warning")


if __name__ == "__main__":
    main()
