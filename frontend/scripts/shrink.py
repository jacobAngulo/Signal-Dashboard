import os
import re

src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', '..', 'design', 'dashboard-snapshot.html')
h = open(src).read()
before = len(h)

# Only SVG geometry gets rounded. A blanket pass over the file would also hit
# the oklch() channels in the stylesheet (changing every colour) and the
# probabilities and returns rendered in the tables (changing the data).
GEOM = ('x', 'y', 'x1', 'y1', 'x2', 'y2', 'cx', 'cy', 'r', 'rx', 'ry',
        'width', 'height', 'd', 'points', 'offset')

def round_attr(m):
    name, val = m.group(1), m.group(2)
    if name not in GEOM:
        return m.group(0)
    val = re.sub(r'\d+\.\d{2,}',
                 lambda n: ('%.1f' % float(n.group(0))).rstrip('0').rstrip('.'), val)
    return '%s="%s"' % (name, val)

def in_svg(m):
    return re.sub(r'\b([a-zA-Z-]+)="([^"]*)"', round_attr, m.group(0))

h = re.sub(r'<svg.*?</svg>', in_svg, h, flags=re.S)

# Whitespace between tags is never significant here -- every text node the app
# renders sits inside an element, so collapsing tag gaps changes no layout.
h = re.sub(r'>\s+<', '><', h)

open(src, 'w').write(h)
print('%.0f KB -> %.0f KB  (-%d%%)' % (before/1024, len(h)/1024, 100 - 100*len(h)//before))
