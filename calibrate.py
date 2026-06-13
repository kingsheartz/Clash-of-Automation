"""
CoC Bot Calibrator
Run this script to find the exact coordinates for your specific screen resolution.
"""
import pyautogui
import time

def get_region(name):
    print(f"\n--- Calibrating {name} ---")
    input(f"1. Hover your mouse over the TOP-LEFT corner of the {name} number and press Enter...")
    x1, y1 = pyautogui.position()
    print(f"   [+] Top-Left saved at: ({x1}, {y1})")
    
    input(f"2. Hover your mouse over the BOTTOM-RIGHT corner of the {name} number and press Enter...")
    x2, y2 = pyautogui.position()
    print(f"   [+] Bottom-Right saved at: ({x2}, {y2})")
    
    w = x2 - x1
    h = y2 - y1
    return (x1, y1, w, h)

def main():
    print("="*50)
    print("  CoC Bot Calibrator")
    print("="*50)
    print("1) Calibrate Deploy Points (for troops/spells)")
    print("2) Calibrate Loot Regions (Gold/Elixir OCR boxes)")
    choice = input("\nEnter 1 or 2: ")
    
    if choice.strip() == '2':
        print("\n" + "="*50)
        gold = get_region("GOLD")
        elixir = get_region("ELIXIR")
        
        print("\n" + "="*50)
        print("Copy and paste this into coc_bot.py (around line 54):\n")
        print(f"GOLD_REGION   = {gold}")
        print(f"ELIXIR_REGION = {elixir}")
        print("="*50)
        
    else:
        print("\n" + "="*50)
        print("Hover over the 'Possible' green grass areas around the base.")
        print("Press ENTER in this terminal to save a point.")
        print("Type 'q' and press ENTER when you are done to generate the code.")
        print("="*50)

        points = []
        while True:
            user_input = input(f"Point {len(points)+1} (Hover mouse and press Enter, or 'q' to quit): ")
            if user_input.strip().lower() == 'q':
                break
            
            x, y = pyautogui.position()
            points.append((x, y))
            print(f"  [+] Saved point: ({x}, {y})")

        print("\n" + "="*50)
        print("Copy and paste this into coc_bot.py:\n")
        print("DEPLOY_POINTS = [")
        for pt in points:
            print(f"    {pt},")
        print("]")
        print("="*50)

if __name__ == "__main__":
    main()