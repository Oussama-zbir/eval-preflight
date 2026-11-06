import json


class LoadError(ValueError):
    """The input could not be read or does not match the expected format."""


def loads_json(text: str) -> object:
    """json.loads, reporting nesting too deep for the parser as a JSONDecodeError."""
    try:
        return json.loads(text)
    except RecursionError:
        raise json.JSONDecodeError("nested too deeply", text, 0) from None


__all__ = ["LoadError"]
