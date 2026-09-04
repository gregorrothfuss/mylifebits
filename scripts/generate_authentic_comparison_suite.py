import os, sys
from PIL import Image, ImageDraw, ImageFont

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/quick-galileo'
MEDIA_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408/media_2014_full'
OUT_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408/media_jan2014_real_comparison'
os.makedirs(OUT_DIR, exist_ok=True)

# Typography
FONT_BANNER = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 30)
FONT_BADGE = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 20)

def draw_badge(draw, x1, y1, x2, y2, text, color, bg_color):
    draw.rounded_rectangle([(x1, y1), (x2, y2)], radius=10, outline=color, width=4)
    text_w = draw.textlength(text, font=FONT_BADGE) + 20
    if (x2 - x1) >= text_w + 12:
        bx2 = min(x2 - 6, 1065)
        bx1 = bx2 - text_w
    else:
        bx1 = max(15, min(x1, 1065 - text_w))
        bx2 = bx1 + text_w
    if y1 >= 1540:
        by1 = y1 + 6
        by2 = by1 + 34
    elif 1350 <= y1 <= 1530:
        by1 = max(1310, y1 - 38)
        by2 = by1 + 34
    else:
        if y1 >= 280:
            by1 = y1 - 38
            by2 = by1 + 34
        else:
            by1 = y1 + 6
            by2 = by1 + 34
    draw.rounded_rectangle([(bx1, by1), (bx2, by2)], radius=6, fill=bg_color)
    draw.text((bx1 + 10, by1 + 6), text, font=FONT_BADGE, fill=(255, 255, 255))

ANNOTATIONS = {
    1: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: 189 Loisaida Ave, All day", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    2: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:03 AM (Continuous Overnight)", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: Subway 10:03 AM – 10:21 AM (America/New_York)", "green"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: Timezone Offset Bug (+1h shift to 11:03 AM)", "red"),
        ],
    },
    3: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: 189 Loisaida Ave, All day", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    4: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 5:04 PM (Continuous Overnight)", "green"),
            (30, 1925, 1050, 2105, "GROUND TRUTH: Brooklyn Museum (5:57 PM – 7:39 PM)", "green"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: Time Inversion (Subway 6:04 PM > Museum 5:57 PM)", "red"),
        ],
    },
    5: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 12:23 PM (Continuous Overnight)", "green"),
            (30, 1725, 1050, 1895, "GROUND TRUTH: Walking 19 sec (12:23 PM – 12:23 PM)", "green"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: 19s Walk corrupted into 1h Moving (12:23 PM – 1:23 PM)", "red"),
        ],
    },
    6: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:00 AM (Continuous Overnight)", "green")],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: 1-Hour Timezone Shift (Subway at 11:00 AM)", "red"),
        ],
    },
    7: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:35 AM (Continuous Overnight)", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: Subway 10:35 AM – 11:10 AM -> Google 11:10 AM", "green"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: Subway shifted to 11:35 AM (Google starts at 11:10 AM before arrival!)", "red"),
        ],
    },
    8: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 11:30 AM (Continuous Overnight)", "green"),
            (30, 2240, 1050, 2380, "GROUND TRUTH: Google NYC - 9th Avenue Workplace", "green"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: 1-Hour Timezone Shift (Walking at 12:30 PM)", "red"),
        ],
    },
    9: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:35 AM (Continuous Overnight)", "green")],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: 1-Hour Timezone Shift (Walking at 10:35 AM)", "red"),
        ],
    },
    10: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:37 AM (Continuous Overnight)", "green")],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: 1-Hour Timezone Shift (Walking at 11:37 AM)", "red"),
        ],
    },
    11: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 6:51 PM (Continuous Overnight)", "green"),
            (30, 2085, 1050, 2265, "CANDIDATE MISSING VISIT: Ave A & 6th St (114 min gap, 7:13 PM – 9:07 PM)", "yellow"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 2085, 1050, 2265, "REGRESSION: Fake 2h Subway (Swallowed Missing Visit Gap)", "red"),
        ],
    },
    12: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 11:22 AM · NO SUBWAY", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: Moving 1 hr 14 min (Neighborhood Walk)", "green"),
        ],
        'cleaned': [
            (560, 680, 1040, 890, "REGRESSION: Fake Subway Route across East River", "red"),
            (280, 1400, 520, 1490, "REGRESSION: Fake Subway Stat (Prod has NO Subway)", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Fake Subway Card (Prod has NO Subway)", "red"),
            (30, 1725, 1050, 1895, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
        ],
    },
    13: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:11 AM (Continuous Overnight)", "green")],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: 1-Hour Timezone Shift (Walking at 11:11 AM)", "red"),
        ],
    },
    14: {
        'baseline': [
            (40, 420, 430, 480, "GROUND TRUTH: Google NYC Workplace Pin", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:58 AM (Continuous Overnight)", "green"),
            (30, 1925, 1050, 2105, "GROUND TRUTH: Google NYC - 9th Avenue", "green"),
        ],
        'cleaned': [
            (90, 410, 590, 480, "HALLUCINATION: TAO Downtown Pin", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 2085, 1050, 2265, "HALLUCINATION: TAO Downtown replacing Workplace", "red"),
        ],
    },
    15: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:18 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    16: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:30 AM (Continuous Overnight)", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: Walking 12 sec (9:30 AM – 9:30 AM)", "green"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: 12s Walk corrupted into 1h Moving (9:30 AM – 10:30 AM)", "red"),
        ],
    },
    17: {
        'baseline': [
            (250, 800, 950, 1220, "GROUND TRUTH: Authentic Belt Pkwy Taxi Route", "green"),
            (580, 1400, 820, 1490, "GROUND TRUTH: Taxi 17 mi · 1 hr 36 min", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:29 AM (Continuous Overnight)", "green"),
        ],
        'cleaned': [
            (80, 500, 950, 1150, "REGRESSION: Straight Line Chord (Shit Path)", "red"),
            (100, 1400, 320, 1490, "REGRESSION: Walking 13 mi replacing Taxi", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
        ],
    },
    18: {
        'baseline': [
            (80, 500, 450, 1150, "GROUND TRUTH: Winding Taxi Route & America/La_Paz UTC-4", "green"),
            (100, 1400, 280, 1490, "GROUND TRUTH: Taxi 4 mi · 31 min", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: El Alto Airport (4:32 PM – 5:00 PM)", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: In a taxi 3.9 mi · 31 min (5:00 PM – 5:31 PM)", "green"),
        ],
        'cleaned': [
            (80, 700, 950, 1050, "REGRESSION: Straight Line Chord", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Timezone Offset Error (3:32 PM, 1h early)", "red"),
            (30, 1725, 1050, 1895, "REGRESSION: Walking 4.2 mi at 8.2 mph replacing Taxi", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: Time Went Backwards (4:31 PM < 5:31 PM)", "red"),
        ],
    },
    19: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:35 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    20: {
        'baseline': [
            (60, 1400, 560, 1490, "GROUND TRUTH: Driving 68 mi · Boat 12 mi · NO SUBWAY", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 6:00 AM (Continuous Overnight)", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: Driving 52 mi · 3 hr 15 min", "green"),
        ],
        'cleaned': [
            (720, 1400, 920, 1490, "REGRESSION: Fake Subway in Bolivia (11 mi)", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: Generic Moving replacing Driving", "red"),
        ],
    },
    21: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 8:00 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    22: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:00 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    23: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:30 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    24: {
        'baseline': [
            (60, 1400, 420, 1490, "GROUND TRUTH: Driving 105 mi · NO SUBWAY", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 7:00 AM (Continuous Overnight)", "green"),
        ],
        'cleaned': [
            (740, 1400, 920, 1490, "REGRESSION: Fake Subway in Andean National Park", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
        ],
    },
    25: {
        'baseline': [
            (60, 1400, 240, 1490, "GROUND TRUTH: Driving 44 mi · 1 hr 43 min", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:00 AM (Continuous Overnight)", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: Driving 44 mi · 1 hr 43 min", "green"),
            (30, 2085, 1050, 2265, "GROUND TRUTH: Pizzería El Charrúa (Authentic Lunch Visit)", "green"),
        ],
        'cleaned': [
            (60, 1400, 240, 1490, "REGRESSION: Generic Moving replacing Driving", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: Generic Moving replacing Driving", "red"),
            (30, 2085, 1050, 2265, "REGRESSION: Swallowed Lunch Visit (Merged into Hotel)", "red"),
        ],
    },
    26: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:15 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    27: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:00 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    28: {
        'baseline': [
            (380, 1400, 620, 1490, "GROUND TRUTH: Driving 17 mi · Atacama · NO SUBWAY", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 12:36 AM (Continuous Overnight)", "green"),
        ],
        'cleaned': [
            (360, 1400, 580, 1490, "REGRESSION: Fake Subway in Atacama Desert (17 mi)", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
        ],
    },
    29: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 11:30 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
    30: {
        'baseline': [
            (380, 1400, 620, 1490, "GROUND TRUTH: Driving 48 mi · NO SUBWAY", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:00 AM (Continuous Overnight)", "green"),
        ],
        'cleaned': [
            (440, 1400, 640, 1490, "REGRESSION: Fake Subway (13 mi 42 min)", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red"),
        ],
    },
    31: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 8:45 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split (Left at 12:00 AM)", "red")],
    },
}

print("[*] Generating 100% Authentic Device Side-by-Side Comparison for January 2014...")

for day in range(1, 32):
    dt_str = f"2014-01-{day:02d}"
    b_path = os.path.join(MEDIA_DIR, f"{dt_str}_baseline.png")
    c_path = os.path.join(MEDIA_DIR, f"{dt_str}_cleaned.png")
    
    if not os.path.exists(b_path) or not os.path.exists(c_path):
        print(f"Skipping {dt_str}: file missing")
        continue
        
    img_b = Image.open(b_path).convert('RGB')
    img_c = Image.open(c_path).convert('RGB')
    
    draw_b = ImageDraw.Draw(img_b)
    draw_c = ImageDraw.Draw(img_c)
    
    annot = ANNOTATIONS.get(day, {})
    
    # Draw badges directly on authentic screenshot coordinates
    for item in annot.get('cleaned', []):
        x1, y1, x2, y2, text, col_type = item
        color = (239, 68, 68) if col_type == 'red' else ((234, 179, 8) if col_type == 'yellow' else (34, 197, 94))
        draw_badge(draw_c, x1, y1, x2, y2, text, color, color)
        
    for item in annot.get('baseline', []):
        x1, y1, x2, y2, text, col_type = item
        color = (34, 197, 94) if col_type == 'green' else ((234, 179, 8) if col_type == 'yellow' else (239, 68, 68))
        draw_badge(draw_b, x1, y1, x2, y2, text, color, color)
        
    total_h = 2470
    panel = Image.new('RGB', (2240, total_h), (241, 243, 244))
    
    # Left: Prod Baseline
    p_left = Image.new('RGB', (1080, total_h), (255, 255, 255))
    p_left.paste(img_b, (0, 70))
    d_pl = ImageDraw.Draw(p_left)
    d_pl.rectangle([(0, 0), (1080, 70)], fill=(30, 41, 59))
    d_pl.text((540, 35), "PROD BASELINE (AUTHENTIC GROUND TRUTH ON DEVICE)", font=FONT_BANNER, fill=(255, 255, 255), anchor='mm')
    
    # Right: Cleaned Run
    p_right = Image.new('RGB', (1080, total_h), (255, 255, 255))
    p_right.paste(img_c, (0, 70))
    d_pr = ImageDraw.Draw(p_right)
    d_pr.rectangle([(0, 0), (1080, 70)], fill=(153, 27, 27))
    d_pr.text((540, 35), "CLEANED RUN (ANOMALIES & REGRESSIONS HIGHLIGHTED)", font=FONT_BANNER, fill=(255, 255, 255), anchor='mm')
    
    panel.paste(p_left, (0, 0))
    panel.paste(p_right, (1160, 0))
    d_p = ImageDraw.Draw(panel)
    d_p.line([(1120, 0), (1120, total_h)], fill=(203, 213, 225), width=4)
    
    out_file = os.path.join(OUT_DIR, f"{dt_str}_comparison.png")
    panel.save(out_file)
    print(f"  [{day:2d}/31] Saved authentic {dt_str}_comparison.png ({panel.size[0]}x{panel.size[1]})")

print("[✓] ALL 31 AUTHENTIC DEVICE SIDE-BY-SIDE SCREENSHOTS GENERATED!")
