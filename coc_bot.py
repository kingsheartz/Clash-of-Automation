"""
Clash of Clans - Event Attack Automation v3
Platform: Windows native (Google Play Games)

HOW CARD DETECTION WORKS:
  1. Capture the troop bar strip (TROOP_BAR_REGION)
  2. Slide each template across the bar — the bar is center-aligned and
     grows outward with army size, so slot X positions are never fixed
  3. Cluster peaks, crop each card, portrait-match to confirm identity
  4. Deploy until card greys out — never use OCR counts

DEPLOY LOGIC (fully dynamic — any army with templates/ PNGs):
  - Heroes: once each, by template name
  - Lightning: zap air defences first, then eagle artillery (templates/defence/)
  - Healer: deploys immediately after archer queen, left of her spot
  - Troops: deploy until disabled; rage mid-funnel (after lightning)
  - Freeze: drop on defenses until disabled
"""

import cv2
import numpy as np
import pytesseract
import pydirectinput
import pyautogui
import time
import re
import sys
import os
import glob
from PIL import ImageGrab, Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

MIN_GOLD   = 1_000_000
MIN_ELIXIR = 500_000

MATCH_CONFIDENCE = 0.75
DEFENCE_MATCH_CONFIDENCE = 0.38
DEFENCE_EDGE_CONFIDENCE = 0.32
DEFENCE_MATCH_SCALES = [
    0.45, 0.55, 0.65, 0.75, 0.85, 0.95,
    1.05, 1.20, 1.40, 1.60, 1.85, 2.10,
]
DEFENCE_MIN_DISTANCE = 60
CARD_MATCH_CONFIDENCE = 0.40
CARD_MATCH_MARGIN = 0.02   # best template must beat 2nd place in same slot
CARD_SCAN_MIN_SCORE = 0.48 # minimum peak score to accept a bar position

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_ROOT = os.path.join(SCRIPT_DIR, "templates")
TEMPLATE_DIRS = {
    "TROOP": os.path.join(TEMPLATE_ROOT, "troops"),
    "HERO":  os.path.join(TEMPLATE_ROOT, "heroes"),
    "SPELL": os.path.join(TEMPLATE_ROOT, "spells"),
}
DEFENCE_DIR = os.path.join(TEMPLATE_ROOT, "defence")

# Set True to save OCR/card debug images and verbose scan logs
DEBUG = False

_CARD_TEMPLATES = None

# ── Loot OCR ─────────────────────────────────────────────────
GOLD_REGION   = (238, 246, 328, 72)
ELIXIR_REGION = (235, 326, 323, 65)

# ── Troop Bar ─────────────────────────────────────────────────
# Wide capture band — cards are found dynamically (center-aligned bar).
# Format: (screen_left, screen_top, capture_width, capture_height)
TROOP_BAR_REGION = (232, 1467, 2748, 210)

CARD_WIDTH     = 185
CARD_HEIGHT    = 210
CARD_CENTER_Y  = 105   # vertical center within card
CARD_SLOT_GAP  = 0.55  # min separation between peaks, as fraction of CARD_WIDTH

# Screen Y of card centers (TROOP_BAR_REGION top + card center)
CARD_SCREEN_Y  = 1467 + CARD_CENTER_Y  # = 1572

# ── Deploy Points ─────────────────────────────────────────────
# Outer border of enemy base — troops/heroes deployed here
DEPLOY_POINTS = [
    (1920, 1387), (2129, 1209), (2396, 1040), (2510, 896),
    (2448, 732),  (2258, 556),  (2044, 411),  (1798, 246),
    (1279, 246),  (1096, 352),  (944,  474),  (805,  552),
    (641,  751),  (567,  870),  (669,  999),  (787,  1082),
    (939,  1183), (990,  1238), (1123, 1316), (1304, 1415),
    (1819, 1425), (2001, 1284), (2048, 1244), (2173, 1153),
]

# Per-hero deploy points on the base border
HERO_DEPLOY_POINTS = {
    "barbarian_king": DEPLOY_POINTS[0],
    "grand_warden":   DEPLOY_POINTS[8],
    "archer_queen":   DEPLOY_POINTS[16],
}

# Healer drops just left of the archer queen deploy point
HEALER_LEFT_OFFSET = 90

# Base area to search for defence buildings (above the troop bar)
BASE_SEARCH_REGION = (280, 160, 2320, 1280)

# Lightning: 2 zaps per detected air defence, then cycle targets
LIGHTNING_ZAPS_PER_AD = 2
LIGHTNING_ZAPS_EAGLE = 4
AIR_DEFENCE_MATCH_CONFIDENCE = 0.40

# Fallback when template matching finds nothing on screen
LIGHTNING_POINTS = [
    (1410, 795), (1415, 800),   # AD 1
    (1495, 855), (1500, 860),   # AD 2
    (1580, 915), (1585, 920),   # AD 3
    (1665, 975), (1670, 980),   # AD 4
]

# Rage → drop inside the funnel (not on the outer deploy ring)
RAGE_CAST_POINT = (1680, 1020)
RAGE_FUNNEL_POINTS = [
    (1920, 1387),   # deploy edge — where troops land
    (1850, 1250),   # just inside border
    (1750, 1100),   # troop blob as they walk in
]
RAGE_DEPLOY_AFTER_CLICKS = 6   # cast rage after this many troop clicks
RAGE_CAST_DELAY = 1.0          # troops already walking — shorter wait

# Freeze → any defense inside the red-border zone; cycles if count > 1
FREEZE_POINTS = [
    (1360, 920), (1524, 784), (1668, 952), (1454, 1005),
    (1809, 779), (1686, 651), (1294, 827), (1603, 704),
    (1750, 700), (1380, 820), (1550, 880), (1620, 620),
]

# Fallback for unknown spell slots
SPELL_POINTS = FREEZE_POINTS

# Safe failsafe exclusion zone — don't move mouse within this margin of screen edge
FAILSAFE_MARGIN = 50

BATTLE_POLL_INTERVAL = 0.25   # how often to check for battle end
RETURN_HOME_CLICK_DELAY = 0.5

# Victory screen UI — stable crops from battle_end.png (loot numbers vary per attack)
VICTORY_BANNER_TEMPLATE = os.path.join(TEMPLATE_ROOT, "victory_banner.png")
RETURN_HOME_BTN_TEMPLATE = os.path.join(TEMPLATE_ROOT, "return_home.png")
BATTLE_UI_CONFIDENCE = 0.60
BATTLE_UI_SCALES = [0.85, 0.95, 1.0, 1.05, 1.15]

# Fallback click when victory banner is visible
RETURN_HOME_POINT = (1440, 1580)

# ─────────────────────────────────────────────────────────────
# SAFETY
# ─────────────────────────────────────────────────────────────

pyautogui.FAILSAFE    = True
pyautogui.PAUSE       = 0.05
pydirectinput.FAILSAFE = True
pydirectinput.PAUSE   = 0.05


def safe_coords(x, y):
    """Clamp coordinates away from screen corners to avoid failsafe."""
    sw, sh = pyautogui.size()
    x = max(FAILSAFE_MARGIN, min(x, sw - FAILSAFE_MARGIN))
    y = max(FAILSAFE_MARGIN, min(y, sh - FAILSAFE_MARGIN))
    return x, y


# ─────────────────────────────────────────────────────────────
# CORE HELPERS
# ─────────────────────────────────────────────────────────────

def screenshot():
    img = ImageGrab.grab()
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _defence_gray(img):
    """Contrast-normalised grey — less sensitive to AD level colours."""

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _defence_edges(gray):
    """Rocket + base silhouette — works across AD levels."""

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.Canny(blur, 35, 110)


def _collect_defence_peaks(
    region,
    template,
    tw,
    th,
    left,
    top,
    passes,
):
    """Run one or more match passes and collect all peaks above threshold."""

    peaks = []

    for matcher, min_score in passes:
        work = matcher.copy()
        while True:
            _, score, _, loc = cv2.minMaxLoc(work)
            if score < min_score:
                break

            peaks.append((
                left + loc[0] + tw // 2,
                top + loc[1] + th // 2,
                float(score),
            ))

            x1, y1 = loc[0], loc[1]
            work[y1:y1 + th, x1:x1 + tw] = 0

    return peaks


def find_defence_matches(template_path, confidence=DEFENCE_MATCH_CONFIDENCE):
    """
    Find defences by structure (edges) and colour across many scales.
    Edge matching tolerates different air-defence level palettes.
    """

    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        print(f"  [!] Missing template: {template_path}")
        return []

    screen = screenshot()
    left, top, rw, rh = BASE_SEARCH_REGION
    region = screen[top:top + rh, left:left + rw]
    region_gray = _defence_gray(region)
    region_edge = _defence_edges(region_gray)

    candidates = []

    for scale in DEFENCE_MATCH_SCALES:
        tw = max(16, int(template.shape[1] * scale))
        th = max(16, int(template.shape[0] * scale))
        if th > region.shape[0] or tw > region.shape[1]:
            continue

        scaled = cv2.resize(template, (tw, th))
        t_edge = _defence_edges(_defence_gray(scaled))

        passes = (
            (cv2.matchTemplate(region, scaled, cv2.TM_CCOEFF_NORMED), confidence),
            (cv2.matchTemplate(region_edge, t_edge, cv2.TM_CCOEFF_NORMED),
                DEFENCE_EDGE_CONFIDENCE),
        )
        candidates.extend(
            _collect_defence_peaks(
                region, scaled, tw, th, left, top, passes
            )
        )

    candidates.sort(key=lambda c: c[2], reverse=True)

    accepted = []
    for cx, cy, score in candidates:
        if any(
            abs(cx - ax) < DEFENCE_MIN_DISTANCE
            and abs(cy - ay) < DEFENCE_MIN_DISTANCE
            for ax, ay, _ in accepted
        ):
            continue
        accepted.append((cx, cy, score))

    if DEBUG and not accepted:
        cv2.imwrite("debug_base_search.png", region)
    elif DEBUG and accepted:
        dbg = region.copy()
        for cx, cy, score in accepted:
            cv2.circle(
                dbg,
                (cx - left, cy - top),
                20,
                (0, 255, 0),
                2,
            )
        cv2.imwrite("debug_air_defence.png", dbg)

    return accepted


def resolve_lightning_targets():
    """
    Build zap points from template-matched air defences.
    Searches BASE_SEARCH_REGION at 12 scales (colour + edges).
    Falls back to calibrated LIGHTNING_POINTS only when nothing matches.
    """

    points = []
    ad_path = os.path.join(DEFENCE_DIR, "air_defence.png")

    print("  [*] Scanning air defences...")
    t0 = time.time()
    ads = find_defence_matches(
        ad_path,
        confidence=AIR_DEFENCE_MATCH_CONFIDENCE,
    )
    elapsed = time.time() - t0

    for cx, cy, score in ads:
        print(
            f"  [v] air_defence @ ({cx},{cy})  conf={score:.2f}"
        )
        for _ in range(LIGHTNING_ZAPS_PER_AD):
            points.append((cx, cy))

    if not points:
        print(
            f"  [!] No ADs found in {elapsed:.1f}s — "
            "using calibrated LIGHTNING_POINTS"
        )
        return LIGHTNING_POINTS

    print(f"  [+] Found {len(ads)} AD(s) in {elapsed:.1f}s")
    return points


def healer_point_left_of_queen(queen_pt):
    """Deploy healer slightly left of the archer queen border drop."""

    return (queen_pt[0] - HEALER_LEFT_OFFSET, queen_pt[1])


def deploy_healer(healer_card, queen_pt):
    """Deploy all healers left of the archer queen drop point."""

    pt = healer_point_left_of_queen(queen_pt)
    print(
        f"  [>] Deploying healer after queen "
        f"-> ({pt[0]},{pt[1]})"
    )

    deselect()
    select_card(healer_card)
    time.sleep(0.2)

    if card_is_exhausted(healer_card):
        print("    healer already exhausted — skipping")
        return

    deployed = 0
    while not card_is_exhausted(healer_card):
        raw_click(pt[0], pt[1])
        time.sleep(0.05)
        deployed += 1
        if deployed >= 200:
            print("    [!] safety cap reached")
            break

    print(f"    disabled after {deployed} clicks")
    time.sleep(0.2)


def find_button(template_path, confidence=MATCH_CONFIDENCE):
    try:
        screen   = screenshot()
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            print(f"  [!] Missing template: {template_path}")
            return None
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val >= confidence:
            h, w  = template.shape[:2]
            cx, cy = max_loc[0] + w//2, max_loc[1] + h//2
            print(f"  [v] {template_path} @ ({cx},{cy})  conf={max_val:.2f}")
            return (cx, cy)
        return None
    except Exception as e:
        print(f"  [!] find_button error: {e}")
        return None


def raw_click(x, y, delay=0.0):
    """Low-level click using pydirectinput."""
    x, y = safe_coords(x, y)
    pydirectinput.moveTo(x, y)
    time.sleep(0.03)
    pydirectinput.mouseDown(x, y)
    time.sleep(0.03)
    pydirectinput.mouseUp(x, y)
    if delay:
        time.sleep(delay)


def click(pos, delay=0.5):
    raw_click(pos[0], pos[1], delay)


def wait_for(template_path, timeout=45, interval=0.5):
    t = 0
    while t < timeout:
        pos = find_button(template_path)
        if pos:
            return pos
        time.sleep(interval)
        t += interval
    print(f"  [!] Timeout waiting for {template_path}")
    return None


# ─────────────────────────────────────────────────────────────
# LOOT CHECK
# ─────────────────────────────────────────────────────────────

def ocr_number(region):
    left, top, w, h = region
    img = ImageGrab.grab(bbox=(left, top, left+w, top+h))
    img = img.resize((w*3, h*3), Image.LANCZOS).convert("L")
    np_img = np.array(img)
    _, binary = cv2.threshold(np_img, 200, 255, cv2.THRESH_BINARY_INV)
    text = pytesseract.image_to_string(
        binary,
        config="--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789KkMm,."
    ).strip().upper().replace(",","")
    m = re.search(r"(\d+)\s*([KM]?)", text)
    if not m:
        return 0
    v = int(m.group(1))
    if m.group(2) == "K": v *= 1_000
    if m.group(2) == "M": v *= 1_000_000
    return v


def loot_ok():
    gold   = ocr_number(GOLD_REGION)
    elixir = ocr_number(ELIXIR_REGION)
    ok     = gold >= MIN_GOLD and elixir >= MIN_ELIXIR
    print(f"  [Loot] Gold={gold:,} Elixir={elixir:,} → {'PASS' if ok else 'FAIL'}")
    return ok


# ─────────────────────────────────────────────────────────────
# CARD DETECTION
# ─────────────────────────────────────────────────────────────

def capture_bar():
    """Capture just the card area of the troop bar."""
    left, top, w, h = TROOP_BAR_REGION
    img = ImageGrab.grab(bbox=(left, top, left+w, top+h))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def load_card_templates():
    """Load troop/hero/spell portrait templates from templates/."""

    global _CARD_TEMPLATES
    if _CARD_TEMPLATES is not None:
        return _CARD_TEMPLATES

    templates = []
    for card_type, folder in TEMPLATE_DIRS.items():
        for path in glob.glob(os.path.join(folder, "*.png")):
            img = cv2.imread(path, cv2.IMREAD_COLOR)
            if img is None:
                print(f"  [!] Could not load template: {path}")
                continue
            name = os.path.splitext(os.path.basename(path))[0]
            templates.append({
                "name": name,
                "type": card_type,
                "img": img,
                "path": path,
            })

    _CARD_TEMPLATES = templates
    return templates


def portrait_roi(card_img):
    """Match on the portrait body, not the xN badge (count varies)."""

    h, w = card_img.shape[:2]
    return card_img[
        int(h * 0.18):int(h * 0.92),
        int(w * 0.05):int(w * 0.95),
    ]


def portrait_gray(card_img):
    """Grayscale portrait used for matching — ignores xN badge."""

    return cv2.cvtColor(portrait_roi(card_img), cv2.COLOR_BGR2GRAY)


def _rank_templates(card_img):
    """Return [(score, template_dict), ...] sorted best-first."""

    templates = load_card_templates()
    if not templates:
        return []

    rois = [
        portrait_gray(card_img),
        cv2.cvtColor(card_img, cv2.COLOR_BGR2GRAY),
    ]
    ranked = []

    for tmpl in templates:
        t_portrait = portrait_gray(
            cv2.resize(tmpl["img"], (CARD_WIDTH, CARD_HEIGHT))
        )
        t_full = cv2.cvtColor(
            cv2.resize(tmpl["img"], (CARD_WIDTH, CARD_HEIGHT)),
            cv2.COLOR_BGR2GRAY,
        )
        best_score = 0.0
        for roi in rois:
            rh, rw = roi.shape[:2]
            for t_roi in (t_portrait, t_full):
                for scale in (0.94, 1.0, 1.06):
                    sw = max(12, int(rw * scale))
                    sh = max(12, int(rh * scale))
                    t_resized = cv2.resize(t_roi, (sw, sh))
                    if t_resized.shape[0] > rh or t_resized.shape[1] > rw:
                        continue
                    result = cv2.matchTemplate(
                        roi, t_resized, cv2.TM_CCOEFF_NORMED
                    )
                    best_score = max(best_score, float(result.max()))
        ranked.append((best_score, tmpl))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def _best_template_guess(card_img):
    ranked = _rank_templates(card_img)
    return ranked[0][1]["name"] if ranked else None


def identify_card(card_img):
    """
    Match a single slot crop to the best template.
    Returns (name, type, confidence) or (None, None, best_score).
    """

    ranked = _rank_templates(card_img)
    if not ranked or ranked[0][0] < CARD_MATCH_CONFIDENCE:
        return None, None, ranked[0][0] if ranked else 0.0

    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    if ranked[0][0] - second_score < CARD_MATCH_MARGIN:
        return None, None, ranked[0][0]

    best = ranked[0][1]
    return best["name"], best["type"], ranked[0][0]


def _resize_card(img, bar_h):
    """Normalize a template/card image to standard slot dimensions."""

    return cv2.resize(img, (CARD_WIDTH, bar_h))


def _template_peak_on_bar(bar_strip, tmpl_img):
    """
    Find the best horizontal position for one template on the bar.
    Returns (bar_x, score).
    """

    bar_h = bar_strip.shape[0]
    sized = _resize_card(tmpl_img, bar_h)
    bar_gray = cv2.cvtColor(bar_strip, cv2.COLOR_BGR2GRAY)
    tmpl_views = [
        cv2.cvtColor(sized, cv2.COLOR_BGR2GRAY),
        portrait_gray(sized),
    ]

    best_x = 0
    best_score = 0.0

    for tmpl_gray in tmpl_views:
        if tmpl_gray.shape[0] > bar_h or tmpl_gray.shape[1] > bar_strip.shape[1]:
            continue
        result = cv2.matchTemplate(
            bar_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED
        )
        _, score, _, loc = cv2.minMaxLoc(result)
        if score > best_score:
            best_score = float(score)
            best_x = int(loc[0])

    return best_x, best_score


def scan_bar_positions(bar):
    """
    Locate card columns by sliding every template across the bar.
    The troop bar grows from screen-center as army size changes.
    """

    bar_h = min(CARD_HEIGHT, bar.shape[0])
    bar_strip = bar[0:bar_h, :]
    min_sep = int(CARD_WIDTH * CARD_SLOT_GAP)
    peaks = []

    for tmpl in load_card_templates():
        bar_x, score = _template_peak_on_bar(bar_strip, tmpl["img"])
        if score < CARD_SCAN_MIN_SCORE:
            continue
        peaks.append({
            "bar_x": bar_x,
            "score": score,
            "name": tmpl["name"],
            "type": tmpl["type"],
        })

    peaks.sort(key=lambda p: p["score"], reverse=True)

    accepted = []
    for peak in peaks:
        if any(
            abs(peak["bar_x"] - slot["bar_x"]) < min_sep
            for slot in accepted
        ):
            continue
        accepted.append(peak)

    accepted.sort(key=lambda p: p["bar_x"])

    if DEBUG:
        for peak in peaks[:15]:
            mark = "✓" if peak in accepted else "·"
            print(
                f"  [scan] {mark} {peak['name']:16s} "
                f"bar_x={peak['bar_x']} score={peak['score']:.2f}"
            )

    return accepted


def crop_card(bar, bar_x):
    """Crop one card column from the captured bar."""

    bar_h = min(CARD_HEIGHT, bar.shape[0])
    x1 = max(0, bar_x)
    x2 = min(bar.shape[1], bar_x + CARD_WIDTH)
    if x2 - x1 < CARD_WIDTH // 2:
        return None
    return bar[0:bar_h, x1:x2]


def _template_by_name(name):
    for tmpl in load_card_templates():
        if tmpl["name"] == name:
            return tmpl
    return None


def refine_card_crop(bar, bar_x, radius=16):
    """
    Small horizontal search — scan peaks can be a few px off the
    true slot edge, which tanks crop-only match scores.
    """

    best_img = None
    best_x = bar_x
    best_score = -1.0

    for dx in range(-radius, radius + 1, 2):
        card_img = crop_card(bar, bar_x + dx)
        if card_img is None:
            continue
        ranked = _rank_templates(card_img)
        if not ranked:
            continue
        if ranked[0][0] > best_score:
            best_score = ranked[0][0]
            best_img = card_img
            best_x = bar_x + dx

    if best_img is None:
        return crop_card(bar, bar_x), bar_x

    return best_img, best_x


def resolve_card_identity(card_img, slot):
    """
    Identify a card crop. Fall back to the bar-scan attribution when
    the crop match is weak but the full-bar scan was confident.
    """

    ranked = _rank_templates(card_img)
    if ranked:
        name, card_type, score = identify_card(card_img)
        if name is not None:
            return name, card_type, score

    scan_name = slot.get("name")
    scan_score = slot.get("score", 0.0)
    scan_type = slot.get("type")
    scan_rank = 0.0

    if scan_name and ranked:
        for score, tmpl in ranked:
            if tmpl["name"] == scan_name:
                scan_rank = score
                break

    if scan_name and scan_score >= CARD_SCAN_MIN_SCORE:
        if scan_rank >= 0.35 or (
            ranked and ranked[0][1]["name"] == scan_name
        ):
            return scan_name, scan_type, max(scan_score, scan_rank)

    if ranked and ranked[0][0] >= CARD_MATCH_CONFIDENCE:
        second_score = ranked[1][0] if len(ranked) > 1 else 0.0
        if ranked[0][0] - second_score >= CARD_MATCH_MARGIN:
            best = ranked[0][1]
            return best["name"], best["type"], ranked[0][0]

    return None, None, ranked[0][0] if ranked else 0.0


def detect_all_cards():
    """
    Find cards on the center-aligned troop bar via template scan,
    then confirm each crop with identify_card().
    """

    bar = capture_bar()
    cards = []

    for slot in scan_bar_positions(bar):
        bar_x = slot["bar_x"]
        card_img, bar_x = refine_card_crop(bar, bar_x)
        if card_img is None:
            continue

        if DEBUG:
            cv2.imwrite(f"debug_slot_{bar_x}.png", card_img)

        if np.mean(cv2.cvtColor(card_img, cv2.COLOR_BGR2GRAY)) < 20:
            continue

        name, card_type, score = resolve_card_identity(card_img, slot)
        if name is None:
            guess = _best_template_guess(card_img)
            guess_txt = f", guess={guess}" if guess else ""
            print(
                f"  [!] Unknown card bar_x={bar_x} "
                f"(best={score:.2f}{guess_txt})"
            )
            continue

        screen_x = TROOP_BAR_REGION[0] + bar_x + CARD_WIDTH // 2

        cards.append({
            "name": name,
            "type": card_type,
            "screen_x": screen_x,
            "screen_y": CARD_SCREEN_Y,
            "bar_x": bar_x,
            "match_conf": score,
        })

    if not cards:
        print("  [!] No cards matched — check templates/ folder")

    return cards


def card_is_disabled(card_img):
    """
    Fully deployed troop/spell cards turn grey and dim.
    Dark event troops (e.g. lavaloon) stay desaturated while active,
    so rely on overall brightness — not header colour or saturation alone.
    """

    h, w = card_img.shape[:2]
    top_hsv = cv2.cvtColor(
        card_img[0:int(h * 0.20), :],
        cv2.COLOR_BGR2HSV
    )
    top_blue = np.count_nonzero(
        cv2.inRange(top_hsv, (90, 60, 60), (130, 255, 255))
    )
    mean_sat = np.mean(
        cv2.cvtColor(card_img, cv2.COLOR_BGR2HSV)[:, :, 1]
    )
    mean_val = np.mean(
        cv2.cvtColor(card_img, cv2.COLOR_BGR2GRAY)
    )

    return (
        mean_val < 62
        or (
            mean_val < 78
            and mean_sat < 38
            and top_blue < 600
        )
    )


def card_is_exhausted(card):

    bar = capture_bar()
    bar_x = card["bar_x"]
    card_img = crop_card(bar, bar_x)
    if card_img is None:
        return True

    return card_is_disabled(card_img)


# ─────────────────────────────────────────────────────────────
# BATTLE CHECK
# ─────────────────────────────────────────────────────────────

def _match_template_in_roi(screen, template_path, roi, confidence=BATTLE_UI_CONFIDENCE):
    """
    Multi-scale match within a screen region.
    Returns ((cx, cy), score) or (None, best_score).
    """

    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        print(f"  [!] Missing template: {template_path}")
        return None, 0.0

    left, top, rw, rh = roi
    region = screen[top:top + rh, left:left + rw]
    best_score = 0.0
    best_center = None

    for scale in BATTLE_UI_SCALES:
        tw = max(10, int(template.shape[1] * scale))
        th = max(10, int(template.shape[0] * scale))
        if th > region.shape[0] or tw > region.shape[1]:
            continue

        scaled = cv2.resize(template, (tw, th))
        result = cv2.matchTemplate(region, scaled, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(result)
        if score > best_score:
            best_score = float(score)
            best_center = (
                left + loc[0] + tw // 2,
                top + loc[1] + th // 2,
            )

    if best_score >= confidence and best_center:
        return best_center, best_score

    return None, best_score


def find_return_home_click(screen=None):
    """Locate the green Return Home button on the victory screen."""

    if screen is None:
        screen = screenshot()

    h, w = screen.shape[:2]
    top = int(h * 0.58)
    roi = (0, top, w, h - top)

    pos, score = _match_template_in_roi(
        screen, RETURN_HOME_BTN_TEMPLATE, roi
    )
    if pos:
        print(
            f"  [v] return_home @ ({pos[0]},{pos[1]})  "
            f"conf={score:.2f}"
        )
        return pos

    return None


def is_victory_banner_visible(screen=None, quiet=False):
    """Victory ribbon / stars at the top of the end-battle screen."""

    if screen is None:
        screen = screenshot()

    h, w = screen.shape[:2]
    roi = (0, 0, w, int(h * 0.40))

    pos, score = _match_template_in_roi(
        screen, VICTORY_BANNER_TEMPLATE, roi
    )
    if pos and not quiet:
        print(
            f"  [v] victory_banner @ ({pos[0]},{pos[1]})  "
            f"conf={score:.2f}"
        )
        return True

    return pos is not None


def is_battle_end_screen(screen=None):
    """True when victory UI or Return Home button is visible."""

    if screen is None:
        screen = screenshot()

    h, w = screen.shape[:2]

    btn, _ = _match_template_in_roi(
        screen,
        RETURN_HOME_BTN_TEMPLATE,
        (0, int(h * 0.58), w, h - int(h * 0.58)),
    )
    if btn:
        return True

    banner, _ = _match_template_in_roi(
        screen,
        VICTORY_BANNER_TEMPLATE,
        (0, 0, w, int(h * 0.40)),
    )
    return banner is not None


def find_return_home():
    """
    Return Home click position on the victory screen.
    end_battle.png is intentionally unused (visible during live battles).
    """

    screen = screenshot()
    home = find_return_home_click(screen)
    if home:
        return home

    if is_victory_banner_visible(screen):
        return RETURN_HOME_POINT

    return None


def battle_over():
    """Battle finished when victory UI appears."""

    return is_battle_end_screen()


# ─────────────────────────────────────────────────────────────
# DEPLOY
# ─────────────────────────────────────────────────────────────

def select_card(card):
    """Click the card in the troop bar to select it."""
    x, y = safe_coords(card["screen_x"], card["screen_y"])
    raw_click(x, y, delay=0.3)


def deselect():
    """Tap a neutral area to clear the current card selection."""
    raw_click(1366, 100, delay=0.15)


def deploy_troops(troops, rage_card=None):

    """
    Deploy troops one click at a time until disabled.
    Healer is handled separately in deploy_heroes().
    """

    rage_cast = False
    total_clicks = 0

    for card in troops:

        print(
            f"  [>] Deploying troop "
            f"{card['name']} bar_x={card['bar_x']}"
        )

        deselect()
        select_card(card)
        time.sleep(0.2)

        if card_is_exhausted(card):
            print("    already exhausted — skipping")
            continue

        deployed = 0
        point_idx = 0

        while not card_is_exhausted(card):

            if (
                rage_card
                and not rage_cast
                and total_clicks >= RAGE_DEPLOY_AFTER_CLICKS
            ):
                cast_rage(rage_card)
                rage_cast = True
                deselect()
                select_card(card)
                time.sleep(0.2)

            pt = DEPLOY_POINTS[point_idx % len(DEPLOY_POINTS)]
            raw_click(pt[0], pt[1])
            time.sleep(0.05)
            deployed += 1
            total_clicks += 1
            point_idx += 1

            if deployed >= 200:
                print("    [!] safety cap reached")
                break

        print(f"    disabled after {deployed} clicks")
        time.sleep(0.2)

    if rage_card and not rage_cast:
        cast_rage(rage_card)


def cast_spell_until_exhausted(card, points, delay=0.35, reselect_every=2):
    """Cast a spell on rotating points until the card greys out."""

    print(f"  [>] Casting {card['name']} until disabled")

    deselect()
    select_card(card)
    time.sleep(0.3)

    if card_is_exhausted(card):
        print(f"    {card['name']} already exhausted — skipping")
        return

    casts = 0
    pt_idx = 0

    while not card_is_exhausted(card):
        if casts > 0 and casts % reselect_every == 0:
            select_card(card)
            time.sleep(0.25)

        pt = points[pt_idx % len(points)]
        raw_click(pt[0], pt[1])
        time.sleep(delay)
        casts += 1
        pt_idx += 1

    print(f"    disabled after {casts} casts")
    time.sleep(0.2)


def cast_rage(rage_card):
    """Drop rage inside the troop funnel — not on the outer deploy ring."""

    pt = RAGE_CAST_POINT

    print(
        f"  [>] Casting rage in funnel "
        f"{rage_card['name']} -> ({pt[0]},{pt[1]})"
    )

    time.sleep(RAGE_CAST_DELAY)
    deselect()
    select_card(rage_card)
    time.sleep(0.3)
    raw_click(pt[0], pt[1])
    time.sleep(0.3)


def cast_lightning(lightning_card):
    points = resolve_lightning_targets()
    cast_spell_until_exhausted(
        lightning_card,
        points,
        delay=0.35,
        reselect_every=2,
    )


def deploy_freeze(freeze_cards):

    for card in freeze_cards:
        cast_spell_until_exhausted(
            card,
            FREEZE_POINTS,
            delay=0.2,
            reselect_every=1,
        )

def deploy_heroes(heroes, healer_card=None):

    deployed = {}
    healer_done = False

    for idx, card in enumerate(heroes):

        pt = HERO_DEPLOY_POINTS.get(
            card["name"],
            DEPLOY_POINTS[idx % len(DEPLOY_POINTS)],
        )

        print(
            f"  [>] Deploying {card['name']} "
            f"-> ({pt[0]},{pt[1]})"
        )

        deselect()
        time.sleep(0.05)
        select_card(card)
        time.sleep(0.15)

        if card_is_exhausted(card):
            print(f"    {card['name']} already deployed — skipping")
            if card["name"] == "archer_queen" and healer_card and not healer_done:
                queen_pt = HERO_DEPLOY_POINTS["archer_queen"]
                deploy_healer(healer_card, queen_pt)
                healer_done = True
            continue

        raw_click(pt[0], pt[1])
        deployed[card["name"]] = pt
        time.sleep(0.15)

        if card["name"] == "archer_queen" and healer_card and not healer_done:
            deploy_healer(healer_card, pt)
            healer_done = True

    if healer_card and not healer_done:
        queen_pt = deployed.get(
            "archer_queen",
            HERO_DEPLOY_POINTS["archer_queen"],
        )
        deploy_healer(healer_card, queen_pt)

    return deployed

def deploy_spells(spells):
    """Legacy wrapper — prefer cast_lightning / cast_rage / deploy_freeze."""
    for card in spells:
        if card["name"] == "lightning":
            cast_lightning(card)
        elif card["name"] == "rage":
            cast_rage(card)
        elif card["name"] == "freeze":
            deploy_freeze([card])


def activate_hero_abilities(heroes):
    """Click each hero card again to activate their ability."""

    if is_battle_end_screen():
        print("  [*] Battle over — skipping hero abilities")
        return

    print("  [>] Activating hero abilities...")
    for card in heroes:
        select_card(card)
        time.sleep(0.15)


def deploy_all():

    print("  [*] Scanning troop bar...")

    cards = detect_all_cards()

    troops = sorted(
        [c for c in cards if c["type"] == "TROOP"],
        key=lambda c: c["bar_x"],
    )
    healer_card = next((c for c in troops if c["name"] == "healer"), None)
    troops = [c for c in troops if c["name"] != "healer"]

    heroes = sorted(
        [c for c in cards if c["type"] == "HERO"],
        key=lambda c: c["bar_x"],
    )

    spells = sorted(
        [c for c in cards if c["type"] == "SPELL"],
        key=lambda c: c["bar_x"],
    )

    lightning = next((c for c in spells if c["name"] == "lightning"), None)
    rage = next((c for c in spells if c["name"] == "rage"), None)
    freeze_cards = [c for c in spells if c["name"] == "freeze"]

    print(
        f"  [*] Detected: "
        f"{len(troops)} troops, "
        f"{len(heroes)} heroes, "
        f"{len(spells)} spells"
    )

    for c in cards:
        print(
            f"      {c['type']:6s} {c['name']:16s} "
            f"conf={c['match_conf']:.2f} "
            f"screen=({c['screen_x']},{c['screen_y']})"
        )

    if not cards:
        print(
            "  [!] No cards detected"
        )
        return False

    deselect()

    print("  [*] Deploying heroes...")
    hero_positions = deploy_heroes(heroes, healer_card=healer_card)

    deselect()
    if lightning:
        print("  [*] Casting lightning on defences...")
        cast_lightning(lightning)

    deselect()
    print("  [*] Deploying troops...")
    deploy_troops(troops, rage_card=rage)

    deselect()
    if freeze_cards:
        print("  [*] Casting freeze on defenses...")
        deploy_freeze(freeze_cards)

    activate_hero_abilities(heroes)

    print("  [*] Deployment complete!")

    return True

# ─────────────────────────────────────────────────────────────
# MAIN LOOP  — state machine
# ─────────────────────────────────────────────────────────────

def run():
    print("=" * 55)
    print("  CoC Event Bot v3  --  starting in 5 seconds")
    print("  EMERGENCY STOP: move mouse to top-left corner")
    print("=" * 55)
    time.sleep(5)

    attacks = 0
    skips   = 0

    while True:
        print(f"\n{'─'*50}")
        print(f"  Attacks={attacks}  Skips={skips}")

        # ── State: Scouting (Next button visible) ────────────
        next_btn = find_button("templates/next_btn.png")
        if next_btn:
            print("  [State] Scouting base...")
            if MIN_GOLD == 0 and MIN_ELIXIR == 0 or loot_ok():
                print("  [+] Loot OK — deploying!")
                success = deploy_all()
                if success:
                    attacks += 1
                else:
                    print(
                        "  [!] Deployment failed"
                    )
                    continue

                # Wait for battle to end, then click Return Home immediately
                print("  [~] Waiting for battle to finish...")
                deadline = time.time() + 240
                home = None
                while time.time() < deadline:
                    screen = screenshot()
                    home = find_return_home_click(screen)
                    if home:
                        print("  [+] Battle finished!")
                        break
                    if is_victory_banner_visible(screen, quiet=True):
                        home = RETURN_HOME_POINT
                        print(
                            "  [+] Victory screen — "
                            f"clicking Return Home @ {home}"
                        )
                        break
                    time.sleep(BATTLE_POLL_INTERVAL)

                if home:
                    click(home, delay=RETURN_HOME_CLICK_DELAY)
                else:
                    print("  [!] Return Home not found")
            else:
                print("  [-] Loot too low — skipping")
                click(next_btn, delay=1.0)
                skips += 1
            continue

        # ── State: Home Village ───────────────────────────────
        home_btn = find_button("templates/attack_initialize_btn.png")
        if home_btn:
            print("  [State] Home — starting matchmaking...")
            click(home_btn, delay=1.0)
            match_btn = wait_for("templates/find_match_btn.png", timeout=10)
            if match_btn:
                click(match_btn, delay=1.0)
            confirm = find_button("templates/attack_btn.png")
            if confirm:
                click(confirm, delay=1.0)
            continue

        # ── State: Post-battle ────────────────────────────────
        return_home = find_return_home()
        if return_home:
            print("  [State] Post-battle — returning home...")
            click(return_home, delay=RETURN_HOME_CLICK_DELAY)
            continue

        # ── Unknown state ─────────────────────────────────────
        print("  [?] Unknown state — waiting 2s...")
        time.sleep(2)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[Stopped by user]", flush=True)
        sys.exit(0)