"""
Clash of Clans - Event Attack Automation v3
Platform: Windows native (Google Play Games)
Screen: High-DPI display (effective 2732x1536 with 2x scaling)

HOW CARD DETECTION WORKS:
  1. Capture the troop bar region (TROOP_BAR_REGION)
  2. Split into fixed slots using CARD_WIDTH spacing
  3. Classify each slot:
       - Has xN count in top + blue background  → TROOP
       - Has xN count in top + non-blue bg      → SPELL
       - No xN count                            → HERO
  4. Track count remaining per troop/spell card
  5. Click card to select, then click deploy points

DEPLOY LOGIC:
  - Troops: deploy until card greyed-out (disabled view)
  - Heroes: click card once → click border point → activate ability after 15s
  - Lightning: first, on air-defense cluster (LIGHTNING_POINTS)
  - Rage: mid troop deploy, on funnel path where troops are walking
  - Freeze: last, on defenses (FREEZE_POINTS)

Install:
  pip install pyautogui pydirectinput opencv-python pytesseract Pillow
  + Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
"""

import cv2
import numpy as np
import pytesseract
import pydirectinput
import pyautogui
import time
import re
import sys
from collections import Counter
from PIL import ImageGrab, Image

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

MIN_GOLD   = 1_000_000
MIN_ELIXIR = 500_000

MATCH_CONFIDENCE = 0.75

# Set True to save OCR/card debug images and verbose scan logs
DEBUG = False

# ── Loot OCR ─────────────────────────────────────────────────
GOLD_REGION   = (238, 246, 328, 72)
ELIXIR_REGION = (235, 326, 323, 65)

# ── Troop Bar ─────────────────────────────────────────────────
# The full region containing all troop/hero/spell cards
# Format: (screen_left, screen_top, capture_width, capture_height)
TROOP_BAR_REGION = (232, 1467, 2748, 210)  # Only capture top 210px (card area)

# Card layout within the captured bar image
CARD_X_STARTS  = [232, 421, 610, 799, 988, 1177, 1366, 1555, 1744, 1933]
CARD_WIDTH     = 185
CARD_HEIGHT    = 210
CARD_CENTER_Y  = 105   # vertical center within card

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

# Spell drop points — calibrate with calibrate.py option 3
# Army spell order: Lightning @ 1555, Rage @ 1744, Freeze @ 1933

SPELL_SLOTS = {
    1555: "lightning",
    1744: "rage",
    1933: "freeze",
}

# Fallback when spell badge OCR fails (rage x1 often reads as bare 'x')
SPELL_DEFAULT_COUNTS = {
    1555: 8,
    1744: 1,
    1933: 1,
}

# Lightning x8 → 4 air defenses (diagonal cluster), 2 spells each
LIGHTNING_POINTS = [
    (1410, 795), (1415, 800),   # AD 1
    (1495, 855), (1500, 860),   # AD 2
    (1580, 915), (1585, 920),   # AD 3
    (1665, 975), (1670, 980),   # AD 4
]

# Rage → troop funnel path (border → base); cast mid-deploy while troops move
RAGE_FUNNEL_POINTS = [
    (1920, 1387),   # deploy edge — where troops land
    (1850, 1250),   # just inside border
    (1750, 1100),   # troop blob as they walk in
]
RAGE_DEPLOY_AFTER_CLICKS = 6   # cast rage after this many troop clicks
RAGE_CAST_DELAY = 1.5          # extra wait so troops have moved into funnel

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


def read_count(card_img):
    """
    OCR the xN badge from the card's top header strip.
    Runs several preprocess passes — a single crop/threshold
    is not reliable across troops, spells, and digit widths.
    """

    h, w = card_img.shape[:2]

    # Badge lives in the thin header bar only; taller crops pull in
    # troop portraits and destroy tesseract accuracy.
    passes = [
        (0.18, 0.38, 10, 200, False, 7),
        (0.20, 0.35, 8,  180, False, 8),
        (0.18, 0.38, 10, 200, True,  8),
        (0.20, 0.40, 8,  150, False, 7),
        (0.22, 0.35, 8,  180, False, 8),
        (0.20, 0.35, 12, 180, False, 7),
        (0.18, 0.52, 12, 170, False, 8),  # x1 spells: badge sits far right
        (0.16, 0.55, 12, 180, False, 7),
    ]

    counts = []
    raws = []
    debug_thresh = None

    for hfrac, wfrac, scale, thresh_val, invert, psm in passes:
        roi = card_img[0:int(h * hfrac), int(w * wfrac):w]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(
            gray, None, fx=scale, fy=scale,
            interpolation=cv2.INTER_CUBIC
        )
        flag = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
        _, thresh = cv2.threshold(gray, thresh_val, 255, flag)
        raw = pytesseract.image_to_string(
            thresh,
            config=f"--psm {psm} -c tessedit_char_whitelist=xX0123456789"
        ).strip()
        raws.append(raw)

        m = re.search(r"[xX]+(\d+)", raw)
        if m:
            counts.append(int(m.group(1)))
            if DEBUG and debug_thresh is None:
                debug_thresh = thresh

    if DEBUG and debug_thresh is not None:
        cv2.imwrite(
            f"count_debug_{int(time.time()*1000)}.png",
            debug_thresh
        )

    if DEBUG:
        print(f"OCR RAW={raws}")

    if counts:
        return Counter(counts).most_common(1)[0][0]

    return 0


def resolve_spell_count(bar_x, ocr_count):
    """Use OCR count when available, else known army defaults."""
    if ocr_count > 0:
        return ocr_count
    return SPELL_DEFAULT_COUNTS.get(bar_x, 1)


def classify_card(card_img, count):
    """
    Classify by the top header strip — troops/spells have a flat
    coloured bar with the xN badge; heroes are portrait-only.
    """

    h, w = card_img.shape[:2]
    top_hsv = cv2.cvtColor(
        card_img[0:int(h * 0.20), :],
        cv2.COLOR_BGR2HSV
    )

    top_blue = np.count_nonzero(
        cv2.inRange(top_hsv, (90, 60, 60), (130, 255, 255))
    )
    top_purple = np.count_nonzero(
        cv2.inRange(top_hsv, (120, 40, 40), (170, 255, 255))
    )

    has_header = top_blue > 4000

    if count > 0 or has_header:
        if top_purple > 3000:
            return "SPELL"
        return "TROOP"

    return "HERO"


def detect_all_cards():

    bar = capture_bar()

    cards = []

    for bar_x in CARD_X_STARTS:

        if bar_x + CARD_WIDTH > bar.shape[1]:
            continue

        card_img = bar[
            0:CARD_HEIGHT,
            bar_x:bar_x+CARD_WIDTH
        ]

        if DEBUG:
            cv2.imwrite(
                f"debug_slot_{bar_x}.png",
                card_img
            )

        mean_brightness = np.mean(
            cv2.cvtColor(
                card_img,
                cv2.COLOR_BGR2GRAY
            )
        )

        if mean_brightness < 20:
            continue

        count = read_count(card_img)

        card_type = classify_card(
            card_img,
            count
        )

        if card_type == "SPELL":
            count = resolve_spell_count(bar_x, count)

        screen_x = (
            TROOP_BAR_REGION[0]
            + bar_x
            + CARD_WIDTH // 2
        )

        screen_y = CARD_SCREEN_Y

        if DEBUG:
            print(
                f"SLOT={bar_x} "
                f"COUNT={count} "
                f"TYPE={card_type}"
            )

        cards.append({
            "type": card_type,
            "count": count,
            "screen_x": screen_x,
            "screen_y": screen_y,
            "bar_x": bar_x,
        })

    return cards


def card_is_disabled(card_img):
    """
    Fully deployed troop/spell cards turn grey and lose their
    coloured header bar. Heroes grey out too but lack the x0 badge.
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

    # Active troops/spells: saturated portrait + blue/purple header.
    # Disabled: grey card, header bar gone (top_blue was ~5000).
    return top_blue < 1500 and mean_sat < 80


def card_is_exhausted(card):

    bar = capture_bar()
    bar_x = card["bar_x"]

    card_img = bar[
        0:CARD_HEIGHT,
        bar_x:bar_x + CARD_WIDTH
    ]

    return card_is_disabled(card_img)


# ─────────────────────────────────────────────────────────────
# BATTLE CHECK
# ─────────────────────────────────────────────────────────────

def battle_over():
    """
    Battle is over only when the Return Home screen appears.
    The End Battle button is visible during active battles,
    so it must never be used as a completion signal.
    """
    return find_button(
        "templates/return_home.png",
        confidence=0.85
    ) is not None


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
    Casts rage mid-deploy once troops are walking into the base.
    """

    rage_cast = False
    total_clicks = 0

    for card in troops:

        print(
            f"  [>] Deploying troop "
            f"bar_x={card['bar_x']}"
        )

        deselect()
        select_card(card)
        time.sleep(0.2)

        if card_is_exhausted(card):
            print("    already disabled — skipping")
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


def cast_rage(rage_card):
    """Drop rage on the troop funnel while troops are moving in."""

    pt = RAGE_FUNNEL_POINTS[1]

    print(
        f"  [>] Casting rage on funnel "
        f"bar_x={rage_card['bar_x']} "
        f"-> ({pt[0]},{pt[1]})"
    )

    time.sleep(RAGE_CAST_DELAY)
    deselect()
    select_card(rage_card)
    time.sleep(0.3)
    raw_click(pt[0], pt[1])
    time.sleep(0.3)


def cast_lightning(lightning_card):

    count = SPELL_DEFAULT_COUNTS[1555]

    print(
        f"  [>] Casting lightning "
        f"bar_x={lightning_card['bar_x']} x{count}"
    )

    deselect()
    select_card(lightning_card)
    time.sleep(0.3)

    for i in range(count):
        if i > 0 and i % 2 == 0:
            select_card(lightning_card)
            time.sleep(0.25)

        pt = LIGHTNING_POINTS[i % len(LIGHTNING_POINTS)]
        raw_click(pt[0], pt[1])
        time.sleep(0.4)

    time.sleep(0.3)


def deploy_freeze(freeze_cards):

    for card in freeze_cards:

        bar_x = card["bar_x"]
        count = resolve_spell_count(bar_x, card["count"])

        print(
            f"  [>] Casting freeze "
            f"bar_x={bar_x} x{count}"
        )

        deselect()
        select_card(card)
        time.sleep(0.3)

        for i in range(count):
            pt = FREEZE_POINTS[i % len(FREEZE_POINTS)]
            raw_click(pt[0], pt[1])
            time.sleep(0.2)

        time.sleep(0.3)

def deploy_heroes(heroes):

    hero_points = [
        DEPLOY_POINTS[0],
        DEPLOY_POINTS[8],
        DEPLOY_POINTS[16],
    ]

    hero_names = {
        988: "King",
        1177: "Warden",
        1366: "Queen",
    }

    for idx, card in enumerate(heroes):

        pt = hero_points[idx % len(hero_points)]
        name = hero_names.get(card["bar_x"], f"hero{idx}")

        print(
            f"  [>] Deploying {name} "
            f"bar_x={card['bar_x']} "
            f"-> ({pt[0]},{pt[1]})"
        )

        deselect()
        time.sleep(0.1)
        select_card(card)
        time.sleep(0.4)

        raw_click(pt[0], pt[1])
        time.sleep(0.5)

def deploy_spells(spells):
    """Legacy wrapper — prefer cast_lightning / cast_rage / deploy_freeze."""
    for card in spells:
        kind = SPELL_SLOTS.get(card["bar_x"], "spell")
        if kind == "lightning":
            cast_lightning(card)
        elif kind == "rage":
            cast_rage(card)
        elif kind == "freeze":
            deploy_freeze([card])


def activate_hero_abilities(heroes):
    """
    After troops are deployed and 15s have passed,
    click each hero card again to activate their ability.
    """
    print("  [>] Activating hero abilities...")
    for card in heroes:
        select_card(card)
        time.sleep(0.3)


def deploy_all():

    print("  [*] Scanning troop bar...")

    cards = detect_all_cards()

    troops = [
        c for c in cards
        if c["type"] == "TROOP"
    ]

    heroes = [
        c for c in cards
        if c["type"] == "HERO"
    ]

    spells = [
        c for c in cards
        if c["type"] == "SPELL"
    ]

    lightning = next(
        (c for c in spells if SPELL_SLOTS.get(c["bar_x"]) == "lightning"),
        None,
    )
    rage = next(
        (c for c in spells if SPELL_SLOTS.get(c["bar_x"]) == "rage"),
        None,
    )
    freeze_cards = [
        c for c in spells if SPELL_SLOTS.get(c["bar_x"]) == "freeze"
    ]

    print(
        f"  [*] Detected: "
        f"{len(troops)} troops, "
        f"{len(heroes)} heroes, "
        f"{len(spells)} spells"
    )

    for c in cards:

        print(
            f"      {c['type']:6s} "
            f"count={c['count']:2d} "
            f"screen=({c['screen_x']},{c['screen_y']})"
        )

    if not cards:
        print(
            "  [!] No cards detected"
        )
        return False

    deselect()

    print("  [*] Deploying heroes...")
    deploy_heroes(heroes)

    deselect()
    if lightning:
        print("  [*] Casting lightning on air defenses...")
        cast_lightning(lightning)

    deselect()
    print("  [*] Deploying troops...")
    deploy_troops(troops, rage_card=rage)

    deselect()
    if freeze_cards:
        print("  [*] Casting freeze on defenses...")
        deploy_freeze(freeze_cards)

    print(
        "  [*] Waiting 20s "
        "before hero abilities..."
    )

    time.sleep(20)

    activate_hero_abilities(
        heroes
    )

    print(
        "  [*] Deployment complete!"
    )

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
                print("  [+] Loot OK — attacking!")
                time.sleep(1)
                success = deploy_all()
                if success:
                    attacks += 1
                else:
                    print(
                        "  [!] Deployment failed"
                    )
                    continue

                # Wait for battle to end
                print("  [~] Waiting for battle to finish...")
                deadline = time.time() + 240
                while time.time() < deadline:
                    if battle_over():
                        print("  [+] Battle finished!")
                        break
                    time.sleep(1)

                home = wait_for("templates/return_home.png", timeout=30)
                if home:
                    click(home, delay=2.0)
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
        return_home = find_button("templates/return_home.png")
        if return_home:
            print("  [State] Post-battle — returning home...")
            click(return_home, delay=2.0)
            continue

        # ── Unknown state ─────────────────────────────────────
        print("  [?] Unknown state — waiting 2s...")
        time.sleep(2)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[Stopped by user]")
        sys.exit(0)