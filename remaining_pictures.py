import argparse
import shutil
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    TK_AVAILABLE = True
except ImportError:
    tk = None
    filedialog = None
    messagebox = None
    TK_AVAILABLE = False


def _list_file_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        raise NotADirectoryError(f"Directory does not exist: {directory}")
    return {item.name for item in directory.iterdir() if item.is_file()}


def get_remaining_pictures(pictures_dir: str, completed_pictures_dir: str) -> list[str]:
    pictures_path = Path(pictures_dir)
    completed_path = Path(completed_pictures_dir)

    pictures = _list_file_names(pictures_path)
    completed_pictures = _list_file_names(completed_path)
    return sorted(pictures - completed_pictures)


def copy_remaining_pictures(
    pictures_dir: str,
    completed_pictures_dir: str,
    destination_dir: str,
) -> list[str]:
    source_path = Path(pictures_dir)
    destination_path = Path(destination_dir)
    destination_path.mkdir(parents=True, exist_ok=True)

    remaining_pictures = get_remaining_pictures(pictures_dir, completed_pictures_dir)
    copied_files: list[str] = []

    for filename in remaining_pictures:
        source_file = source_path / filename
        destination_file = destination_path / filename

        shutil.copy2(source_file, destination_file)
        copied_files.append(filename)

    return copied_files


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find pictures that are present in the source directory but missing in "
            "the completed directory, then copy them to a destination directory. "
            "You can pass all paths as arguments or use --pick."
        )
    )
    parser.add_argument(
        "pictures_dir",
        nargs="?",
        help="Directory with original pictures",
    )
    parser.add_argument(
        "completed_pictures_dir",
        nargs="?",
        help="Directory with already completed pictures",
    )
    parser.add_argument(
        "destination_dir",
        nargs="?",
        help="Directory where remaining pictures should be copied",
    )
    parser.add_argument(
        "--pick",
        action="store_true",
        help="Use system directory picker to choose all three directories",
    )
    return parser


def _pick_directories() -> tuple[str, str, str]:
    if (
        not TK_AVAILABLE
        or tk is None
        or filedialog is None
        or messagebox is None
    ):
        raise RuntimeError("Tkinter is not available on this system.")

    prompts = [
        ("Select source pictures directory", "Choose the folder with original pictures."),
        (
            "Select completed pictures directory",
            "Choose the folder with already completed pictures.",
        ),
        ("Select destination directory", "Choose where remaining pictures will be copied."),
    ]

    selected_paths: list[str] = []
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()

    try:
        for title, message in prompts:
            messagebox.showinfo(
                "Select Directory",
                message,
                parent=root,
            )
            root.lift()
            root.focus_force()
            root.update()

            selected = filedialog.askdirectory(title=title, parent=root)
            if not selected:
                raise ValueError("Directory selection cancelled.")
            selected_paths.append(selected)
    finally:
        root.destroy()

    return selected_paths[0], selected_paths[1], selected_paths[2]


def _resolve_directories(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[str, str, str]:
    provided_all = all(
        [args.pictures_dir, args.completed_pictures_dir, args.destination_dir]
    )

    if args.pick or not provided_all:
        if not args.pick and any(
            [args.pictures_dir, args.completed_pictures_dir, args.destination_dir]
        ):
            parser.error("Provide all three directories or use --pick.")
        if not TK_AVAILABLE:
            parser.error("Tkinter is unavailable. Provide directories as arguments.")
        try:
            pictures_dir, completed_pictures_dir, destination_dir = _pick_directories()
        except ValueError as exc:
            parser.error(str(exc))
        return pictures_dir, completed_pictures_dir, destination_dir

    return args.pictures_dir, args.completed_pictures_dir, args.destination_dir


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    pictures_dir, completed_pictures_dir, destination_dir = _resolve_directories(
        args,
        parser,
    )

    copied_files = copy_remaining_pictures(
        pictures_dir,
        completed_pictures_dir,
        destination_dir,
    )

    print(f"Copied {len(copied_files)} file(s) to {destination_dir}")
    for filename in copied_files:
        print(filename)


if __name__ == "__main__":
    main()