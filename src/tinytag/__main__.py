# pylint: disable=missing-module-docstring,protected-access

from __future__ import annotations
from io import StringIO
from os.path import splitext
import csv
import json
import os
import sys

from tinytag import TinyTag, TinyTagException


def _usage() -> None:
    print('''tinytag [options] <filename...>

    -h, --help
        Display help

    -i, --save-image <image-path>
        Save the cover art to a file

    -f, --format json|csv|tsv|tabularcsv
        Specify how the output should be formatted

    -s, --skip-unsupported
        Skip files that do not have a file extension supported by tinytag

''')


def _pop_param(name: str, _default: str | None) -> str | None:
    if name in sys.argv:
        idx = sys.argv.index(name)
        sys.argv.pop(idx)
        return sys.argv.pop(idx)
    return _default


def _pop_switch(name: str) -> bool:
    if name in sys.argv:
        idx = sys.argv.index(name)
        sys.argv.pop(idx)
        return True
    return False


def _print_tag(tag: TinyTag, formatting: str, header_printed: bool = False) -> bool:
    data = tag.as_dict()
    del data['images']
    if formatting == 'json':
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return header_printed
    if formatting not in {'csv', 'tsv', 'tabularcsv'}:
        return header_printed
    for field, value in data.items():
        if isinstance(value, str):
            data[field] = value.replace('\x00', ';')  # use a more friendly separator for output
    csv_file = StringIO()
    delimiter = '\t' if formatting == 'tsv' else ','
    writer = csv.writer(csv_file, delimiter=delimiter, lineterminator='\n')
    if formatting == 'tabularcsv':
        if not header_printed:
            writer.writerow(data.keys())
            header_printed = True
        writer.writerow(data.values())
        value = csv_file.getvalue().strip()
    else:
        writer.writerows(data.items())
        value = csv_file.getvalue()
    print(value)
    return header_printed


def _run() -> int:
    header_printed = False
    save_image_path = _pop_param('--save-image', None) or _pop_param('-i', None)
    formatting = (_pop_param('--format', None) or _pop_param('-f', None)) or 'json'
    skip_unsupported = _pop_switch('--skip-unsupported') or _pop_switch('-s')
    filenames = sys.argv[1:]
    display_help = not filenames or _pop_switch('--help') or _pop_switch('-h')
    if display_help:
        _usage()
        return 0

    for i, filename in enumerate(filenames):
        if skip_unsupported and not (TinyTag.is_supported(filename) and os.path.isfile(filename)):
            continue
        try:
            tag = TinyTag.get(filename, image=save_image_path is not None)
            if save_image_path:
                # allow for saving the image of multiple files
                actual_save_image_path = save_image_path
                if len(filenames) > 1:
                    actual_save_image_path, ext = splitext(actual_save_image_path)
                    actual_save_image_path += f'{i:05d}{ext}'
                image = tag.images.any
                if image is not None:
                    with open(actual_save_image_path, 'wb') as file_handle:
                        file_handle.write(image.data)
            header_printed = _print_tag(tag, formatting, header_printed)
        except (OSError, TinyTagException) as exc:
            sys.stderr.write(f'{filename}: {exc}\n')
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(_run())
