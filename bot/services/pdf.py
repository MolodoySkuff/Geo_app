import os
import datetime
import logging
from jinja2 import Environment, FileSystemLoader, select_autoescape

env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"])
)

def _wrap(c, text, max_width, font_name="Helvetica", font_size=10):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    words = (text or "").split()
    line, lines = "", []
    for w in words:
        test = (line + " " + w).strip()
        if stringWidth(test, font_name, font_size) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines

def render_report(*args, **kwargs):
    return None