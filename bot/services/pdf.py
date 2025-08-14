import os, datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

env = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html"])
)

def render_report(metric_set, addr, source="", map_path=""):
    tpl = env.get_template("report.html")
    html = tpl.render(
        addr=addr,
        m=metric_set,
        source=source,
        generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        map_path=map_path
    )
    out_dir = "cache/reports"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
    HTML(string=html, base_url=os.getcwd()).write_pdf(out_path)
    return out_path