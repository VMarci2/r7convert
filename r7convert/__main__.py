import sys


def cli(argv: list[str]) -> int:
    """r7convert --convert CLIP [CLIP ...] --out DIR [--log FILE] [--prores] [--no-exr]"""
    from pathlib import Path

    from .convert import Converter, Settings, probe_clips
    from .media import Tools

    args = argv[1:]
    out = Path(args[args.index("--out") + 1])
    log_path = Path(args[args.index("--log") + 1]) if "--log" in args else None
    clips = [Path(a) for a in args[args.index("--convert") + 1:] if not a.startswith("--")]
    clips = [c for c in clips if c != out and c != log_path]

    log_file = open(log_path, "w", encoding="utf-8") if log_path else None

    def log(message: str) -> None:
        if log_file:
            log_file.write(message + "\n")
            log_file.flush()
        elif sys.stdout:
            print(message)

    try:
        from . import __version__
        log(f"Canon R7 EXR Converter v{__version__}")
        tools = Tools.discover()
        log(f"ffmpeg: {tools.ffmpeg}")
        log(f"exiftool: {tools.exiftool}")
        settings = Settings(output_dir=out, write_exr="--no-exr" not in args,
                            write_prores="--prores" in args)
        Converter(tools, settings, log).run(probe_clips(clips, tools))
        return 0
    except Exception as error:
        log(f"error: {error}")
        return 1
    finally:
        if log_file:
            log_file.close()


def main() -> int:
    if "--convert" in sys.argv:
        return cli(sys.argv)
    from .ui import main as ui_main
    return ui_main()


if __name__ == "__main__":
    sys.exit(main())
