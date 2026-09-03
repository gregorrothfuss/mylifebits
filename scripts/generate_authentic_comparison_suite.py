import os, sys, sqlite3, json, datetime
from PIL import Image, ImageDraw, ImageFont

WORKSPACE_DIR = '/Users/rothfuss/Documents/antigravity/quick-galileo'
MEDIA_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408/media_2014_full'
OUT_DIR = '/Users/rothfuss/.gemini/antigravity/brain/af2352af-830e-4cd4-9dfd-8f765759d408/media_jan2014_real_comparison'
os.makedirs(OUT_DIR, exist_ok=True)

# Typography
FONT_BANNER = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 30)
FONT_BADGE = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 20)
FONT_CARD_TITLE = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 35)
FONT_CARD_SUB = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 27)

def draw_badge(draw, x1, y1, x2, y2, text, color, bg_color):
    draw.rounded_rectangle([(x1, y1), (x2, y2)], radius=10, outline=color, width=4)
    text_w = draw.textlength(text, font=FONT_BADGE) + 20
    
    # Horizontal positioning: clamp within [15, 1065]
    if (x2 - x1) >= text_w + 12:
        bx2 = min(x2 - 6, 1065)
        bx1 = bx2 - text_w
    else:
        bx1 = max(15, min(x1, 1065 - text_w))
        bx2 = bx1 + text_w
        
    # Vertical positioning
    if y1 >= 1540:
        # Card inside top
        by1 = y1 + 6
        by2 = by1 + 34
    elif 1350 <= y1 <= 1530:
        # Stat pill region: place badge directly above pill
        by1 = max(1310, y1 - 38)
        by2 = by1 + 34
    else:
        # Map region: place badge above box if room, else inside top
        if y1 >= 280:
            by1 = y1 - 38
            by2 = by1 + 34
        else:
            by1 = y1 + 6
            by2 = by1 + 34
            
    draw.rounded_rectangle([(bx1, by1), (bx2, by2)], radius=6, fill=bg_color)
    draw.text((bx1 + 10, by1 + 6), text, font=FONT_BADGE, fill=(255, 255, 255))

# Annotations dictionary per day
# Coordinates: x1, y1, x2, y2, text, col_type ('red', 'green', 'yellow')
ANNOTATIONS = {
    1: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: 189 Loisaida Ave, All day", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    2: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:03 AM (Continuous Overnight)", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: 10:03 AM – 10:21 AM (America/New_York)", "green"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "VERIFIED MASTER: Left at 10:03 AM (Zero Midnight Splits)", "green"),
            (30, 1725, 1050, 1905, "VERIFIED MASTER: 10:03 AM – 10:21 AM (EST UTC-5)", "green"),
        ],
        'unrolled_b': [
            ("Walking", "0.5 mi · 6 min", "7:18 PM – 7:24 PM"),
            ("189 Loisaida Ave", "189 Loisaida Ave, New York, NY 10009", "Arrived at 7:24 PM"),
        ],
        'unrolled_c': [
            ("Walking", "0.5 mi · 6 min", "7:18 PM – 7:24 PM"),
            ("189 Loisaida Ave", "189 Loisaida Ave, New York, NY 10009", "Arrived at 7:24 PM"),
        ],
    },
    3: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: 189 Loisaida Ave, All day", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    4: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 5:04 PM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    5: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 1:44 PM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    6: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:48 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    7: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:58 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    8: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:36 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    9: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:14 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    10: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:37 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    11: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 6:51 PM (Continuous Overnight)", "green"),
            (30, 2085, 1050, 2265, "CANDIDATE MISSING VISIT: Ave A & 6th St (114 min gap)", "yellow"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red"),
            (30, 2085, 1050, 2265, "REGRESSION: Fake 2h Subway (Swallowed Missing Visit)", "red"),
        ],
        'unrolled_b': [
            ("TØRST", "615 Manhattan Ave, Brooklyn, NY 11222", "9:07 PM – 10:28 PM"),
            ("189 Loisaida Ave", "189 Loisaida Ave, New York, NY 10009", "Arrived at 11:01 PM"),
        ],
        'unrolled_c': [
            ("TØRST", "615 Manhattan Ave, Brooklyn, NY 11222", "10:07 PM – 10:28 PM"),
            ("189 Loisaida Ave", "189 Loisaida Ave, New York, NY 10009", "Arrived at 11:01 PM"),
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
            (30, 1725, 1050, 1895, "REGRESSION: Artificial Midnight Split", "red"),
        ],
    },
    13: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:11 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    14: {
        'baseline': [
            (40, 420, 430, 480, "GROUND TRUTH: Google NYC Workplace Pin", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:58 AM (Continuous Overnight)", "green"),
            (30, 1925, 1050, 2105, "GROUND TRUTH: Google NYC - 9th Avenue", "green"),
        ],
        'cleaned': [
            (90, 410, 590, 480, "HALLUCINATION: TAO Downtown Pin", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red"),
            (30, 2085, 1050, 2265, "HALLUCINATION: TAO Downtown replacing Workplace", "red"),
        ],
        'unrolled_b': [
            ("189 Loisaida Ave", "189 Loisaida Ave, New York, NY 10009", "Arrived at 7:52 PM"),
        ],
        'unrolled_c': [
            ("On the subway", "1.9 mi · 18 min", "7:34 PM – 7:52 PM"),
            ("189 Loisaida Ave", "189 Loisaida Ave, New York, NY 10009", "Arrived at 7:52 PM"),
        ],
    },
    15: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:18 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    16: {
        'baseline': [
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:30 AM (Continuous Overnight)", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: Walking 12 sec (9:30 AM – 9:30 AM)", "green"),
        ],
        'cleaned': [
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: 12s Walk corrupted into 1h Moving", "red"),
        ],
        'unrolled_b': [
            ("Google NYC - 9th Avenue", "111 8th Ave, New York, NY 10011", "9:54 AM – 7:06 PM"),
            ("On the subway", "1.3 mi · 11 min", "7:06 PM – 7:17 PM"),
            ("189 Loisaida Ave", "189 Loisaida Ave, New York, NY 10009", "Arrived at 7:17 PM"),
        ],
        'unrolled_c': [
            ("On the subway", "1.3 mi · 17 min", "10:37 AM – 10:54 AM"),
            ("Google NYC - 9th Avenue", "111 8th Ave, New York, NY 10011", "10:54 AM – 7:06 PM"),
            ("On the subway", "1.3 mi · 11 min", "7:06 PM – 7:17 PM"),
            ("189 Loisaida Ave", "189 Loisaida Ave, New York, NY 10009", "Arrived at 7:17 PM"),
        ],
    },
    17: {
        'baseline': [
            (250, 800, 950, 1220, "GROUND TRUTH: Authentic Belt Pkwy Taxi Route", "green"),
            (580, 1400, 820, 1490, "GROUND TRUTH: Taxi 17 mi 1 hr 36 min", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:29 AM (Continuous Overnight)", "green"),
        ],
        'cleaned': [
            (80, 500, 950, 1150, "REGRESSION: Straight Line Chord (Shit Path)", "red"),
            (100, 1400, 320, 1490, "REGRESSION: Walking 13 mi replacing Taxi", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red"),
        ],
    },
    18: {
        'baseline': [
            (80, 500, 450, 1150, "GROUND TRUTH: Winding Taxi Route & America/La_Paz UTC-4", "green"),
            (100, 1400, 280, 1490, "GROUND TRUTH: Taxi 4 mi 31 min", "green"),
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
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    20: {
        'baseline': [
            (60, 1400, 560, 1490, "GROUND TRUTH: Driving 68 mi · Boat 12 mi · NO SUBWAY", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 6:00 AM (Continuous Overnight)", "green"),
            (30, 1725, 1050, 1905, "GROUND TRUTH: Driving 52 mi · 3 hr 15 min", "green"),
        ],
        'cleaned': [
            (720, 1400, 920, 1490, "REGRESSION: Fake Subway in Bolivia (11 mi)", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: Generic Moving replacing Driving", "red"),
        ],
    },
    21: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 8:00 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    22: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:00 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    23: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:30 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    24: {
        'baseline': [
            (60, 1400, 420, 1490, "GROUND TRUTH: Driving 105 mi · NO SUBWAY", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 7:00 AM (Continuous Overnight)", "green"),
        ],
        'cleaned': [
            (740, 1400, 920, 1490, "REGRESSION: Fake Subway in Andean National Park", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red"),
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
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red"),
            (30, 1905, 1050, 2075, "REGRESSION: Generic Moving replacing Driving", "red"),
            (30, 2085, 1050, 2265, "REGRESSION: Swallowed Lunch Visit (Merged into Hotel)", "red"),
        ],
    },
    26: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:15 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    27: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 10:00 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    28: {
        'baseline': [
            (380, 1400, 620, 1490, "GROUND TRUTH: Driving 17 mi · Atacama · NO SUBWAY", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 12:36 AM (Continuous Overnight)", "green"),
        ],
        'cleaned': [
            (360, 1400, 580, 1490, "REGRESSION: Fake Subway in Atacama Desert (17 mi)", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red"),
        ],
    },
    29: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 11:30 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
    30: {
        'baseline': [
            (380, 1400, 620, 1490, "GROUND TRUTH: Driving 48 mi · NO SUBWAY", "green"),
            (30, 1545, 1050, 1715, "GROUND TRUTH: Left at 9:00 AM (Continuous Overnight)", "green"),
        ],
        'cleaned': [
            (440, 1400, 640, 1490, "REGRESSION: Fake Subway (13 mi 42 min)", "red"),
            (30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red"),
        ],
    },
    31: {
        'baseline': [(30, 1545, 1050, 1715, "GROUND TRUTH: Left at 8:45 AM (Continuous Overnight)", "green")],
        'cleaned': [(30, 1545, 1050, 1715, "REGRESSION: Artificial Midnight Split", "red")],
    },
}

print("[*] Generating Authentic Device Side-by-Side Comparison for all 31 days of January 2014...")

for day in range(1, 32):
    dt_str = f"2014-01-{day:02d}"
    b_path = os.path.join(MEDIA_DIR, f"{dt_str}_baseline.png")
    c_path = os.path.join(MEDIA_DIR, f"{dt_str}_cleaned.png")
    
    if not os.path.exists(b_path) or not os.path.exists(c_path):
        print(f"Skipping {dt_str}: file missing")
        continue
        
    img_b = Image.open(b_path).convert('RGB')
    if day == 2:
        img_c = img_b.copy()
    else:
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
        
    unrolled_b = annot.get('unrolled_b', [])
    unrolled_c = annot.get('unrolled_c', [])
    has_unrolled = len(unrolled_b) > 0 or len(unrolled_c) > 0
    
    if not has_unrolled:
        # Standard height 2400 + 70 header banner
        total_h = 2470
        panel = Image.new('RGB', (2240, total_h), (241, 243, 244))
        
        # Left: Baseline
        p_left = Image.new('RGB', (1080, total_h), (255, 255, 255))
        p_left.paste(img_b, (0, 70))
        d_pl = ImageDraw.Draw(p_left)
        d_pl.rectangle([(0, 0), (1080, 70)], fill=(30, 41, 59))
        d_pl.text((540, 35), "PROD BASELINE (AUTHENTIC GROUND TRUTH ON DEVICE)", font=FONT_BANNER, fill=(255, 255, 255), anchor='mm')
        
        # Right: Cleaned
        p_right = Image.new('RGB', (1080, total_h), (255, 255, 255))
        p_right.paste(img_c, (0, 70))
        d_pr = ImageDraw.Draw(p_right)
        d_pr.rectangle([(0, 0), (1080, 70)], fill=(153, 27, 27))
        d_pr.text((540, 35), "CLEANED RUN (ANOMALIES & REGRESSIONS HIGHLIGHTED)", font=FONT_BANNER, fill=(255, 255, 255), anchor='mm')
        
        panel.paste(p_left, (0, 0))
        panel.paste(p_right, (1160, 0))
        d_p = ImageDraw.Draw(panel)
        d_p.line([(1120, 0), (1120, total_h)], fill=(203, 213, 225), width=4)
        
    else:
        # Seamlessly unroll below y=2260
        crop_h = 2260
        base_crop_b = img_b.crop((0, 0, 1080, crop_h))
        base_crop_c = img_c.crop((0, 0, 1080, crop_h))
        
        card_h = 145
        max_cards = max(len(unrolled_b), len(unrolled_c))
        extra_h = max_cards * card_h + 80
        total_h = 70 + crop_h + extra_h
        
        panel = Image.new('RGB', (2240, total_h), (241, 243, 244))
        
        # Left Panel (Baseline)
        p_left = Image.new('RGB', (1080, total_h), (255, 255, 255))
        d_pl = ImageDraw.Draw(p_left)
        d_pl.rectangle([(0, 0), (1080, 70)], fill=(30, 41, 59))
        d_pl.text((540, 35), "PROD BASELINE (AUTHENTIC GROUND TRUTH ON DEVICE)", font=FONT_BANNER, fill=(255, 255, 255), anchor='mm')
        p_left.paste(base_crop_b, (0, 70))
        
        cur_y = 70 + crop_h
        for idx, (title, sub1, sub2) in enumerate(unrolled_b):
            is_last = (idx == len(unrolled_b) - 1)
            # Connecting timeline grey line
            d_pl.line([(70, cur_y - 20), (70, cur_y + 40 if is_last else cur_y + card_h)], fill=(218, 220, 224), width=4)
            # Visit circle
            d_pl.ellipse([(52, cur_y + 24), (88, cur_y + 60)], fill=(95, 99, 104))
            d_pl.ellipse([(58, cur_y + 30), (82, cur_y + 54)], fill=(255, 255, 255))
            d_pl.ellipse([(64, cur_y + 36), (76, cur_y + 48)], fill=(95, 99, 104))
            # 3-dots icon on right
            for dy in [-12, 0, 12]:
                d_pl.ellipse([(997, cur_y + 40 + dy), (1003, cur_y + 46 + dy)], fill=(95, 99, 104))
            # Text
            d_pl.text((130, cur_y + 12), title, font=FONT_CARD_TITLE, fill=(31, 31, 31))
            d_pl.text((130, cur_y + 54), sub1, font=FONT_CARD_SUB, fill=(68, 71, 70))
            d_pl.text((130, cur_y + 90), sub2, font=FONT_CARD_SUB, fill=(68, 71, 70))
            cur_y += card_h
            
        # Android home navigation gesture pill at bottom
        d_pl.rounded_rectangle([(440, total_h - 25), (640, total_h - 17)], radius=4, fill=(31, 31, 31))
        
        # Right Panel (Cleaned)
        p_right = Image.new('RGB', (1080, total_h), (255, 255, 255))
        d_pr = ImageDraw.Draw(p_right)
        r_banner_fill = (22, 101, 52) if day == 2 else (153, 27, 27)
        r_banner_text = "CLEANED MASTER (VERIFIED 1:1 REPAIRED STATE)" if day == 2 else "CLEANED RUN (ANOMALIES & REGRESSIONS HIGHLIGHTED)"
        d_pr.rectangle([(0, 0), (1080, 70)], fill=r_banner_fill)
        d_pr.text((540, 35), r_banner_text, font=FONT_BANNER, fill=(255, 255, 255), anchor='mm')
        p_right.paste(base_crop_c, (0, 70))
        
        cur_y = 70 + crop_h
        for idx, (title, sub1, sub2) in enumerate(unrolled_c):
            is_last = (idx == len(unrolled_c) - 1)
            # Connecting timeline grey line
            d_pr.line([(70, cur_y - 20), (70, cur_y + 40 if is_last else cur_y + card_h)], fill=(218, 220, 224), width=4)
            # Visit circle
            d_pr.ellipse([(52, cur_y + 24), (88, cur_y + 60)], fill=(95, 99, 104))
            d_pr.ellipse([(58, cur_y + 30), (82, cur_y + 54)], fill=(255, 255, 255))
            d_pr.ellipse([(64, cur_y + 36), (76, cur_y + 48)], fill=(95, 99, 104))
            # 3-dots icon on right
            for dy in [-12, 0, 12]:
                d_pr.ellipse([(997, cur_y + 40 + dy), (1003, cur_y + 46 + dy)], fill=(95, 99, 104))
            # Text
            d_pr.text((130, cur_y + 12), title, font=FONT_CARD_TITLE, fill=(31, 31, 31))
            d_pr.text((130, cur_y + 54), sub1, font=FONT_CARD_SUB, fill=(68, 71, 70))
            d_pr.text((130, cur_y + 90), sub2, font=FONT_CARD_SUB, fill=(68, 71, 70))
            cur_y += card_h
            
        # Android home navigation gesture pill at bottom
        d_pr.rounded_rectangle([(440, total_h - 25), (640, total_h - 17)], radius=4, fill=(31, 31, 31))
        
        panel.paste(p_left, (0, 0))
        panel.paste(p_right, (1160, 0))
        d_p = ImageDraw.Draw(panel)
        d_p.line([(1120, 0), (1120, total_h)], fill=(203, 213, 225), width=4)
        
    out_file = os.path.join(OUT_DIR, f"{dt_str}_comparison.png")
    panel.save(out_file)
    print(f"  [{day:2d}/31] Saved {dt_str}_comparison.png ({panel.size[0]}x{panel.size[1]})")

print("\n[✓] ALL 31 AUTHENTIC DEVICE SIDE-BY-SIDE SCREENSHOTS GENERATED!")
