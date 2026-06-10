"""
print_generator.py — 3D print file generation for Ludus.
Generates nameplate (.3mf) and name tag (.stl) files per attendee.
Dependencies: build123d (pip), Graduate and Liberation Sans fonts.
ocp_vscode is intentionally NOT imported — it is a dev-only tool.
"""
import tempfile
from pathlib import Path

from build123d import (
    Align, BuildPart, BuildSketch, Color, FontStyle, Locations,
    Mesher, Mode, Plane, Rectangle, RectangleRounded, Text,
    export_stl, extrude, add,
)

# ── Nameplate parameters ───────────────────────────────────────────
PLATE_WIDTH   = 75.90
PLATE_HEIGHT  = 25.10
PLATE_DEPTH   = 0.8
CORNER_RADIUS = 2.0
NAME_SIZE     = 8
YEAR_SIZE     = 8
TEXT_DEPTH    = 0.4
LINE_GAP      = 1.5
PLATE_FONT    = "Graduate"

# ── Name tag parameters ────────────────────────────────────────────
TAG_TEXT_SIZE  = 20
TAG_TEXT_DEPTH = 3
TAG_BAR_HEIGHT = 10
TAG_BAR_DEPTH  = 0.8
TAG_FONT       = "Liberation Sans"


def generate_nameplate(username: str, year: str) -> bytes:
    """Generate a nameplate .3mf for multi-color printing.
    Gold body = plate with text void. Black body = text fill.
    Returns raw .3mf bytes. Raises on failure."""
    username = username.upper()

    name_y = (YEAR_SIZE + LINE_GAP) / 2
    year_y = -(NAME_SIZE + LINE_GAP) / 2

    with BuildPart() as text_part:
        with BuildSketch(Plane.XY.offset(PLATE_DEPTH - TEXT_DEPTH)):
            with Locations((0, name_y, 0)):
                Text(username, font_size=NAME_SIZE, font=PLATE_FONT,
                     align=(Align.CENTER, Align.CENTER))
            with Locations((0, year_y, 0)):
                Text(year, font_size=YEAR_SIZE, font=PLATE_FONT,
                     align=(Align.CENTER, Align.CENTER))
        extrude(amount=TEXT_DEPTH)

    with BuildPart() as plate_part:
        with BuildSketch():
            RectangleRounded(PLATE_WIDTH, PLATE_HEIGHT, CORNER_RADIUS)
        extrude(amount=PLATE_DEPTH)
        add(text_part.part, mode=Mode.SUBTRACT)

    plate_solid = plate_part.part
    plate_solid.label = "plate"
    plate_solid.color = Color("gold")

    text_solid = text_part.part
    text_solid.label = "text"
    text_solid.color = Color("black")

    tmp = tempfile.NamedTemporaryFile(suffix=".3mf", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    try:
        exporter = Mesher()
        exporter.add_shape(plate_solid)
        exporter.add_shape(text_solid)
        exporter.write(str(tmp_path))
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def generate_nametag(gamertag: str) -> bytes:
    """Generate a name tag .stl.
    Text printed face-down; bar stands proud as the base/stand.
    Returns raw .stl bytes. Raises on failure."""
    gamertag = gamertag.upper()

    with BuildPart() as tag:
        with BuildSketch():
            Text(gamertag, font_size=TAG_TEXT_SIZE, font=TAG_FONT,
                 font_style=FontStyle.BOLD,
                 align=(Align.MIN, Align.MIN))
        extrude(amount=TAG_TEXT_DEPTH)

        text_width = tag.part.bounding_box().size.X

        with BuildSketch(Plane.XY.offset(-0.01)):
            Rectangle(text_width, TAG_BAR_DEPTH + 0.01,
                      align=(Align.MIN, Align.MIN))
        extrude(amount=TAG_BAR_HEIGHT)

    result = tag.part.fuse()

    tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    try:
        export_stl(result, str(tmp_path))
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)
