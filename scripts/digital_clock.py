"""Large, regular-weight numerals rendered with terminal half blocks."""

DIGITS = {
    '0': ('01110', '10001', '10001', '10001', '10001', '10001', '01110'),
    '1': ('00100', '01100', '00100', '00100', '00100', '00100', '01110'),
    '2': ('01110', '10001', '00001', '00010', '00100', '01000', '11111'),
    '3': ('11110', '00001', '00001', '01110', '00001', '00001', '11110'),
    '4': ('00010', '00110', '01010', '10010', '11111', '00010', '00010'),
    '5': ('11111', '10000', '10000', '11110', '00001', '00001', '11110'),
    '6': ('00110', '01000', '10000', '11110', '10001', '10001', '01110'),
    '7': ('11111', '00001', '00010', '00100', '01000', '01000', '01000'),
    '8': ('01110', '10001', '10001', '01110', '10001', '10001', '01110'),
    '9': ('01110', '10001', '10001', '01111', '00001', '00010', '01100'),
    ':': ('0', '0', '1', '0', '1', '0', '0'),
}


def clock_lines(value, width, height):
    """Fit large numerals to the available area, with square half-cell pixels."""
    glyphs = [DIGITS[char] for char in value]
    columns = sum(len(glyph[0]) for glyph in glyphs) + len(glyphs) - 1
    scale = min(width // columns, height * 2 // 7)
    if scale < 1:
        return [value[:width]]
    pixels = []
    for row in range(7):
        line = ''.join(pixel * scale for pixel in '0'.join(glyph[row] for glyph in glyphs))
        pixels.extend([line] * scale)
    if len(pixels) % 2:
        pixels.append('0' * len(pixels[0]))
    blocks = {'00': ' ', '10': '▀', '01': '▄', '11': '█'}
    return [''.join(blocks[top + bottom] for top, bottom in zip(pixels[row], pixels[row + 1]))
            for row in range(0, len(pixels), 2)]
