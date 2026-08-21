# -*- coding: utf-8 -*-
"""猴子沼泽地Ⅲ(107000403) farm:稳定站在平台正中间,治愈(c)群秒僵尸猴(不死),双击/魔双(v)打青蛇。
GPU 批量模板匹配 + 小地图定位保持居中。复用 ant_farm 底层原语 + subway_farm 的 gpu_match/navmap。
研究/学习用(用户自建本地服 BeiDou GMS083)。热键 F9 暂停/继续  F12 退出。
"""
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except Exception: pass

import sys, os, time, json, random, threading, winsound
import numpy as np, cv2
sys.path.insert(0, r"C:\Workspace\ant_farm")
sys.path.insert(0, r"C:\Workspace\subway_farm")
import ant_farm as eng                       # 抓帧/DPI/提权/血蓝/小地图/输入
from navmap import NavMap
try:
    import torch
    from gpu_match import GpuMatcher
    _HAS_GPU = torch.cuda.is_available()
except Exception:
    _HAS_GPU = False

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")

DEFAULT_CFG = {
    "window_title_contains": "冒险岛",
    "geo_path": os.path.join(HERE, "mapdata", "geo_107000403.json"),
    "template_dir": os.path.join(HERE, "templates"),

    # 检测(GPU)
    "use_gpu": True, "match_downscale": 0.5,
    "monkey_thresh": 0.30,        # 治愈只数数量,阈值可略松
    "snake_thresh": 0.22,         # 魔双要瞄准,严一点
    "match_scale": 1.4,           # 屏上尺度(与地铁同客户端/DPI, 1.4 起步, 按调试层微调)
    "monkey_frames": ["monkey_stand_0.png", "monkey_move_0.png", "monkey_move_2.png"],
    "snake_frames": ["snake_move_0.png", "snake_move_2.png"],

    # 锚点(角色"脚下"屏幕位置;居中farm时基本在屏幕中间,靠边平台用摄像机夹取)
    "anchor_x_frac": 0.5, "anchor_y_frac": 0.58,
    "band_up": 160, "band_down": 150,

    # 治愈(群体,不死): 矩形AoE。技能2301002 lt/rb=±250(横)×±150(纵)世界单位,以角色脚下为心
    "heal_key": "c", "heal_min": 1, "heal_interval": 0.75, "heal_burst": 1, "heal_tap_gap": 0.05,
    "heal_x": 250, "heal_up": 150, "heal_down": 170,
    # 魔法双击(定向): 青蛇进射程→朝它放
    "claw_key": "v", "claw_range": 320, "claw_y_tol": 90,
    "claw_taps": 2, "claw_tap_gap": 0.04, "claw_interval": 0.55, "turn_hold": 0.06,

    # 小地图/定位
    "minimap_rect": None,
    "minimap_png": os.path.join(HERE, "mapdata", "minimap107000403.png"),
    "mm_scale": None,
    "plat_ytol": 55,

    # 居中(核心): 保持在当前平台正中间。回中优先级高于放技能。
    "hold_dot": None,             # 手动占位点[小地图x,y]: 站到想守的点点"初始化占位"记下, 工具把你保持在这(优先于自动找中点)
    "center_dead_mm": 2,          # 站定阈值(小地图px): 偏<此就站定; 魔双也只在此内放(它会把人推离)
    "cast_zone_mm": 5,            # 放技能容忍区(px): 偏>此→先回中、不放技能(放技能会锁步,回不来)
    "recenter_pad_mm": 3,         # 校准平台端点内缩(px),防抖到端外

    # 血蓝
    "bars_region": None, "hp_key": "1", "mp_key": "2",
    "hp_ratio_thresh": 0.45, "mp_ratio_thresh": 0.30, "potion_cooldown": 0.9,

    # 捡物 / 循环
    "pickup_enable": True, "pickup_key": "z", "pickup_interval": 0.45,
    "loop_sleep": 0.004,

    # 随机化(默认关闭,保持旧配置行为不变)
    # 按住占比=每次施法改用 keyDown→随机时长→keyUp 的概率；0=始终轻点,100=始终按住。
    "randomize_enable": False,
    "heal_hold_chance_pct": 0.0, "claw_hold_chance_pct": 0.0,
    "skill_hold_min": 0.08, "skill_hold_max": 0.22,
    # 每次施法完成后重掷下一次间隔,实际范围=基础间隔×(1±百分比)。
    "heal_interval_jitter_pct": 15.0, "claw_interval_jitter_pct": 15.0,
    # 站位目标在中心/手动占位点附近缓慢换点；有平台扫界时会夹在安全边界内。
    "center_offset_mm": 0.0,
    "center_offset_period_min": 5.0, "center_offset_period_max": 12.0,
    # 运行且游戏置顶时,每隔随机时长轻点一次 F3 或 F7；需同时开启随机化总开关。
    "random_fkey_enable": False,
    "random_fkey_min": 1.0, "random_fkey_max": 120.0,
    "random_fkey_f3_pct": 50.0,

    # 特征图片报警：命中后声音锁存，直到面板点“停止报警”；图片消失后可再次触发。
    "alert_enable": True,
    "alert_template": os.path.join(HERE, "templates", "alert_star_pattern.png"),
    "alert_templates": [
        {"name": "星星背景", "path": os.path.join(HERE, "templates", "alert_star_pattern.png")},
        {"name": "谎言探测仪", "path": os.path.join(HERE, "templates", "alert_lie_detector.png"),
         "patch_threshold_min": 0.75},
    ],
    "alert_sound": os.path.join(HERE, "templates", "alert_alarm.wav"),
    "alert_threshold": 0.76,
    "alert_patch_threshold": 0.80,
    "alert_scan_interval": 0.25,
    "alert_downscale": 0.15,
    "alert_scales": [0.5, 0.65, 0.82, 1.0, 1.22, 1.5, 1.8],
    "alert_patch_ratio": 0.46,
    "alert_clear_scans": 3,
}


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if os.path.exists(CFG_PATH):
        try: cfg.update(json.load(open(CFG_PATH, encoding="utf-8")))
        except Exception as e: print("读config失败:", e)
    return cfg


def save_cfg(cfg):
    json.dump(cfg, open(CFG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def _load_tpl(path):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None or im.ndim < 3 or im.shape[2] < 4: return None
    a = im[:, :, 3]; ys, xs = np.where(a > 20)
    if len(xs) == 0: return None
    im = im[ys.min():ys.max()+1, xs.min():xs.max()+1]
    return im[:, :, :3].copy(), im[:, :, 3].copy()


def _nms(dets, r=22):
    dets = sorted(dets, key=lambda d: d[2]); kept = []
    for d in dets:
        if all(not (d[3] == k[3] and abs(d[0]-k[0]) < r and abs(d[1]-k[1]) < r) for k in kept):
            kept.append(d)
    return kept


def _combat_targets(dets, ax, ay, hx, hup, hdn, claw_r, claw_yt):
    """按技能几何范围分组。

    治愈只打治愈矩形内的僵尸猴；魔双保持原有青蛇目标，并补充位于魔双范围内、
    但不在治愈矩形内的僵尸猴。返回 (heal_monkeys, snakes, claw_targets)。
    """
    def in_heal_box(d):
        return abs(d[0]-ax) <= hx and -hup <= (d[1]-ay) <= hdn

    def in_claw_range(d):
        return abs(d[0]-ax) <= claw_r and abs(d[1]-ay) <= claw_yt

    heal_monkeys = [d for d in dets if d[3] == "monkey" and in_heal_box(d)]
    snakes = [d for d in dets if d[3] == "snake" and in_claw_range(d)]
    claw_monkeys = [d for d in dets if d[3] == "monkey" and not in_heal_box(d) and in_claw_range(d)]
    return heal_monkeys, snakes, snakes + claw_monkeys


def _screen_anchor(wc, W, H, sx, sy, vr, cfg):
    """世界坐标→角色"脚下"的真实屏幕锚点 (ax, ay),两轴都做摄像机夹取。
    横/纵只要该轴 VR 比可视范围宽,就按夹取算(靠边/到顶到底镜头不居中→锚点自动偏);
    否则用固定比例。纵向补 (anchor_y_frac-0.5)*H 的"脚偏移"(居中时正好=anchor_y_frac*H)。"""
    swx = W/sx; swy = H/sy
    if wc is not None and vr and (vr[2]-vr[0]) > swx:
        camx = min(max(wc[0]-swx/2.0, vr[0]), vr[2]-swx); ax = int((wc[0]-camx)*sx)
    else:
        ax = int(W*cfg.get("anchor_x_frac", 0.5))
    if wc is not None and vr and (vr[3]-vr[1]) > swy:
        camy = min(max(wc[1]-swy/2.0, vr[1]), vr[3]-swy)
        ay = int((wc[1]-camy)*sy + (cfg.get("anchor_y_frac", 0.58)-0.5)*H)
    else:
        ay = int(H*cfg.get("anchor_y_frac", 0.58))
    return ax, ay


class AlertImageDetector:
    """整图 + 多个重叠区块的低分辨率多尺度模板匹配。"""
    def __init__(self, cfg):
        self.down = max(0.1, min(1.0, float(cfg.get("alert_downscale", 0.25) or 0.25)))
        self.scales = [max(0.2, float(s)) for s in cfg.get("alert_scales", [1.0])]
        self.full_templates = []; self.patch_templates = []; self.source_names = []; missing = []
        self.patch_threshold_mins = {}
        sources = cfg.get("alert_templates") or [
            {"name": "报警图", "path": cfg.get("alert_template")}]
        ratio = max(0.3, min(0.7, float(cfg.get("alert_patch_ratio", 0.46) or 0.46)))
        for i, item in enumerate(sources):
            if isinstance(item, str): name, path = "报警图%d" % (i+1), item
            else: name, path = str(item.get("name") or "报警图%d" % (i+1)), item.get("path")
            src = cv2.imread(path or "", cv2.IMREAD_COLOR)
            if src is None:
                missing.append(str(path)); continue
            self.source_names.append(name)
            if not isinstance(item, str) and item.get("patch_threshold_min") is not None:
                self.patch_threshold_mins[name] = max(0.3, min(0.99, float(item["patch_threshold_min"])))
            gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
            self.full_templates.extend(self._scaled_templates(gray, name))

            # 每张参考图取四角和中心；任何一个较大特征区块出现都可命中。
            ph = max(24, int(round(gray.shape[0] * ratio)))
            pw = max(24, int(round(gray.shape[1] * ratio)))
            max_x, max_y = gray.shape[1]-pw, gray.shape[0]-ph
            origins = [(0, 0), (max_x, 0), (0, max_y), (max_x, max_y), (max_x//2, max_y//2)]
            for x, y in origins:
                patch = gray[y:y+ph, x:x+pw]
                self.patch_templates.extend(self._scaled_templates(patch, name))
        if not self.source_names:
            raise RuntimeError("报警模板全部无法读取: %s" % "、".join(missing))

    def _scaled_templates(self, gray, label):
        out = []
        for scale in self.scales:
            scale = max(0.2, float(scale))
            tw = max(12, int(round(gray.shape[1] * self.down * scale)))
            th = max(12, int(round(gray.shape[0] * self.down * scale)))
            tpl = cv2.resize(gray, (tw, th), interpolation=cv2.INTER_AREA)
            out.append((label, scale, tpl))
        return out

    def _best_match(self, small, templates):
        sh, sw = small.shape[:2]
        best_score, best_loc, best_size, best_label = 0.0, None, None, ""
        for label, _scale, tpl in templates:
            th, tw = tpl.shape[:2]
            if th >= sh or tw >= sw: continue
            result = cv2.matchTemplate(small, tpl, cv2.TM_CCOEFF_NORMED)
            result[~np.isfinite(result)] = -1.0
            _, score, _, loc = cv2.minMaxLoc(result)
            if score > best_score:
                best_score, best_loc, best_size, best_label = float(score), loc, (tw, th), label
        if best_loc is None:
            return 0.0, None, ""
        inv = 1.0 / self.down
        x1 = int(round(best_loc[0] * inv)); y1 = int(round(best_loc[1] * inv))
        x2 = int(round((best_loc[0] + best_size[0]) * inv))
        y2 = int(round((best_loc[1] + best_size[1]) * inv))
        return best_score, (x1, y1, x2, y2), best_label

    def detect(self, frame):
        if frame is None or frame.shape[0] < 20 or frame.shape[1] < 20:
            return {"full_score": 0.0, "full_box": None, "patch_score": 0.0, "patch_box": None}
        gray = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY)
        sw = max(20, int(round(gray.shape[1] * self.down)))
        sh = max(20, int(round(gray.shape[0] * self.down)))
        small = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA)
        full_score, full_box, full_name = self._best_match(small, self.full_templates)
        patch_score, patch_box, patch_name = self._best_match(small, self.patch_templates)
        return {"full_score": full_score, "full_box": full_box, "full_name": full_name,
                "patch_score": patch_score, "patch_box": patch_box, "patch_name": patch_name,
                "patch_threshold_min": self.patch_threshold_mins.get(patch_name)}


class AlarmPlayer:
    """优先通过默认音频设备循环 WAV；不可用时回退后台蜂鸣。"""
    def __init__(self, sound_path=None):
        self.sound_path = sound_path or os.path.join(HERE, "templates", "alert_alarm.wav")
        self._lock = threading.Lock(); self._stop = threading.Event(); self._thread = None
        self._playing = False; self._mode = None

    @property
    def playing(self):
        with self._lock:
            return self._playing

    def start(self):
        with self._lock:
            if self._playing or (self._thread is not None and self._thread.is_alive()): return False
            try:
                flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP | winsound.SND_NODEFAULT
                winsound.PlaySound(self.sound_path, flags)
                self._playing = True; self._mode = "wav"
                return True
            except Exception:
                pass
            self._stop = threading.Event()
            self._playing = True; self._mode = "beep"
            self._thread = threading.Thread(target=self._run_beep, name="monkey-alert", daemon=True)
            self._thread.start()
            return True

    def stop(self):
        with self._lock:
            mode = self._mode
            self._playing = False; self._mode = None; self._stop.set()
        if mode == "wav":
            try: winsound.PlaySound(None, 0)
            except Exception: pass

    def _run_beep(self):
        try:
            pattern = ((1450, 360), (900, 220), (1450, 360))
            while not self._stop.is_set():
                for freq, duration in pattern:
                    if self._stop.is_set(): return
                    try:
                        winsound.Beep(freq, duration)
                    except Exception:
                        try: winsound.MessageBeep(winsound.MB_ICONHAND)
                        except Exception: pass
                        if self._stop.wait(0.35): return
                    if self._stop.wait(0.08): return
        finally:
            with self._lock:
                if self._thread is threading.current_thread(): self._thread = None
                if self._mode == "beep": self._playing = False; self._mode = None


class Detector:
    """GPU 优先;无 GPU 回退 CPU(cv2)。返回 [(cx,cy,score,label)],label∈{monkey,snake}。"""
    def __init__(self, cfg):
        self.cfg = cfg; td = cfg["template_dir"]
        tpls, labels = [], []
        for f in cfg["monkey_frames"]:
            t = _load_tpl(os.path.join(td, f))
            if t: tpls.append(t); labels.append("monkey")
        for f in cfg["snake_frames"]:
            t = _load_tpl(os.path.join(td, f))
            if t: tpls.append(t); labels.append("snake")
        if not tpls: raise RuntimeError("templates 缺失: " + td)
        self.tpls, self.labels = tpls, labels
        self.gpu = None
        if cfg.get("use_gpu") and _HAS_GPU:
            self.gpu = GpuMatcher(tpls, labels, scale=cfg["match_scale"],
                                  downscale=cfg["match_downscale"], device="cuda")

    def detect(self, frame, band, x0, x1):
        y0, y1 = band
        roi = frame[y0:y1, x0:x1]
        if roi.shape[0] < 12 or roi.shape[1] < 12: return []
        mt = self.cfg["monkey_thresh"]; st = self.cfg["snake_thresh"]
        out = []
        if self.gpu is not None:
            raw = self.gpu.detect(roi, thr=max(mt, st), x_off=x0, y_off=y0)
            for cx, cy, sc, lab, w, h in raw:
                if (lab == "monkey" and sc <= mt) or (lab == "snake" and sc <= st):
                    out.append((cx, cy, sc, lab))
        else:
            ds = self.cfg["match_downscale"]; s = self.cfg["match_scale"]
            sd = cv2.resize(roi, (int(roi.shape[1]*ds), int(roi.shape[0]*ds)), interpolation=cv2.INTER_AREA).astype(np.float32)
            for (bgr, mask), lab in zip(self.tpls, self.labels):
                thr = mt if lab == "monkey" else st
                for flip in (False, True):
                    b = cv2.flip(bgr, 1) if flip else bgr; m = cv2.flip(mask, 1) if flip else mask
                    tw = max(6, int(b.shape[1]*s*ds)); th = max(6, int(b.shape[0]*s*ds))
                    bb = cv2.resize(b, (tw, th)).astype(np.float32); mm = cv2.resize(m, (tw, th)).astype(np.float32)
                    if th >= sd.shape[0] or tw >= sd.shape[1]: continue
                    r = cv2.matchTemplate(sd, bb, cv2.TM_SQDIFF_NORMED, mask=mm); r[~np.isfinite(r)] = 1.0
                    ys, xs = np.where(r <= thr)
                    for x, y in zip(xs, ys):
                        out.append((int((x+tw/2)/ds)+x0, int((y+th/2)/ds)+y0, float(r[y, x]), lab))
        return _nms(out)


class MonkeyController:
    def __init__(self, cfg, log=print, on_status=None, on_debug=None, on_alert=None, alarm=None):
        self.cfg = cfg; self.log = log
        self.on_status = on_status or (lambda **k: None)
        self.on_debug = on_debug or (lambda d: None)
        self.on_alert = on_alert or (lambda **k: None)
        self.alarm = alarm or AlarmPlayer(cfg.get("alert_sound"))
        self.stop_flag = False; self.pause_flag = False
        self.state = "IDLE"; self.facing = "right"; self.held = None
        self.fps = 0.0; self._t = None; self._dbg = 0.0
        self.nav = NavMap(cfg["geo_path"])
        self.mv_act = ""
        self._center_offset = 0.0; self._next_center_offset = 0.0
        self.alert_visible = False; self.alert_ack = False; self.alert_misses = 0
        self.alert_score = 0.0; self.alert_box = None; self.alert_kind = ""; self.alert_state = None
        self.log("平台数 %d" % len(self.nav.platforms))

    # 输入
    def set_hold(self, d):
        if self.held == d: return
        if self.held:
            try: eng.pdi.keyUp(self.held)
            except Exception: pass
        if d:
            try: eng.pdi.keyDown(d)
            except Exception: pass
        self.held = d

    def _release(self):
        self.set_hold(None); eng.release_all()

    def stop(self): self.stop_flag = True
    def toggle_pause(self):
        self.pause_flag = not self.pause_flag; self._release()
        self.log("已" + ("暂停" if self.pause_flag else "继续")); return self.pause_flag

    def acknowledge_alert(self):
        was_playing = self.alarm.playing
        self.alarm.stop()
        if self.alert_visible:
            self.alert_ack = True
            self._emit_alert("ACK", self.alert_score)
        else:
            self._emit_alert("READY", self.alert_score)
        if was_playing: self.log("报警声音已停止")

    def _emit_alert(self, state, score=0.0):
        if state == self.alert_state: return
        self.alert_state = state; self.on_alert(state=state, score=score)

    def _check_alert(self, detector, frame):
        if not self.cfg.get("alert_enable", True):
            self.alarm.stop(); self.alert_visible = False; self.alert_ack = False
            self.alert_misses = 0; self.alert_score = 0.0; self.alert_box = None; self.alert_kind = ""
            self._emit_alert("OFF", 0.0); return
        if detector is None or frame is None: return
        match = detector.detect(frame)
        full_score = float(match.get("full_score", 0.0)); patch_score = float(match.get("patch_score", 0.0))
        full_threshold = max(0.3, min(0.99, float(self.cfg.get("alert_threshold", 0.76) or 0.76)))
        patch_threshold = max(0.3, min(0.99, float(self.cfg.get("alert_patch_threshold", 0.84) or 0.84)))
        if match.get("patch_threshold_min") is not None:
            patch_threshold = max(patch_threshold, float(match["patch_threshold_min"]))
        hits = []
        if full_score >= full_threshold:
            name = match.get("full_name") or "报警图"
            hits.append((full_score-full_threshold, full_score, match.get("full_box"), "%s·整体" % name))
        if patch_score >= patch_threshold:
            name = match.get("patch_name") or "报警图"
            hits.append((patch_score-patch_threshold, patch_score, match.get("patch_box"), "%s·区块" % name))
        if hits:
            _margin, score, box, kind = max(hits, key=lambda x: x[0])
        else:
            score = max(full_score, patch_score); box = None; kind = ""
        self.alert_score = score; self.alert_kind = kind
        if hits:
            self.alert_misses = 0; self.alert_box = box
            if not self.alert_visible:
                self.alert_visible = True
                if not self.alert_ack:
                    self.alarm.start()
                    self.log("!!! 检测到报警图片%s，相似度 %.3f；持续报警中 !!!" % (kind, score))
                    self._emit_alert("ALARM", score)
        else:
            self.alert_box = None; self.alert_misses += 1
            clear_n = max(1, int(self.cfg.get("alert_clear_scans", 3) or 3))
            if self.alert_visible and self.alert_misses >= clear_n:
                self.alert_visible = False; self.alert_ack = False
                state = "ALARM" if self.alarm.playing else "READY"
                self._emit_alert(state, score)
                self.log("报警图片已离开画面" + ("，声音继续等待手动停止" if self.alarm.playing else ""))

    def _random_enabled(self):
        return bool(self.cfg.get("randomize_enable", False))

    def _roll_hold(self, key):
        if not self._random_enabled(): return False
        chance = max(0.0, min(100.0, float(self.cfg.get(key, 0.0) or 0.0)))
        return random.random() * 100.0 < chance

    def _hold_duration(self):
        lo = max(0.0, float(self.cfg.get("skill_hold_min", 0.08) or 0.0))
        hi = max(0.0, float(self.cfg.get("skill_hold_max", 0.22) or 0.0))
        if hi < lo: lo, hi = hi, lo
        return random.uniform(lo, hi)

    def _next_interval(self, base_key, jitter_key):
        base = max(0.0, float(self.cfg.get(base_key, 0.0) or 0.0))
        if not self._random_enabled(): return base
        pct = max(0.0, min(100.0, float(self.cfg.get(jitter_key, 0.0) or 0.0))) / 100.0
        return max(0.0, base * random.uniform(1.0-pct, 1.0+pct))

    def _random_fkey_enabled(self):
        return self._random_enabled() and bool(self.cfg.get("random_fkey_enable", False))

    def _random_fkey_delay(self):
        lo = max(0.1, float(self.cfg.get("random_fkey_min", 1.0) or 0.1))
        hi = max(0.1, float(self.cfg.get("random_fkey_max", 120.0) or 0.1))
        if hi < lo: lo, hi = hi, lo
        return random.uniform(lo, hi)

    def _random_fkey(self):
        f3_pct = max(0.0, min(100.0, float(self.cfg.get("random_fkey_f3_pct", 50.0) or 0.0)))
        return "f3" if random.random() * 100.0 < f3_pct else "f7"

    def _press_for(self, key, duration):
        try:
            eng.pdi.keyDown(key)
            until = time.monotonic() + max(0.0, duration)
            while not self.stop_flag and not self.pause_flag:
                left = until - time.monotonic()
                if left <= 0: break
                time.sleep(min(0.03, left))
        finally:
            try: eng.pdi.keyUp(key)
            except Exception: pass

    def _cast_heal(self, count=1):
        self.set_hold(None)
        if self._roll_hold("heal_hold_chance_pct"):
            duration = self._hold_duration()
            self._press_for(self.cfg["heal_key"], duration)
            return "按住%.2fs" % duration
        eng.tap(self.cfg["heal_key"], count, self.cfg.get("heal_tap_gap", 0.05))
        return "轻点x%d" % count

    def _cast_claw(self, side):
        self.set_hold(None)
        try: eng.pdi.keyDown(side)
        except Exception: pass
        mode = "轻点x%d" % self.cfg["claw_taps"]
        try:
            time.sleep(self.cfg.get("turn_hold", 0.06))
            if self._roll_hold("claw_hold_chance_pct"):
                duration = self._hold_duration()
                self._press_for(self.cfg["claw_key"], duration)
                mode = "按住%.2fs" % duration
            else:
                eng.tap(self.cfg["claw_key"], self.cfg["claw_taps"], self.cfg["claw_tap_gap"])
        finally:
            try: eng.pdi.keyUp(side)
            except Exception: pass
        self.facing = side; self.held = None
        return mode

    def _target_offset(self):
        """返回当前中心偏移。只在随机化开启时定期重掷,关闭时立即归零。"""
        amount = max(0.0, float(self.cfg.get("center_offset_mm", 0.0) or 0.0))
        if not self._random_enabled() or amount <= 0.0:
            self._center_offset = 0.0; self._next_center_offset = 0.0
            return 0.0
        now = time.monotonic()
        if now >= self._next_center_offset:
            self._center_offset = random.uniform(-amount, amount)
            lo = max(0.1, float(self.cfg.get("center_offset_period_min", 5.0) or 0.1))
            hi = max(0.1, float(self.cfg.get("center_offset_period_max", 12.0) or 0.1))
            if hi < lo: lo, hi = hi, lo
            self._next_center_offset = now + random.uniform(lo, hi)
        # 运行中把范围调小后,当前目标也立刻回到新范围内。
        self._center_offset = max(-amount, min(amount, self._center_offset))
        return self._center_offset

    def _dot_world(self, dot):
        s = self.cfg.get("mm_scale")
        if not s or dot is None: return None
        return (dot[0]/s*16.0 - self.nav.cX, dot[1]/s*16.0 - self.nav.cY)

    def _center_calc(self, dot):
        """算居中偏移。返回 (回中该按的方向 or None, 偏离绝对值 off_mm[小地图px等效])。
        优先手动占位点 hold_dot(最稳);否则小地图平台中点;否则世界坐标平台中心;无定位视为已居中。"""
        cfg = self.cfg
        dz = cfg.get("center_dead_mm", 2)
        target_off = self._target_offset()
        hold = cfg.get("hold_dot")
        if dot is not None and hold is not None:
            target = float(hold[0]) + target_off
            L = cfg.get("sweep_L"); R = cfg.get("sweep_R"); pad = cfg.get("recenter_pad_mm", 3)
            if L is not None and R is not None and (R - L) >= 6:
                target = min(max(target, L + pad), R - pad)
            off = dot[0] - target
            d = "right" if off < -dz else ("left" if off > dz else None)
            self.mv_act = "占位Δ%+d 目标%+.1f" % (int(off), target_off)
            return d, abs(off)
        L = cfg.get("sweep_L"); R = cfg.get("sweep_R")
        if dot is not None and L is not None and R is not None and (R - L) >= 6:
            pad = cfg.get("recenter_pad_mm", 3)
            c = min(max((L + R) / 2.0 + target_off, L + pad), R - pad)
            x = min(max(dot[0], L + pad), R - pad); off = x - c
            d = "right" if off < -dz else ("left" if off > dz else None)
            self.mv_act = "居中mmΔ%+d 目标%+.1f" % (int(dot[0] - c), target_off)
            return d, abs(off)
        W = self._dot_world(dot)
        if W is not None:
            wx, wy = W; cur = self.nav.plat_at(wx, wy, cfg.get("plat_ytol", 55))
            if cur is not None:
                pad_world = max(0.0, cfg.get("recenter_pad_mm", 3)*16.0)
                lo, hi = cur["xl"] + pad_world, cur["xr"] - pad_world
                c = cur["cx"] + target_off*16.0
                c = min(max(c, lo), hi) if lo <= hi else cur["cx"]
                off = wx - c
                d = "right" if off < -dz*16 else ("left" if off > dz*16 else None)
                self.mv_act = "居中P%dΔ%+d 目标%+.1f" % (cur["i"], int(off), target_off)
                return d, abs(off) / 16.0
        self.mv_act = "居中:无定位"
        return None, 0.0

    def _push_dbg(self, now, anchor, dets, heal_n, act, dot, heal_box=None):
        if now - self._dbg < 0.05: return
        self._dbg = now
        self.on_debug({"fps": round(self.fps, 1), "anchor": anchor, "heal_box": heal_box,
                       "dets": [(d[0], d[1], d[3], round(d[2], 2)) for d in dets], "heal_n": heal_n,
                       "state": self.state, "act": act, "dot": dot,
                       "alert_box": self.alert_box, "alert_score": self.alert_score,
                       "alert_kind": self.alert_kind})

    def run(self):
        cfg = self.cfg
        hwnd, title = eng.find_game_hwnd(cfg["window_title_contains"])
        if not hwnd:
            self.log("找不到游戏窗口"); self.state = "NOWIN"; self.on_status(state="NOWIN"); return
        try: det = Detector(cfg)
        except Exception as e:
            self.log("检测器初始化失败: %s" % e); self.state = "ERROR"; self.on_status(state="ERROR"); return
        self.log("检测: %s" % ("GPU(cuda)" if det.gpu is not None else "CPU(cv2 回退)"))
        try:
            alert_det = AlertImageDetector(cfg)
            self._emit_alert("READY" if cfg.get("alert_enable", True) else "OFF", 0.0)
            self.log("图片报警检测已%s（%s）" % (
                "开启" if cfg.get("alert_enable", True) else "关闭", "、".join(alert_det.source_names)))
        except Exception as e:
            alert_det = None
            self._emit_alert("ERROR", 0.0)
            self.log("图片报警检测不可用: %s" % e)
        grab = eng.Grabber(); mmt = eng.MinimapTracker(cfg)
        self.log("锁定窗口:%s。请点游戏窗口置顶。" % title)

        hotkeys = {}
        next_heal = next_claw = 0.0; hp_last = mp_last = 0.0; last_pickup = 0.0
        next_random_fkey = None; last_alert_scan = 0.0
        while not self.stop_flag:
            if eng.key_edge(hotkeys, "F12"): break
            if eng.key_edge(hotkeys, "F9"): self.toggle_pause()
            try: region = eng.client_region(hwnd)
            except Exception: self.log("窗口丢失"); break
            now = time.time(); monitor_frame = None
            scan_gap = max(0.05, float(cfg.get("alert_scan_interval", 0.18) or 0.18))
            if now-last_alert_scan >= scan_gap:
                last_alert_scan = now
                if alert_det is not None and cfg.get("alert_enable", True):
                    monitor_frame = grab.grab(region)
                self._check_alert(alert_det, monitor_frame)
            if self.pause_flag:
                next_random_fkey = None
                self.state = "PAUSED"; self.on_status(state="PAUSED"); time.sleep(0.2); continue
            if not eng.is_foreground(hwnd):
                next_random_fkey = None
                self._release(); self.state = "WAIT_FOCUS"; self.on_status(state="WAIT_FOCUS")
                time.sleep(0.12); continue

            random_key_act = ""
            if self._random_fkey_enabled():
                if next_random_fkey is None:
                    next_random_fkey = now + self._random_fkey_delay()
                elif now >= next_random_fkey:
                    key = self._random_fkey(); eng.tap(key)
                    delay = self._random_fkey_delay(); next_random_fkey = time.time() + delay
                    random_key_act = "随机按%s" % key.upper()
                    self.log("%s（下次 %.1fs 后）" % (random_key_act, delay))
            else:
                next_random_fkey = None
            if self._t is not None:
                dt = now - self._t
                if dt > 0: self.fps = 0.85*self.fps + 0.15*(1.0/dt)
            self._t = now
            frame = monitor_frame if monitor_frame is not None else grab.grab(region)
            if frame is None: time.sleep(0.006); continue
            H, W = frame.shape[:2]; sx, sy = W/1366.0, H/768.0
            dot = mmt.dot(frame)
            # 锚点: 有世界定位则两轴都摄像机夹取(靠边/到顶到底镜头不居中→锚点自动偏);否则固定比例
            wc = self._dot_world(dot)
            ax, ay = _screen_anchor(wc, W, H, sx, sy, self.nav.vr, cfg)

            # HP/MP
            hp_r, mp_r = eng.read_bars_ratio(frame, cfg.get("bars_region"))
            if hp_r is not None and hp_r < cfg["hp_ratio_thresh"] and now-hp_last > cfg["potion_cooldown"]:
                eng.tap(cfg["hp_key"]); hp_last = now
            if mp_r is not None and mp_r < cfg["mp_ratio_thresh"] and now-mp_last > cfg["potion_cooldown"]:
                eng.tap(cfg["mp_key"]); mp_last = now

            # 检测 ROI
            reach = int(max(cfg["heal_x"], cfg["claw_range"]) * sx) + 60
            x0 = max(0, ax-reach); x1 = min(W, ax+reach)
            top = ay - int(max(cfg["band_up"], cfg["heal_up"]) * sy) - 20
            bot = ay + int(max(cfg["band_down"], cfg["heal_down"], cfg["claw_y_tol"]) * sy) + 20
            band = (max(0, top), min(H, bot))
            dets = det.detect(frame, band, x0, x1)
            # 治愈矩形AoE(以脚下为心): 横±heal_x, 纵[-heal_up,+heal_down]
            hx = cfg["heal_x"]*sx; hup = cfg["heal_up"]*sy; hdn = cfg["heal_down"]*sy
            claw_r = cfg["claw_range"]*sx; claw_yt = cfg["claw_y_tol"]*sy
            monkeys, snakes, claw_targets = _combat_targets(
                dets, ax, ay, hx, hup, hdn, claw_r, claw_yt)

            # 居中优先:先算偏移。偏离超过容忍区→只回中不放技能(放技能会锁步导致回不来)
            move_dir, off_mm = self._center_calc(dot)
            cast_zone = cfg.get("cast_zone_mm", 5); claw_zone = cfg.get("center_dead_mm", 2)
            act = ""
            mk_n = len(monkeys)
            if off_mm > cast_zone:
                act = "回中优先"                           # 偏太多→专心走回中心
            elif mk_n >= 1 and now >= next_heal:
                burst = cfg.get("heal_burst", 1) if mk_n >= cfg["heal_min"] else 1
                cast_mode = self._cast_heal(burst)
                next_heal = time.time() + self._next_interval("heal_interval", "heal_interval_jitter_pct")
                act = "治愈x%d %s" % (mk_n, cast_mode)
            elif off_mm <= claw_zone and claw_targets and now >= next_claw:
                # 魔双会把人推离/锁步→只在站定居中时放
                tgt = min(claw_targets, key=lambda s: abs(s[0]-ax)); side = "left" if tgt[0] < ax else "right"
                cast_mode = self._cast_claw(side)
                next_claw = time.time() + self._next_interval("claw_interval", "claw_interval_jitter_pct")
                target_name = "猴" if tgt[3] == "monkey" else "蛇"
                act = "魔双%s:%s %s" % (target_name, side, cast_mode)

            if random_key_act:
                act = random_key_act + (" · " + act if act else "")

            # 移动放最后:帧末保持回中方向(偏就走回中心,居中则站定)
            self.set_hold(move_dir)
            act = (act + " · " if act else "") + self.mv_act

            self.state = "FARM"
            self.on_status(state="FARM", hp=hp_r, mp=mp_r, monkeys=mk_n, snakes=len(snakes), act=act,
                           dot=(int(dot[0]), int(dot[1])) if dot else None)
            self._push_dbg(now, (ax, ay), dets, mk_n, act, dot,
                           (int(ax-hx), int(ay-hup), int(ax+hx), int(ay+hdn)))
            if cfg.get("pickup_enable", True) and now-last_pickup >= cfg.get("pickup_interval", 0.45):
                eng.tap(cfg.get("pickup_key", "z")); last_pickup = now
            time.sleep(cfg.get("loop_sleep", 0.004))

        self._release(); self.alarm.stop(); self._emit_alert("STOPPED", self.alert_score)
        self.state = "STOPPED"; self.on_status(state="STOPPED"); self.log("已停止。")


def _match_minimap(frame, data_png):
    """用真实小地图模板(去了动点的平台schematic)边缘匹配到画面左上→(精确rect, scale, score)或 None。
    平台线条静态且独特,丛林背景匹配不上,比暗区检测可靠得多。"""
    data = cv2.imread(data_png)
    if data is None: return None
    dh, dw = data.shape[:2]; H, W = frame.shape[:2]
    y0 = 60
    roi = frame[y0:min(H, y0+340), 0:min(W, 340)]
    er = cv2.Canny(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), 40, 120).astype(np.float32)
    ed = cv2.Canny(cv2.cvtColor(data, cv2.COLOR_BGR2GRAY), 40, 120).astype(np.float32)
    best = None
    for s in np.arange(0.82, 1.22, 0.02):     # 模板已是屏幕尺寸→scale≈1
        tw, th = int(dw*s), int(dh*s)
        if th >= er.shape[0] or tw >= er.shape[1] or tw < 40: continue
        r = cv2.matchTemplate(er, cv2.resize(ed, (tw, th)), cv2.TM_CCORR_NORMED)
        _, mx, _, ml = cv2.minMaxLoc(r)
        if best is None or mx > best[0]: best = (mx, float(s), ml, (tw, th))
    if best is None or best[0] < 0.45: return None
    score, s, loc, (tw, th) = best
    return [int(loc[0]), int(loc[1]+y0), int(loc[0]+tw), int(loc[1]+y0+th)], round(float(s), 3), round(score, 3)


def calibrate(cfg, log=print):
    """校准: 真实小地图模板匹配定位(不靠暗区)+ mm_scale + 血蓝 + 当前平台扫界。匹配不上则沿用已存框。"""
    hwnd, _ = eng.find_game_hwnd(cfg["window_title_contains"])
    if not hwnd: log("找不到游戏窗口"); return False
    frame = eng.Grabber().grab(eng.client_region(hwnd)); H, W = frame.shape[:2]
    try:
        mmd = json.load(open(cfg["geo_path"], encoding="utf-8"))["miniMap"]
        canvas_w = max(1, round(mmd["width"]/16.0)); canvas_h = max(1, round(mmd["height"]/16.0))
    except Exception:
        canvas_w = canvas_h = 0
    pm = _match_minimap(frame, cfg.get("minimap_png", ""))
    if pm:
        cfg["minimap_rect"] = pm[0]
        rw = pm[0][2] - pm[0][0]
        cfg["mm_scale"] = round(rw/float(canvas_w), 3) if canvas_w else pm[1]
        log("小地图(真实模板匹配 score=%.2f)=%s mm_scale=%s" % (pm[2], pm[0], cfg["mm_scale"]))
    elif cfg.get("minimap_rect"):
        log("小地图模板没匹配上→沿用已存 minimap_rect=%s(位置固定,通常没问题)" % cfg["minimap_rect"])
    else:
        log("× 没匹配到小地图且无已存框。确保小地图显示、贴左上、无菜单遮挡"); return False
    # 当前平台左右扫界(黄点所在行的亮像素)→ sweep_L/R(居中的核心)
    mr = cfg["minimap_rect"]; d = eng.MinimapTracker(cfg).dot(frame)
    if d:
        mm = frame[mr[1]:mr[3], mr[0]:mr[2]]; Vm = cv2.cvtColor(mm, cv2.COLOR_BGR2HSV)[:, :, 2]
        px, py = int(d[0]), int(d[1]); bg = int(np.median(Vm[Vm < 120])) if np.any(Vm < 120) else 40
        fg = (Vm > bg+22).astype(np.uint8); mmh, mmw = mm.shape[:2]
        row = fg[max(0, py-1):min(mmh, py+9), :].max(axis=0) > 0
        xl = px
        while xl > 0 and row[xl-1]: xl -= 1
        xr = px
        while xr < mmw-1 and row[xr+1]: xr += 1
        cfg["sweep_L"], cfg["sweep_R"], cfg["home_y"] = int(xl), int(xr), int(py)
        log("当前平台 小地图局部 x[%d,%d] (黄点x=%d) 中点=%d" % (xl, xr, px, (xl+xr)//2))
    else:
        log("× 拿不到黄点, sweep 未定")
    cfg["bars_region"] = [573, 1059, 1229, 1152]
    hp, mp = eng.read_bars_ratio(frame, cfg["bars_region"]); log("血蓝 HP=%s MP=%s" % (hp, mp))
    cfg["anchor_x_frac"] = 0.5
    return True


def capture_hold(cfg, log=print):
    """把角色当前所在的小地图黄点记为固定占位点。之后工具一直把你保持在这个点(比自动找中点稳)。
    需先校准(拿到 minimap_rect)。站到你想守的位置再点。"""
    hwnd, _ = eng.find_game_hwnd(cfg["window_title_contains"])
    if not hwnd: log("找不到游戏窗口"); return False
    if not cfg.get("minimap_rect"):
        log("请先点【校准】(需先定位小地图),再初始化占位"); return False
    frame = eng.Grabber().grab(eng.client_region(hwnd))
    d = eng.MinimapTracker(cfg).dot(frame)
    if not d:
        log("× 拿不到小地图黄点(确保小地图显示、人物站好、无菜单遮挡)"); return False
    cfg["hold_dot"] = [int(d[0]), int(d[1])]
    log("已记录占位点 小地图(x=%d,y=%d) — 工具会把你保持在这。想换点:站好再点一次;取消:点【清除占位】。"
        % (int(d[0]), int(d[1])))
    return True


def clear_hold(cfg, log=print):
    cfg["hold_dot"] = None
    log("已清除占位点(回到自动找平台中点)")
    return True


def dump_minimap(cfg, log=print):
    """把左上角(含小地图)截下来存盘,并标出黄色/橙色掩膜与当前 minimap_rect,便于诊断黄点检测。"""
    hwnd, _ = eng.find_game_hwnd(cfg["window_title_contains"])
    if not hwnd: log("找不到游戏窗口"); return False
    frame = eng.Grabber().grab(eng.client_region(hwnd))
    H, W = frame.shape[:2]
    md = os.path.join(HERE, "mapdata")
    rw, rh = min(W, 900), min(H, 560)
    region = frame[0:rh, 0:rw].copy()
    cv2.imwrite(os.path.join(md, "_mm_region.png"), region)          # 原图(我读它看小地图和各色点)
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    yel = cv2.inRange(hsv, np.array((24, 140, 200)), np.array((36, 255, 255)))   # 当前"黄点"范围
    org = cv2.inRange(hsv, np.array((5, 140, 180)), np.array((22, 255, 255)))    # 橙色(队友?)
    vis = region.copy(); vis[yel > 0] = (0, 255, 255); vis[org > 0] = (0, 140, 255)
    r = cfg.get("minimap_rect")
    if r:
        cv2.rectangle(vis, (min(r[0], rw-1), min(r[1], rh-1)), (min(r[2], rw-1), min(r[3], rh-1)), (0, 255, 0), 2)
        d = eng.MinimapTracker(cfg).dot(frame)
        if d: cv2.circle(vis, (r[0]+int(d[0]), r[1]+int(d[1])), 7, (255, 0, 255), 2)
    cv2.imwrite(os.path.join(md, "_mm_masks.png"), vis)              # 掩膜可视化(黄=当前判黄,橙=橙)
    # —— 全屏 + 工具计算的锚点/治愈框(诊断靠边平台锚点对不上) ——
    sx, sy = W/1366.0, H/768.0
    nav = NavMap(cfg["geo_path"]); d2 = eng.MinimapTracker(cfg).dot(frame)
    s = cfg.get("mm_scale")
    wc = (d2[0]/s*16.0 - nav.cX, d2[1]/s*16.0 - nav.cY) if (s and d2) else None
    vr = nav.vr; swx = W/sx; swy = H/sy
    camx = min(max(wc[0]-swx/2.0, vr[0]), vr[2]-swx) if (wc and vr and (vr[2]-vr[0]) > swx) else None
    camy = min(max(wc[1]-swy/2.0, vr[1]), vr[3]-swy) if (wc and vr and (vr[3]-vr[1]) > swy) else None
    ax, ay = _screen_anchor(wc, W, H, sx, sy, vr, cfg)
    mode = "camclamp" if wc is not None else "fixed"
    hx = cfg["heal_x"]*sx; hup = cfg["heal_up"]*sy; hdn = cfg["heal_down"]*sy
    fv = frame.copy()
    cv2.line(fv, (W//2, 0), (W//2, H), (140, 140, 140), 1)                                   # 屏幕中线
    cv2.rectangle(fv, (int(ax-hx), int(ay-hup)), (int(ax+hx), int(ay+hdn)), (255, 255, 0), 3)  # 治愈框(青黄)
    cv2.line(fv, (0, H//2), (W, H//2), (140, 140, 140), 1)                                   # 屏幕横中线
    cv2.line(fv, (ax-40, ay), (ax+40, ay), (255, 0, 255), 3); cv2.line(fv, (ax, ay-40), (ax, ay+40), (255, 0, 255), 3)  # 锚点(洋红)
    cv2.putText(fv, "ax=%d ay=%d mid=(%d,%d) dot=%s wc=%s camx=%s camy=%s" % (
                ax, ay, W//2, H//2, (int(d2[0]), int(d2[1])) if d2 else None, (int(wc[0]), int(wc[1])) if wc else None,
                int(camx) if camx is not None else None, int(camy) if camy is not None else None),
                (24, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
    cv2.imwrite(os.path.join(md, "_frame_debug.png"), fv)
    log("诊断已存: _mm_region/_mm_masks/_frame_debug.png。全屏 mode=%s ax=%d ay=%d 屏中=(%d,%d) dot=%s wc=%s camx=%s camy=%s swx=%.0f swy=%.0f vr=%s。告诉我存好了。"
        % (mode, ax, ay, W//2, H//2, d2, (int(wc[0]), int(wc[1])) if wc else None,
           int(camx) if camx is not None else None, int(camy) if camy is not None else None, swx, swy, vr))
    return True


def run_farm(cfg):
    ctrl = MonkeyController(cfg, log=print)
    print("F9 暂停/继续 F12 退出。3 秒后开始…"); time.sleep(3); ctrl.run()


if __name__ == "__main__":
    run_farm(load_cfg())
