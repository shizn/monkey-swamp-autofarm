# Monkey Swamp III Auto-Farm

Personal research / learning project for a **self-hosted private server** (BeiDou GMS083). Target map **Monkey Swamp III (107000403)**, Golden Beach:

- **Zombie Monkey `4230101` ×30** (undead) → **Heal `c`** when inside the Heal box; if it is outside the Heal box but within Magic Claw range, it is hit with **Magic Claw `v`** instead.
- **Green Snake `2130103` ×14** → **Magic Claw `v`** (directional).

Goal: **hold the center of the current platform** and clear whatever comes into range. No roaming, no rope climbing.

## How it works

- **Map data (authoritative)** comes from the server's own WZ, exported to `mapdata/geo_107000403.json` (631 footholds, 17 platforms, 44 spawns). Monster sprites are the GMS/83 art from maplestory.io; the Zombie Monkey sprite (49×65) matches the server's WZ canvas size exactly.
- **Localization**: the character's minimap dot is found inside the minimap content rectangle. That rectangle is located by edge-matching a reference minimap image (`mapdata/minimap107000403.png`, the static platform schematic with the moving colored dots removed) against the top-left of the frame — this is robust against the dark jungle background, which a plain "largest dark region" search is not.
- **Screen anchor**: the minimap dot is converted to a world coordinate, then to a screen position with a **camera-clamp model on both axes**. When the camera hits a map edge (left/right or top/bottom) it stops centering on the player, so the anchor is offset accordingly instead of assuming the player is at screen center. See `_screen_anchor`.
- **Detection**: GPU batched masked template matching (PyTorch `conv2d`, from `gpu_match`) finds monkeys and snakes each frame. Falls back to CPU (`cv2`) with no GPU.
- **Centering**: keep the minimap dot at a target x (auto platform-center, or a manually captured "occupy point"); walk back when off by more than a deadzone, stand when centered. Recentering takes priority over casting, because casting locks movement.

## Modules

- `monkey_farm.py` — engine (reuses `ant_farm` for capture / DPI / privilege / HP-MP / minimap, and `subway_farm`'s `gpu_match` / `navmap`), detection, heal/claw logic, centering controller, calibration, diagnostics.
- `monkey_gui.py` — control panel + a debug overlay (Heal box, monkey/snake detection markers, FPS).
- `build_geo.py` — rebuild `geo_107000403.json` and the reference minimap from the server WZ.

## Usage

Run **`启动.bat`** (self-elevates; the game runs as admin, so the tool must too). `启动_控制台.bat` is the same but with a console window for diagnostics.

1. Enter the game, stand on the platform you want to farm, with the minimap and HP/MP bars visible and no menus covering them.
2. **Calibrate** — locates the minimap content rectangle and scale.
3. **Occupy point** (optional) — records your current spot as the fixed hold target.
4. Enable the **debug overlay** to check the Heal box and detection, then **Start** and focus the game window.

Hotkeys: `F9` pause/resume, `F12` stop.

## Options (panel)

- **Randomization** (off by default): jitter on cast hold-duration, cast intervals, and hold-point offset, plus optional periodic function-key taps. Any field set to `0` keeps the fixed behavior.
- **Image alarm** (on by default): low-frequency multi-scale template match of configured reference images against the client area; on a match it loops `templates/alert_alarm.wav` and shows the score, latched until stopped from the panel.

## Tuning

- `match_scale` — on-screen sprite scale (starts at 1.4). Adjust if detection is weak.
- `monkey_thresh` / `snake_thresh` — match thresholds; real monsters should score clearly below false positives (check via the debug overlay).
- If minimap matching ever fails, re-crop the real minimap into `mapdata/minimap107000403.png`.
