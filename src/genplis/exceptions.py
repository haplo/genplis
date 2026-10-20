class GenplisError(Exception):
    pass


class GenplisDBError(GenplisError):
    pass


class GenplisM3UGException(GenplisError):
    def __init__(self, message: str, filename: str, line: int) -> None:
        super().__init__(message)
        self.filename = filename
        self.line = line


class GenplisConfigError(GenplisError):
    pass
