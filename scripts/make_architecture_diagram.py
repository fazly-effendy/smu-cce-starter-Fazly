"""Draw docs/images/nimbus-aws-architecture.svg (the AWS network diagram).

Run:  python scripts/make_architecture_diagram.py
The SVG is hand-built so it stays in sync with scripts/nimbus-stack.yaml:
edit the labels here when the template changes, then re-run.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1600, 1215
FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"

PALETTES = {
    "ec2": ("#9DB8F7", "#4169D1", "#2A4CA6"),
    "ebs": ("#86E3D6", "#1FA598", "#14796F"),
    "rds": ("#DDD5FF", "#A897EE", "#7F6FD2"),
    "cfn": ("#F9B9D3", "#E0588F", "#B63C71"),
    "yahoo": ("#C4E8F8", "#5BB7DF", "#3A8FC0"),
    "git": ("#8B93A1", "#3F4756", "#262D39"),
    "igw": ("#A7E3BF", "#2E9E61", "#1F7748"),
    "cw": ("#FDE68A", "#F59E0B", "#B45309"),
}

out: list[str] = []
markers: dict[str, str] = {}


def marker(color: str, start: bool = False) -> str:
    key = ("s" if start else "e") + color.lstrip("#")
    if key not in markers:
        path = "M11,1 L2,6 L11,11" if start else "M1,1 L10,6 L1,11"
        ref = 3 if start else 9
        markers[key] = (f'<marker id="m{key}" viewBox="0 0 12 12" refX="{ref}" refY="6" markerWidth="5" '
                        f'markerHeight="5" orient="auto" markerUnits="strokeWidth"><path d="{path}" fill="none" '
                        f'stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></marker>')
    return f"url(#m{key})"


def add(s: str) -> None:
    out.append(s)


def text(x, y, s, size=14, weight=400, fill="#1E293B", anchor="start", opacity=1.0, italic=False):
    style = ' font-style="italic"' if italic else ""
    add(
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}" opacity="{opacity}"{style}>{escape(s)}</text>'
    )


def panel(x, y, w, h, fill="#FFFFFF", stroke="#C9D6EA", rx=22, dash=None, width=1.6):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"{d}/>')


def pill(x, y, label, fill, color, size=13, pad=14, h=28):
    w = int(len(label) * size * 0.56) + pad * 2
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2}" fill="{fill}"/>')
    text(x + pad, y + h / 2 + size * 0.36, label, size=size, weight=600, fill=color)
    return w


def cube(cx, cy, w, h, palette, glyph=None, ghost=False):
    """Isometric box: (cx, cy) is the centre of the top face."""
    d = w * 0.58
    top = f"{cx - w/2},{cy} {cx},{cy - d/2} {cx + w/2},{cy} {cx},{cy + d/2}"
    left = f"{cx - w/2},{cy} {cx},{cy + d/2} {cx},{cy + d/2 + h} {cx - w/2},{cy + h}"
    right = f"{cx},{cy + d/2} {cx + w/2},{cy} {cx + w/2},{cy + h} {cx},{cy + d/2 + h}"
    if ghost:
        for pts in (left, right, top):
            add(f'<polygon points="{pts}" fill="#F8FAFC" stroke="#94A3B8" stroke-width="1.6" stroke-dasharray="6 5"/>')
        return
    t, l, r = PALETTES[palette]
    add(f'<ellipse cx="{cx}" cy="{cy + d/2 + h + 10}" rx="{w*0.55}" ry="{d*0.22}" fill="#0F172A" opacity=".08"/>')
    add(f'<polygon points="{left}" fill="{l}"/><polygon points="{right}" fill="{r}"/><polygon points="{top}" fill="{t}"/>')
    if glyph:
        # Draw the glyph on the left (front) face: a 100 x h coordinate box mapped onto the face.
        add(f'<g transform="matrix({w/200},{d/200},0,1,{cx - w/2},{cy})">{glyph(h)}</g>')


def screen_glyph(h):
    return (f'<rect x="22" y="{h*0.28}" width="56" height="{h*0.42}" rx="4" fill="#DCE7FF" opacity=".95"/>'
            f'<rect x="31" y="{h*0.40}" width="30" height="5" rx="2" fill="#4169D1"/>'
            f'<rect x="31" y="{h*0.52}" width="22" height="5" rx="2" fill="#4169D1"/>')


def disk_glyph(h):
    return (f'<rect x="24" y="{h*0.30}" width="52" height="{h*0.40}" rx="5" fill="#D8FBF6" opacity=".95"/>'
            f'<rect x="32" y="{h*0.42}" width="36" height="5" rx="2" fill="#14796F"/>'
            f'<rect x="32" y="{h*0.54}" width="24" height="5" rx="2" fill="#14796F"/>')


def stack_glyph(h):
    return "".join(f'<rect x="24" y="{h*(0.26+0.17*i)}" width="52" height="{h*0.09}" rx="3" fill="#FFF0F6" opacity=".95"/>' for i in range(3))


def chart_glyph(h):
    return (f'<path d="M24 {h*0.74} L 42 {h*0.52} L 56 {h*0.62} L 76 {h*0.30}" stroke="#FFFBEB" stroke-width="7" '
            'fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


def git_glyph(h):
    return (f'<path d="M36 {h*0.32} L 22 {h*0.50} L 36 {h*0.68} M64 {h*0.32} L 78 {h*0.50} L 64 {h*0.68} M56 {h*0.26} L 44 {h*0.74}" '
            'stroke="#F1F5F9" stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


def gate_glyph(h):
    return (f'<path d="M26 {h*0.42} H 70 M58 {h*0.30} L 72 {h*0.42} L 58 {h*0.54}" stroke="#ECFDF3" stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="M74 {h*0.66} H 30 M42 {h*0.54} L 28 {h*0.66} L 42 {h*0.78}" stroke="#ECFDF3" stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


def rds_cylinder(cx, cy):
    """Stacked database discs, matching the purple database icon style."""
    t, l, r = PALETTES["rds"]
    add(f'<ellipse cx="{cx}" cy="{cy + 92}" rx="58" ry="12" fill="#0F172A" opacity=".08"/>')
    for i in range(3):
        y = cy + 52 - i * 28
        add(f'<path d="M{cx-52},{y} v 20 a 52 20 0 0 0 104 0 v -20 z" fill="{l}"/>')
        add(f'<path d="M{cx},{y+20} m 0 0 a 52 20 0 0 0 52 -20 v 20 a 52 20 0 0 1 -52 20 z" fill="{r}"/>')
        add(f'<ellipse cx="{cx}" cy="{y}" rx="52" ry="20" fill="{t}" stroke="{l}" stroke-width="1.2"/>')


def cloud_icon(cx, cy):
    cube(cx, cy, 120, 34, "yahoo")
    add(f'<path transform="translate({cx-38},{cy-30}) scale(0.76)" d="M22 62 H 78 A 18 18 0 0 0 74 27 A 26 26 0 0 0 26 30 A 16 16 0 0 0 22 62 Z" '
        'fill="#EAF7FD" stroke="#3A8FC0" stroke-width="5" stroke-linejoin="round"/>')


def laptop(cx, cy):
    add(f'<ellipse cx="{cx}" cy="{cy + 78}" rx="82" ry="10" fill="#0F172A" opacity=".08"/>')
    add(f'<rect x="{cx-60}" y="{cy-50}" width="120" height="86" rx="6" fill="#2A4CA6"/>')
    add(f'<rect x="{cx-50}" y="{cy-40}" width="100" height="66" rx="3" fill="#BFD7FF"/>')
    add(f'<rect x="{cx-50}" y="{cy-40}" width="100" height="9" fill="#EAF2FF"/>')
    for i, wd in enumerate((70, 52, 62)):
        add(f'<rect x="{cx-40}" y="{cy-22 + i*13}" width="{wd}" height="5" rx="2" fill="#2A4CA6"/>')
    add(f'<path d="M{cx-74},{cy+36} H {cx+74} L {cx+88},{cy+56} H {cx-88} Z" fill="#7E9BE6"/>')
    add(f'<rect x="{cx-88}" y="{cy+56}" width="176" height="6" rx="3" fill="#2A4CA6"/>')


def arrow(points, color="#3D5A99", width=3.5, dash=None, both=False, label=None, label_pos=None, label_color=None):
    d = " ".join(("M" if i == 0 else "L") + f"{x},{y}" for i, (x, y) in enumerate(points))
    da = f' stroke-dasharray="{dash}"' if dash else ""
    ms = f' marker-start="{marker(color, True)}"' if both else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" '
        f'stroke-linecap="round"{da} marker-end="{marker(color)}"{ms}/>')
    if label:
        lx, ly = label_pos
        text(lx, ly, label, size=13, weight=600, fill=label_color or color, anchor="middle")


def lock(x, y, color):
    add(f'<g transform="translate({x},{y})"><rect x="0" y="6" width="12" height="10" rx="2" fill="{color}"/>'
        f'<path d="M2.5 6 V4 a3.5 3.5 0 0 1 7 0 V6" stroke="{color}" stroke-width="2" fill="none"/></g>')


def sg_badge(x, y, name, rule, color="#1F4FB8", fill="#E4ECFF"):
    w = int((len(name) + len(rule) + 3) * 12.6 * 0.5) + 44
    add(f'<rect x="{x}" y="{y}" width="{w}" height="30" rx="8" fill="{fill}" stroke="{color}" stroke-opacity=".35"/>')
    lock(x + 12, y + 6, color)
    add(f'<text x="{x + 32}" y="{y + 20}" font-size="12.6" fill="{color}"><tspan font-weight="700">{escape(name)}</tspan>'
        f'<tspan dx="6">{escape(rule)}</tspan></text>')


# --------------------------------------------------------------------------
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">')
DEFS_AT = len(out)
add(f'<rect width="{W}" height="{H}" fill="#F2F6FC"/>')

# Header
add(f'<rect width="{W}" height="104" fill="#16295E"/>')
text(56, 50, "Nimbus · AWS architecture with automatic scaling", size=31, weight=700, fill="#FFFFFF")
text(56, 80, "Stage 3 deployment in the AWS Academy Sandbox (us-east-1), created by one CloudFormation template",
     size=16, fill="#C7D4F2")

# ---------------- Internet column ----------------
panel(30, 128, 282, 980)
pill(52, 148, "INTERNET", "#E2E8F0", "#334155")

laptop(171, 290)
text(171, 392, "Relationship managers", size=17, weight=700, anchor="middle")
text(171, 414, "browser", size=13.5, fill="#475569", anchor="middle")

cloud_icon(171, 600)
text(171, 688, "Yahoo Finance", size=17, weight=700, anchor="middle")
text(171, 710, "market data via yfinance", size=13.5, fill="#475569", anchor="middle")

cube(171, 850, 108, 52, "git", git_glyph)
text(171, 956, "GitHub", size=17, weight=700, anchor="middle")
text(171, 978, "Nimbus code, cloned by", size=13.5, fill="#475569", anchor="middle")
text(171, 996, "each new server", size=13.5, fill="#475569", anchor="middle")

# ---------------- AWS cloud ----------------
panel(334, 128, 1236, 980, stroke="#23324D", width=2)
pill(356, 148, "AWS CLOUD · us-east-1", "#FFF1E0", "#B45309")

# CloudFormation strip
panel(560, 146, 600, 104, fill="#FFF5F9", stroke="#F3B6CF", rx=16)
cube(618, 176, 74, 34, "cfn", stack_glyph)
text(676, 182, "CloudFormation stack  nimbus", size=17, weight=700)
text(676, 205, "scripts/nimbus-stack.yaml creates every resource below.", size=13.5, fill="#475569")
text(676, 225, "A new GitCommit replaces the servers one by one; RDS stays.", size=13.5, fill="#475569")

# CloudWatch strip
panel(1180, 146, 370, 104, fill="#FFF8E6", stroke="#F2C46D", rx=16)
cube(1232, 176, 64, 30, "cw", chart_glyph)
text(1282, 182, "CloudWatch alarms", size=17, weight=700)
text(1282, 205, "target tracking: CPU 60% and", size=13.5, fill="#475569")
text(1282, 225, "1,000 requests per server per min", size=13.5, fill="#475569")

# VPC
panel(404, 270, 1146, 810, fill="#FBFCFF", stroke="#2F6FDC", rx=18, dash="10 6", width=2)
text(432, 302, "VPC  nimbus-vpc", size=17, weight=700, fill="#1D4ED8")
text(590, 302, "10.0.0.0/16", size=15, fill="#1D4ED8", opacity=.8)
text(752, 302, "Availability Zone A", size=14, weight=600, fill="#64748B", anchor="middle")
text(1262, 302, "Availability Zone B", size=14, weight=600, fill="#64748B", anchor="middle")

PUB_Y, PUB_H = 318, 400
PRV_Y, PRV_H = 746, 308
panel(478, PUB_Y, 548, PUB_H, fill="#EEF9F2", stroke="#7CC79A", rx=14)
panel(1046, PUB_Y, 484, PUB_H, fill="#EEF9F2", stroke="#7CC79A", rx=14)
panel(478, PRV_Y, 548, PRV_H, fill="#F0F2FE", stroke="#8EA2E6", rx=14)
panel(1046, PRV_Y, 484, PRV_H, fill="#F7F8FE", stroke="#C3CDF2", rx=14)

text(498, PUB_Y + 30, "Public subnet A", size=15, weight=700, fill="#15803D")
text(632, PUB_Y + 30, "10.0.0.0/24", size=14, fill="#15803D", opacity=.85)
text(1066, PUB_Y + 30, "Public subnet B", size=15, weight=700, fill="#15803D")
text(1200, PUB_Y + 30, "10.0.2.0/24", size=14, fill="#15803D", opacity=.85)
text(618, PRV_Y + 30, "Private subnet A", size=15, weight=700, fill="#3743B5")
text(758, PRV_Y + 30, "10.0.1.0/24", size=14, fill="#3743B5", opacity=.85)
text(1066, PRV_Y + 30, "Private subnet B", size=15, weight=700, fill="#3743B5", opacity=.75)
text(1206, PRV_Y + 30, "10.0.3.0/24", size=14, fill="#3743B5", opacity=.65)
text(1510, PUB_Y + 30, "route 0.0.0.0/0 → internet gateway", size=12.5, fill="#15803D", anchor="end", italic=True)
text(1006, PRV_Y + 52, "route: local only · no internet, no NAT", size=12.5, fill="#3743B5", anchor="end", italic=True)

# Load balancer across both public subnets
add('<rect x="498" y="366" width="1012" height="52" rx="12" fill="#FDE9D6" stroke="#E8891A" stroke-width="1.8"/>')
text(518, 398, "nimbus-alb · Application Load Balancer", size=15.5, weight=700, fill="#9A4A06")
text(1492, 398, "HTTP :80 · sticky sessions · health check /_stcore/health", size=13, fill="#9A4A06", anchor="end")

# Auto Scaling group across both public subnets
panel(492, 436, 1024, 226, fill="none", stroke="#E8891A", rx=14, dash="9 6", width=2)
text(668, 462, "Auto Scaling group  nimbus-app-asg", size=15, weight=700, fill="#9A4A06")
text(668, 482, "min 1 · max 3 · adds / removes servers on the alarms · replaces unhealthy ones",
     size=12.5, fill="#9A4A06")

SRV_X = 600
cube(SRV_X, 532, 96, 46, "ec2", screen_glyph)
text(SRV_X, 630, "nimbus-app · EC2 t2.micro", size=14.5, weight=700, anchor="middle")
text(SRV_X, 648, "Streamlit :8501 · systemd", size=12.5, fill="#475569", anchor="middle")

cube(790, 542, 66, 32, "ebs", disk_glyph)
text(790, 630, "EBS root volume", size=13.5, weight=700, anchor="middle")
text(790, 648, "Markdown copies", size=12.5, fill="#475569", anchor="middle")
add('<path d="M652,560 L 752,560" stroke="#14796F" stroke-width="2.5" stroke-dasharray="3 5" stroke-linecap="round"/>')

cube(1150, 532, 96, 46, None, ghost=True)
text(1150, 630, "more app servers", size=14.5, weight=700, fill="#64748B", anchor="middle")
text(1150, 648, "added under load (up to 3)", size=12.5, fill="#64748B", anchor="middle")
text(1290, 528, "Launch template", size=14, weight=700, fill="#9A4A06")
text(1290, 548, "every server is built the same", size=12.5, fill="#64748B")
text(1290, 566, "way: EC2 user data installs the", size=12.5, fill="#64748B")
text(1290, 584, "pinned commit and starts it", size=12.5, fill="#64748B")

sg_badge(820, 676, "nimbus-alb-sg", "in: 80 from anyone")
sg_badge(1086, 676, "nimbus-app-sg", "in: 8501 from nimbus-alb-sg only")

# RDS
RDS_X, RDS_Y = 620, 846
rds_cylinder(RDS_X, RDS_Y)
text(RDS_X, 974, "nimbus-db · RDS for MySQL", size=16, weight=700, anchor="middle")
text(RDS_X, 994, "db.t3.micro · not publicly accessible", size=13, fill="#475569", anchor="middle")

panel(780, 812, 226, 166, fill="#FFFFFF", stroke="#C3CDF2", rx=12)
text(798, 838, "Database  nimbus", size=14, weight=700, fill="#3743B5")
for i, (name, what) in enumerate((("clients", "client ID, name"), ("discussions", "notes, interests, snapshot"), ("discussion_companies", "price + ratios at the time"))):
    y = 868 + i * 38
    add(f'<rect x="798" y="{y - 12}" width="8" height="8" rx="2" fill="#7F6FD2"/>')
    text(814, y - 4, name, size=13, weight=600)
    text(814, y + 11, what, size=11.5, fill="#64748B")

sg_badge(498, 1014, "nimbus-db-sg", "in: 3306 from nimbus-app-sg only", color="#4338CA", fill="#E9E7FF")

cube(1180, 844, 90, 40, None, ghost=True)
text(1262, 836, "DB subnet group, 2nd AZ", size=14, weight=700, fill="#64748B")
text(1262, 856, "required by RDS; single-AZ", size=13, fill="#64748B")
text(1262, 874, "database, so no standby here", size=13, fill="#64748B")

# Internet gateway on the VPC edge
IGW_X, IGW_Y = 404, 520
cube(IGW_X, IGW_Y - 26, 68, 38, "igw", gate_glyph)
add(f'<rect x="{IGW_X - 42}" y="{IGW_Y + 34}" width="84" height="40" rx="8" fill="#FFFFFF" stroke="#A7E3BF"/>')
text(IGW_X, IGW_Y + 51, "Internet", size=13, weight=700, anchor="middle", fill="#1F7748")
text(IGW_X, IGW_Y + 67, "gateway", size=13, weight=700, anchor="middle", fill="#1F7748")

# ---------------- Flows ----------------
arrow([(262, 300), (330, 300), (330, 470), (362, 470)], label="HTTP :80", label_pos=(286, 290), color="#2A4CA6")
arrow([(370, 500), (250, 600)], color="#2E86B5", both=True, label="HTTPS", label_pos=(240, 540))
arrow([(232, 850), (318, 850), (318, 530), (366, 522)], color="#3F4756", label="git clone", label_pos=(270, 840), dash="7 6")
arrow([(440, 480), (462, 480), (462, 392), (492, 392)], color="#2A4CA6", width=4)
arrow([(SRV_X, 420), (SRV_X, 488)], color="#2A4CA6", width=4)
text(SRV_X - 10, 462, ":8501", size=13, weight=700, fill="#2A4CA6", anchor="end")
arrow([(1150, 420), (1150, 488)], color="#64748B", width=3, dash="7 6")
arrow([(SRV_X, 660), (SRV_X, 818)], color="#6D5BD0", width=4)
text(SRV_X + 12, 735, "MySQL 3306", size=13, weight=700, fill="#6D5BD0")

# ---------------- Footer ----------------
fy = 1132
arrow([(56, fy), (96, fy)], color="#2A4CA6")
text(106, fy + 5, "network traffic", size=13.5, fill="#334155")
arrow([(246, fy), (286, fy)], color="#64748B", width=3, dash="7 6")
text(296, fy + 5, "setup, or only when scaled out", size=13.5, fill="#334155")
lock(540, fy - 9, "#1F4FB8")
text(560, fy + 5, "security group rule (inbound)", size=13.5, fill="#334155")
add(f'<rect x="780" y="{fy - 9}" width="18" height="18" rx="4" fill="#F8FAFC" stroke="#94A3B8" stroke-dasharray="4 3"/>')
text(806, fy + 5, "present only under load", size=13.5, fill="#334155")
text(56, fy + 34, "Status: VPC, EC2 and RDS verified on AWS 25–29 Oct 2026 · load balancer, automatic scale-out / scale-in and self-healing verified 31 Oct 2026",
     size=13.5, weight=600, fill="#475569")
text(56, fy + 58, "No NAT gateway: the database needs no internet access. App servers have no IAM role. Passwords are CloudFormation NoEcho parameters, never in the repository.",
     size=12.5, fill="#64748B")

add("</svg>")
out.insert(DEFS_AT, "<defs>" + "".join(markers.values()) + "</defs>")

target = Path(__file__).resolve().parent.parent / "docs" / "images" / "nimbus-aws-architecture.svg"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text("\n".join(out), encoding="utf-8")
print(f"Wrote {target}")
