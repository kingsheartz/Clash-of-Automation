# Setup Guide: CoC Event Bot

Follow these steps to fully configure and run your Clash of Clans automation bot.

## 1. Environment Setup

> [!WARNING]
> This script must be run directly on **Windows**, not within WSL (Windows Subsystem for Linux), as it needs to interact with your Windows screen and the game window.

1. Open a regular Windows PowerShell or Command Prompt.
2. Navigate to your project folder:
   ```powershell
   cd D:\WORK\Projects\COC-Automate
   ```
3. Install the required Python packages:
   ```powershell
   pip install pyautogui opencv-python pytesseract Pillow
   ```
4. Install **Tesseract OCR for Windows** from [here](https://github.com/UB-Mannheim/tesseract/wiki).
5. Update the path to Tesseract in `coc_bot.py` if necessary:
   ```python
   pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
   ```

## 2. Create Template Images

> [!IMPORTANT]
> The bot relies on exact image matches. You must capture these from your screen.

Create a `templates/` folder in your project directory:
```powershell
mkdir templates
```

Use `Win + Shift + S` to take **tight screenshots** (snip just the button itself, without much background) for each of these items. Save them exactly with these `.png` filenames inside the `templates/` folder.

| Filename | When to capture | Description |
| --- | --- | --- |
| `attack_initialize_btn.png` | Home Screen | The map "Attack!" icon on the bottom left |
| `find_match_btn.png` | Matchmaking Screen | The "Find a Match" button (showing the gold coin cost) |
| `attack_btn.png` | Confirm Attack | The green "Attack!" confirm button |
| `next_btn.png` | Enemy Base | The "Next" button to skip a base |
| `battle_end.png` | Battle Complete | The red "End Battle" button |
| `return_home.png` | Battle Complete | The green "Return Home" button |

## 3. Calibrate OCR (Loot Detection)

The script uses Optical Character Recognition (OCR) to read the available Gold and Elixir. You need to calibrate the screen coordinates so it knows exactly where to look.

1. Start your game and reach an enemy base screen (where you can see the loot numbers in the top left).
2. Run `Calibrate.py`:
   ```powershell
   python Calibrate.py
   ```
3. Hover your mouse over the Gold number and note the coordinates output in the terminal.
4. Hover over the Elixir number and note those coordinates.
5. Update the `GOLD_REGION` and `ELIXIR_REGION` in `coc_bot.py`:
   ```python
   # Format: (left, top, width, height)
   GOLD_REGION   = (750, 190, 220, 38)
   ELIXIR_REGION = (750, 232, 220, 38)
   ```

## 4. Finalize Configuration

Review the top configuration section of `coc_bot.py` before running:
- **Loot Thresholds**: Adjust `MIN_GOLD` and `MIN_ELIXIR` (or set both to 0 to attack everyone regardless of loot).
- **Shortcuts**: Update `TROOP_KEYS`, `HERO_KEYS`, and `SPELL_KEYS` to match the keyboard shortcuts mapped in your Google Play Games emulator.
- **Deploy Points**: By default, it clicks coordinates based on a 1392x783 game window. Use `Calibrate.py` to hover around the outer dirt border of the enemy base and update `DEPLOY_POINTS` if your window size is different.

## 5. Run the Bot

1. Have your game open and visible on the Home Screen.
2. Run the script natively in Windows:
   ```powershell
   python coc_bot.py
   ```
3. **Failsafe**: To emergency stop the script at any time, violently move your mouse cursor to the **top-left corner** of your primary monitor.
