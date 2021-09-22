class EmptyFileError(Exception):
    pass

class MaybeDefault(Exception):
    def __init__(self, default):
        self.value = default
