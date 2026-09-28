"""Offset-preserving masks for the fallback JavaScript source scanner.

This is not a JS parser. Template literals are masked in full, including their
interpolations; regular-expression literals are not parsed by this helper.
"""


def code_mask(text: str) -> str:
    result = list(text)
    i = 0
    while i < len(text):
        start = i
        if text.startswith('//', i):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
        elif text.startswith('/*', i):
            end = text.find('*/', i + 2)
            i = len(text) if end < 0 else end + 2
        elif text[i] in "\"'`":
            quote = text[i]
            i += 1
            while i < len(text):
                if text[i] == '\\':
                    i += 2
                elif text[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            i = min(i, len(text))
        else:
            i += 1
            continue
        for index in range(start, i):
            if text[index] not in '\r\n':
                result[index] = ' '
    return ''.join(result)


def call_end(mask: str, opening: int) -> int:
    """Return the closing parenthesis offset, or -1 for an incomplete call."""
    depth = 0
    for index in range(opening, len(mask)):
        if mask[index] == '(':
            depth += 1
        elif mask[index] == ')':
            depth -= 1
            if depth == 0:
                return index
    return -1
