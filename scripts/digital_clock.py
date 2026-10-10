"""Scalable block digits for the navigator's digital clock."""

DIGITS = {
    '0': ('111', '101', '101', '101', '111'),
    '1': ('010', '110', '010', '010', '111'),
    '2': ('111', '001', '111', '100', '111'),
    '3': ('111', '001', '111', '001', '111'),
    '4': ('101', '101', '111', '001', '001'),
    '5': ('111', '100', '111', '001', '111'),
    '6': ('111', '100', '111', '101', '111'),
    '7': ('111', '001', '001', '001', '001'),
    '8': ('111', '101', '111', '101', '111'),
    '9': ('111', '101', '111', '001', '111'),
    ':': ('0', '1', '0', '1', '0'),
}


def clock_lines(value, width, height):
    """Fit HH:MM:SS to terminal cells, falling back to text in tiny windows."""
    glyphs = [DIGITS[char] for char in value]
    columns = sum(len(glyph[0]) for glyph in glyphs) + len(glyphs) - 1
    if width < columns or height < 5:
        return [value[:width]]
    scale_y = max(1, min(height // 5, width // columns // 2))
    scale_x = max(1, min(width // columns, scale_y * 2))
    lines = []
    for row in range(5):
        pixels = '0'.join(glyph[row] for glyph in glyphs)
        line = ''.join(('█' if pixel == '1' else ' ') * scale_x for pixel in pixels)
        lines.extend([line] * scale_y)
    return lines
