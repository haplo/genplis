import json
import pathlib


class GenplisJSONEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, pathlib.Path):
            return str(obj)
        return super(GenplisJSONEncoder, self).default(obj)
