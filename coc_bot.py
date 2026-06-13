"""
Clash of Clans - Event Attack Automation v2
Platform: Windows native (Google Play Games)

Flow:
  1. attack_initialize_btn  — map "Attack!" on home screen
  2. find_match_btn         — "Find a Match 1100c"
  3. attack_btn             — green "Attack!" confirm
  4. next_btn loop          — skip bases with loot < 500k
  5. Deploy heroes + troops + spells along outer border
  6. End Battle -> Return Home -> repeat

Templates needed in ./templates/:
  attack_initialize_btn.png   map icon Attack! on home screen
  find_match_btn.png          Find a Match 1100 coin button
  attack_btn.png              green Attack! confirm button
  next_btn.png                Next 1100 coin button (skip base)
  battle_end.png              red End Battle button
  return_home.png             green Return Home button

Install:
  pip install pyautogui opencv-python pytesseract Pillow
  + Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
"""

import pyautogui
import pydirectinput
import cv2
import numpy as np
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
import time
import re
import sys
from PIL import ImageGrab, Image

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Loot thresholds — set both to 0 to attack everyone
MIN_GOLD   = 1_000_000
MIN_ELIXIR = 500_000

# Template match confidence (0.0–1.0); lower = more lenient
MATCH_CONFIDENCE = 0.75

# ── Loot OCR regions ─────────────────────────────────────────
# Pixel region of gold/elixir numbers on the matchmaking screen
# Format: (left, top, width, height)
# Run calibrate.py to find your exact values
GOLD_REGION   = (238, 246, 328, 72)
ELIXIR_REGION = (235, 326, 323, 65)

# Troop bar region — the horizontal strip at the bottom of the screen
# where ALL troop cards are displayed during battle.
# Format: (left, top, width, height)
# The script scans this area for pink "x" count text to detect remaining troops.
# Run Calibrate.py to find the exact bounds of your troop bar.
TROOP_BAR_REGION = (232, 1467, 2748, 1677)

# ── Deploy border points ──────────────────────────────────────
# Troops and heroes must be clicked on the OUTER BORDER
# (the grass/dirt strip just outside the enemy walls).
# These are adjusted to avoid the 'Not possible' tree area at the very edges.
DEPLOY_POINTS = [
    (1920, 1387),
    (2129, 1209),
    (2396, 1040),
    (2510, 896),
    (2448, 732),
    (2258, 556),
    (2044, 411),
    (1798, 246),
    (1279, 246),
    (1096, 352),
    (944, 474),
    (805, 552),
    (641, 751),
    (567, 870),
    (669, 999),
    (787, 1082),
    (939, 1183),
    (990, 1238),
    (1123, 1316),
    (1304, 1415),
    (1819, 1425),
    (2001, 1284),
    (2048, 1244),
    (2173, 1153),
]

# Spells land ON the base — aim for the center area
SPELL_POINTS = [
    (1524, 784),
    (1603, 704),
    (1809, 779),
    (1668, 952),
    (1454, 1005),
    (1336, 899),
    (1294, 827),
    (1686, 651),
]

# ─────────────────────────────────────────────────────────────
# SAFETY
# ─────────────────────────────────────────────────────────────

pyautogui.FAILSAFE = True   # Emergency stop: move mouse to top-left
pyautogui.PAUSE    = 0.25
pydirectinput.FAILSAFE = True
pydirectinput.PAUSE = 0.25


# ─────────────────────────────────────────────────────────────
# CORE HELPERS
# ─────────────────────────────────────────────────────────────

def screenshot():
    img = ImageGrab.grab()
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def find_button(template_path, confidence=MATCH_CONFIDENCE):
    """Return (x, y) center of template on screen, or None."""
    try:
        screen   = screenshot()
        template = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if template is None:
            print(f"  [!] Missing template: {template_path}")
            return None
        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val >= confidence:
            h, w = template.shape[:2]
            cx, cy = max_loc[0] + w // 2, max_loc[1] + h // 2
            print(f"  [v] {template_path} @ ({cx},{cy})  conf={max_val:.2f}")
            return (cx, cy)
        return None
    except Exception as e:
        print(f"  [!] find_button error: {e}")
        return None


def click(pos, delay=0.5):
    pydirectinput.moveTo(pos[0], pos[1])
    time.sleep(0.05)
    pydirectinput.mouseDown(pos[0], pos[1])
    time.sleep(0.05)
    pydirectinput.mouseUp(pos[0], pos[1])
    time.sleep(delay)


def wait_for(template_path, timeout=45, interval=0.5):
    """Block until template appears; return its position or None."""
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
# BATTLE CHECK
# ─────────────────────────────────────────────────────────────

def battle_still_running():
    timer_region = (1450, 20, 300, 120)

    img = ImageGrab.grab(
        bbox=(
            timer_region[0],
            timer_region[1],
            timer_region[0] + timer_region[2],
            timer_region[1] + timer_region[3]
        )
    )

    gray = cv2.cvtColor(
        np.array(img),
        cv2.COLOR_RGB2GRAY
    )

    text = pytesseract.image_to_string(
        gray,
        config="--psm 7"
    ).upper()

    return (
        "M" in text
        or "S" in text
        or re.search(r"\d+", text)
    )

def battle_over():

		# Battle timer disappeared
    if not battle_still_running():
        return True

		# Return Home visible
    if find_button(
        "templates/return_home.png",
        confidence=0.90
    ):
        return True

    return False

# ─────────────────────────────────────────────────────────────
# LOOT CHECK
# ─────────────────────────────────────────────────────────────

def ocr_number(region):
    left, top, w, h = region
    img = ImageGrab.grab(bbox=(left, top, left + w, top + h))
    img = img.resize((w * 3, h * 3), Image.LANCZOS).convert("L")

    # CoC text is white. Threshold it to make it black text on white background
    np_img = np.array(img)
    _, binary = cv2.threshold(np_img, 200, 255, cv2.THRESH_BINARY_INV)

    # Save debug image so we can verify OCR is reading the right area
    try:
        cv2.imwrite("debug_ocr_region.png", binary)
    except Exception:
        pass

    text = pytesseract.image_to_string(
        binary, config="--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789KkMm,."
    )
    raw = text.strip()
    text = raw.upper().replace(",", "").replace(" ", "")
    print(f"    [OCR] region={region} raw='{raw}' cleaned='{text}'")
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
    print(f"  [Loot] Gold={gold:,}  Elixir={elixir:,}  (need {MIN_GOLD:,}/{MIN_ELIXIR:,})")
    ok = gold >= MIN_GOLD and elixir >= MIN_ELIXIR
    print(f"  [Loot] Result: {'PASS' if ok else 'FAIL'}")
    return ok


# ─────────────────────────────────────────────────────────────
# DEPLOY
# ─────────────────────────────────────────────────────────────

def focus_game():
    """
    Click a safe neutral area at the top of the game window
    to ensure the game has window focus.
    Adjust (700, 30) if the top bar is in a different position.
    """
    pydirectinput.moveTo(700, 30)
    time.sleep(0.05)
    pydirectinput.mouseDown(700, 30)
    time.sleep(0.05)
    pydirectinput.mouseUp(700, 30)
    time.sleep(0.1)


def click_card(card):
    cx, cy = card_center(card)

    pydirectinput.moveTo(cx, cy)
    time.sleep(0.02)

    pydirectinput.mouseDown(cx, cy)
    time.sleep(0.02)
    pydirectinput.mouseUp(cx, cy)

    time.sleep(0.05)

def get_battle_cards():
    cards = detect_cards()
    cards.sort(key=lambda c: c[0])

    troops = cards[:5]
    heroes = cards[5:8]
    spells = cards[8:]

    return troops, heroes, spells

def get_troop_bar():
    left, top, w, h = TROOP_BAR_REGION

    img = ImageGrab.grab(
        bbox=(left, top, left+w, top+h)
    )

    return cv2.cvtColor(
        np.array(img),
        cv2.COLOR_RGB2BGR
    )

def detect_cards():

    img = get_troop_bar()

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    edges = cv2.Canny(gray, 100, 200)

    contours, _ = cv2.findContours(
        edges,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    cards = []

    for cnt in contours:

        x, y, w, h = cv2.boundingRect(cnt)

        # Real troop cards are roughly:
        # width 140-190
        # height 180-240

        if not (140 <= w <= 190):
            continue

        if not (180 <= h <= 240):
            continue

        cards.append((x, y, w, h))

    # Remove duplicates
    cards.sort(key=lambda c: c[0])

    filtered = []

    for card in cards:

        if not filtered:
            filtered.append(card)
            continue

        prev = filtered[-1]

        if abs(card[0] - prev[0]) > 50:
            filtered.append(card)

    return filtered

def card_center(card):
    x, y, w, h = card

    left, top, _, _ = TROOP_BAR_REGION

    return (
        left + x + w//2,
        top + y + h//2
    )

def card_is_active(card):

    img = get_troop_bar()

    x, y, w, h = card

    roi = img[y:y+h, x:x+w]

    hsv = cv2.cvtColor(
        roi,
        cv2.COLOR_BGR2HSV
    )

    saturation = hsv[:,:,1]

    score = np.mean(saturation)

    return score > 35

def save_card_debug():

    img = get_troop_bar()

    cards = detect_cards()

    cv2.imwrite("troop_bar_debug.png", img)

    for idx, (x, y, w, h) in enumerate(cards):

        roi = img[y:y+h, x:x+w]

        cv2.imwrite(
            f"card_{idx}.png",
            roi
        )

    print(f"Saved {len(cards)} cards.")

def debug_cards():

    cards = detect_cards()

    print(f"[Cards] {len(cards)}")

    for i, card in enumerate(cards):
        print(
            i,
            card,
            card_is_active(card)
        )

def get_spell_count(card):

    img = get_troop_bar()

    x, y, w, h = card

    roi = img[y:y+h, x:x+w]

    # bottom-right area where x8/x1 is shown
    count_roi = roi[int(h*0.60):h, int(w*0.55):w]

    gray = cv2.cvtColor(
        count_roi,
        cv2.COLOR_BGR2GRAY
    )

    gray = cv2.resize(
        gray,
        None,
        fx=4,
        fy=4,
        interpolation=cv2.INTER_CUBIC
    )

    _, thresh = cv2.threshold(
        gray,
        140,
        255,
        cv2.THRESH_BINARY
    )

    text = pytesseract.image_to_string(
        thresh,
        config="--psm 7"
    )

    m = re.search(r'(\d+)', text)

    if m:
        return int(m.group(1))

    return 1

def deploy_all():

    focus_game()
    time.sleep(0.5)

    cards = detect_cards()

    if len(cards) < 8:
        print("[!] Not enough cards detected")
        return

    troops, heroes, spells = get_battle_cards()

    print(
        f"Troops={len(troops)} "
        f"Heroes={len(heroes)} "
        f"Spells={len(spells)}"
    )

    # ------------------
    # TROOPS
    # ------------------

    print("[*] Deploying troops...")

    for troop in troops:

        click_card(troop)

        safety = 0

        while card_is_active(troop) and safety < 300:

            point = DEPLOY_POINTS[
                safety % len(DEPLOY_POINTS)
            ]

            pydirectinput.moveTo(*point)

            pydirectinput.mouseDown(*point)
            pydirectinput.mouseUp(*point)

            time.sleep(0.03)

            safety += 1

        print(
            f"Troop exhausted after {safety} drops"
        )

    # ------------------
    # HEROES
    # ------------------

    print("[*] Deploying heroes...")

    for idx, hero in enumerate(heroes):

        click_card(hero)

        point = DEPLOY_POINTS[
            (idx * 4) % len(DEPLOY_POINTS)
        ]

        pydirectinput.moveTo(*point)
        pydirectinput.mouseDown(*point)
        pydirectinput.mouseUp(*point)

        time.sleep(0.1)

    # ------------------
		# SPELLS
		# ------------------

    print("[*] Casting spells...")

    CENTER_SPELL_POINTS = [
				(1524, 784),
				(1560, 760),
				(1490, 820),
				(1600, 800),
		]

    for spell in spells:

        count = get_spell_count(spell)

        print(f"Spell count = {count}")

        click_card(spell)

        for i in range(count):

            point = CENTER_SPELL_POINTS[
                i % len(CENTER_SPELL_POINTS)
            ]

            pydirectinput.moveTo(*point)
            pydirectinput.mouseDown(*point)
            pydirectinput.mouseUp(*point)

            time.sleep(0.25)

    # ------------------
    # HERO ABILITIES
    # ------------------

    print("[*] Waiting 5s...")

    time.sleep(5)

    for hero in heroes:

        click_card(hero)

    print("[*] Deployment finished.")

# ─────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────

def run():
    print("=" * 55)
    print("  CoC Event Bot  --  starting in 5 seconds")
    print("  EMERGENCY STOP: move mouse to top-left corner")
    print("=" * 55)
    time.sleep(5)

    attacks = 0
    skips   = 0

    while True:
        print(f"\n{'─'*50}")
        print(f"  [Round {attacks+1}]  Attacks={attacks}  Skips={skips}")

        # State 1: We are scouting a base (Next button is visible)
        next_btn = find_button("templates/next_btn.png")
        if next_btn:
            print("  [State] Scouting a base...")
            if MIN_GOLD == 0 and MIN_ELIXIR == 0 or loot_ok():
                print("  [+] Loot meets threshold! Attacking...")
                time.sleep(1)
                deploy_all()
                attacks += 1

                print("  [~] Waiting for battle to finish (Return Home)...")
                # Battle can take up to 3 mins
                start = time.time()

                while time.time() - start < 240:

                    if battle_over():
                        print("  [+] Battle finished")
                        break

                time.sleep(0.5)

                return_home = wait_for(
                    "templates/return_home.png",
                    timeout=30,
                    interval=0.5
                )

                if return_home:
                    click(return_home, delay=1.0)
                else:
                    print("  [!] Return Home not found")
            else:
                print("  [-] Skipping base...")
                click(next_btn, delay=1.0)
                skips += 1
            continue

        # State 2: We are at Home
        home_btn = find_button("templates/attack_initialize_btn.png")
        if home_btn:
            print("  [State] At Home Village. Starting matchmaking...")
            click(home_btn, delay=1.0)
            match_btn = wait_for("templates/find_match_btn.png", timeout=10)
            if match_btn:
                click(match_btn, delay=1.0)

            # Just in case there is a green confirm button (some events)
            attack_confirm = find_button("templates/attack_btn.png")
            if attack_confirm:
                click(attack_confirm, delay=1.0)
            continue

        # State 3: Battle Ended (Return Home button is visible)
        return_home = find_button("templates/return_home.png")
        if return_home:
            print("  [State] Post-battle. Returning home...")
            click(return_home, delay=1.0)
            continue

        # Unknown State
        print("  [!] Unknown state (Cannot find Home, Next, or Return buttons). Waiting 2s...")
        time.sleep(2)

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\n[Stopped by user]")