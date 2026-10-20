import json
from pathlib import Path


class GenplisJSONEncoder(json.JSONEncoder):
    def default(self, o: object) -> object:
        if isinstance(o, Path):
            return str(o)
        return super().default(o)
