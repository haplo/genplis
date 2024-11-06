import sys

from tinytag import TinyTag

LARGE_TAG = 1000


def get_tags(file_path, args):
    if not TinyTag.is_supported(file_path):
        print(f"Skipping {file_path}: not supported by tinytag")
        return {}
    tag = TinyTag.get(file_path).as_dict()
    # remove large tags, they are likely images or lyrics
    for key in list(tag.keys()):
        value = tag[key]
        if get_tag_size(value) > LARGE_TAG:
            if args.verbose:
                print(f"Removing tag {key} because it's larger than {LARGE_TAG} bytes")
            del tag[key]
    return tag


def get_tag_size(value):
    if isinstance(value, list):
        return sum(get_tag_size(v) for v in value)
    return sys.getsizeof(value)
