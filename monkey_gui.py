# -*- coding: utf-8 -*-
"""猴子沼泽地Ⅲ farm · 图形界面。双击 启动.bat(自动申请管理员权限)。
稳定站平台正中间;治愈(c)群秒僵尸猴 + 魔双(v)打青蛇;GPU 检测;调试层显示治愈框与检测。
"""
import os, sys, queue, threading, traceback, ctypes, datetime
import tkinter as tk
from tkinter import messagebox
import win32gui, win32con

import monkey_farm as mf

APPDIR = os.path.dirname(os.path.abspath(__file__))
CRASHLOG = os.path.join(APPDIR, "monkey_crash.log")


def _logexc(etype, evalue, etb):
    """把未捕获异常写到 monkey_crash.log(窗口崩掉也留证据)。"""
    try:
        with open(CRASHLOG, "a", encoding="utf-8") as f:
            f.write("\n==== %s ====\n" % datetime.datetime.now())
            traceback.print_exception(etype, evalue, etb, file=f)
    except Exception:
        pass
STATE_CN = {"IDLE": "空闲", "FARM": "运行中", "PAUSED": "已暂停", "WAIT_FOCUS": "等待游戏置顶",
            "STOPPED": "已停止", "NOWIN": "找不到窗口", "ERROR": "出错"}
ALERT_CN = {"OFF": "图片报警:关闭", "READY": "图片报警:待命", "ALARM": "⚠ 图片报警中",
            "ACK": "图片报警:已静音", "ERROR": "图片报警:模板错误", "STOPPED": "图片报警:已停止"}


class Overlay:
    """游戏上的调试叠加层:透明+点击穿透+置顶,且对截图/dxcam 隐身。"""
    def __init__(self, root):
        self.root = root; self.enabled = False; self._styled = False
        self.win = tk.Toplevel(root); self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", "#010101"); self.win.config(bg="#010101")
        self.canvas = tk.Canvas(self.win, bg="#010101", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.win.geometry("200x100+0+0"); self.win.withdraw()

    def _style(self):
        try:
            hwnd = win32gui.GetAncestor(self.win.winfo_id(), win32con.GA_ROOT)
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            ex |= (win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT
                   | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)   # WDA_EXCLUDEFROMCAPTURE
            self._styled = True
        except Exception:
            pass

    def set_enabled(self, on):
        self.enabled = bool(on)
        if self.enabled:
            self.win.deiconify(); self.win.lift()
            if not self._styled:
                self.win.after(60, self._style)
        else:
            self.win.withdraw()

    def set_geometry(self, region):
        if self.enabled:
            self.win.geometry("%dx%d+%d+%d" % (region["width"], region["height"], region["left"], region["top"]))
            self.win.lift()

    def draw(self, d):
        if not self.enabled: return
        c = self.canvas; c.delete("all")
        ax, ay = d.get("anchor", (0, 0))
        box = d.get("heal_box")
        if box:
            c.create_rectangle(box[0], box[1], box[2], box[3], outline="#00e5ff", width=2)   # 治愈矩形AoE
        alert_box = d.get("alert_box")
        if alert_box:
            c.create_rectangle(alert_box[0], alert_box[1], alert_box[2], alert_box[3],
                               outline="#ff1b1b", width=5)
            c.create_text(alert_box[0]+4, max(6, alert_box[1]-24),
                          text="报警%s %.3f" % (d.get("alert_kind", "图"), d.get("alert_score", 0.0)), anchor="nw",
                          fill="#ff3030", font=("Consolas", 14, "bold"))
        c.create_line(ax-16, ay, ax+16, ay, fill="#ff2fd0", width=2)   # 角色锚点
        c.create_line(ax, ay-16, ax, ay+16, fill="#ff2fd0", width=2)
        for (x, y, lab, sc) in d.get("dets", []):
            col = "#3bd0ff" if lab == "monkey" else "#ff3bef"
            c.create_oval(x-16, y-16, x+16, y+16, outline=col, width=2)
            c.create_text(x, y-18, text="%s%.2f" % ("猴" if lab == "monkey" else "蛇", sc),
                          fill=col, font=("Consolas", 10))
        info = "FPS %.0f | %s | %s | 框内僵尸猴%d" % (
            d.get("fps", 0), STATE_CN.get(d.get("state", ""), d.get("state", "")), d.get("act", ""), d.get("heal_n", 0))
        c.create_rectangle(6, 6, 24+len(info)*11, 34, fill="#000000", outline="")
        c.create_text(12, 10, text=info, anchor="nw", fill="#00ff66", font=("Consolas", 13, "bold"))


class App:
    def __init__(self, root):
        self.root = root
        root.title("猴子沼泽地Ⅲ farm(治愈僵尸猴 / 魔双青蛇 · GPU)")
        try:
            dpi = root.winfo_fpixels("1i")
            if dpi and dpi > 0: root.tk.call("tk", "scaling", dpi/72.0)
        except Exception: pass
        self.cfg = mf.load_cfg(); self.q = queue.Queue()
        sound_path = self.cfg.get("alert_sound")
        self.alarm = mf.AlarmPlayer(sound_path); self.test_alarm_player = mf.AlarmPlayer(sound_path)
        self.ctrl = None; self.thread = None; self.running = False
        self.overlay = Overlay(root)
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_window(); self.root.after(100, self._drain)

    def _build(self):
        pad = {"padx": 6, "pady": 3}
        self.win_var = tk.StringVar(value="窗口:查找中…")
        tk.Label(self.root, textvariable=self.win_var, anchor="w").pack(fill="x", **pad)
        self.state_var = tk.StringVar(value="状态:空闲  |  检测:%s" % ("GPU" if mf._HAS_GPU else "CPU回退"))
        tk.Label(self.root, textvariable=self.state_var, anchor="w", fg="#0a0").pack(fill="x", **pad)
        self.info_var = tk.StringVar(value="HP - | MP - | 僵尸猴 - | 青蛇 - | -")
        tk.Label(self.root, textvariable=self.info_var, anchor="w").pack(fill="x", **pad)

        bf = tk.Frame(self.root); bf.pack(fill="x", **pad)
        tk.Button(bf, text="▶ 开始", width=8, command=self.start).pack(side="left", padx=2)
        tk.Button(bf, text="⏸ 暂停/继续", width=11, command=self.pause).pack(side="left", padx=2)
        tk.Button(bf, text="■ 停止", width=8, command=self.stop).pack(side="left", padx=2)
        bf2 = tk.Frame(self.root); bf2.pack(fill="x", **pad)
        tk.Button(bf2, text="🎯 校准", width=9, command=self.calibrate).pack(side="left", padx=2)
        tk.Button(bf2, text="📍 初始化占位", width=12, command=self.capture_hold).pack(side="left", padx=2)
        tk.Button(bf2, text="清除占位", width=8, command=self.clear_hold).pack(side="left", padx=2)
        tk.Button(bf2, text="🔬 诊断小地图", width=12, command=self.dump_minimap).pack(side="left", padx=2)
        self.dbg_var = tk.BooleanVar(value=False)
        tk.Checkbutton(bf2, text="调试层", variable=self.dbg_var, command=self._toggle_overlay).pack(side="left", padx=6)

        af = tk.Frame(self.root); af.pack(fill="x", **pad)
        self.alert_var = tk.BooleanVar(value=bool(self.cfg.get("alert_enable", True)))
        tk.Checkbutton(af, text="启用图片报警", variable=self.alert_var).pack(side="left", padx=2)
        tk.Label(af, text="相似度≥").pack(side="left", padx=(8, 1))
        self.alert_thresh_var = tk.StringVar(value=str(self.cfg.get("alert_threshold", 0.76)))
        tk.Entry(af, textvariable=self.alert_thresh_var, width=6).pack(side="left")
        tk.Button(af, text="🔊 测试3秒", command=self.test_alarm).pack(side="left", padx=6)
        tk.Button(af, text="🔕 停止报警", command=self.stop_alarm).pack(side="left", padx=2)
        self.alert_state_var = tk.StringVar(value=ALERT_CN["READY"] if self.alert_var.get() else ALERT_CN["OFF"])
        self.alert_label = tk.Label(af, textvariable=self.alert_state_var, fg="#b00020", anchor="w")
        self.alert_label.pack(side="left", padx=8)

        tk.Label(self.root, text="占位用法:先校准 → 站到你想守的点 → 点「初始化占位」→ 开始。  治愈=c 魔双=v 血=1 蓝=2",
                 fg="#888", anchor="w").pack(fill="x", **pad)

        pf = tk.LabelFrame(self.root, text="参数(改完点应用,运行中即时生效)"); pf.pack(fill="x", **pad)
        self.fields = {}
        rows = [("monkey_thresh", "僵尸猴阈值"), ("snake_thresh", "青蛇阈值"), ("match_scale", "屏上尺度"),
                ("heal_x", "治愈半宽"), ("heal_up", "治愈·上"), ("heal_down", "治愈·下"),
                ("heal_min", "触发最少猴"), ("heal_burst", "连打次数"), ("heal_interval", "治愈间隔s"),
                ("claw_range", "魔双射程px"), ("claw_interval", "魔双间隔s"),
                ("center_dead_mm", "站定容差px"), ("cast_zone_mm", "回中优先区px"), ("pickup_interval", "捡物间隔s")]
        for i, (k, cn) in enumerate(rows):
            r = tk.Frame(pf); r.grid(row=i//2, column=i % 2, sticky="w", padx=6, pady=2)
            tk.Label(r, text=cn+":", width=12, anchor="e").pack(side="left")
            v = tk.StringVar(value=str(self.cfg.get(k, "")))
            tk.Entry(r, textvariable=v, width=8).pack(side="left"); self.fields[k] = v
        self.pick_var = tk.BooleanVar(value=bool(self.cfg.get("pickup_enable", True)))
        tk.Checkbutton(pf, text="捡物(z)", variable=self.pick_var).grid(row=7, column=0, sticky="w", padx=6)
        tk.Button(pf, text="应用参数", command=self.apply_settings).grid(row=7, column=1, sticky="e", padx=6)

        rf = tk.LabelFrame(self.root, text="随机化（按住占比=每次施法采用连续按键的概率）")
        rf.pack(fill="x", **pad)
        self.random_var = tk.BooleanVar(value=bool(self.cfg.get("randomize_enable", False)))
        tk.Checkbutton(rf, text="启用随机化", variable=self.random_var).grid(
            row=0, column=0, sticky="w", padx=6, pady=2)
        self.fkey_var = tk.BooleanVar(value=bool(self.cfg.get("random_fkey_enable", False)))
        tk.Checkbutton(rf, text="随机按F3/F7", variable=self.fkey_var).grid(
            row=0, column=1, sticky="w", padx=6, pady=2)
        tk.Button(rf, text="应用随机设置", command=self.apply_settings).grid(
            row=0, column=2, sticky="e", padx=8, pady=2)
        self.random_fields = {}
        random_rows = [
            ("heal_hold_chance_pct", "治愈按住占比%"), ("claw_hold_chance_pct", "魔双按住占比%"),
            ("skill_hold_min", "按住最短s"), ("skill_hold_max", "按住最长s"),
            ("heal_interval_jitter_pct", "治愈间隔±%"), ("claw_interval_jitter_pct", "魔双间隔±%"),
            ("center_offset_mm", "中心偏移±px"), ("center_offset_period_min", "换点最短s"),
            ("center_offset_period_max", "换点最长s"), ("random_fkey_min", "F键最短s"),
            ("random_fkey_max", "F键最长s"), ("random_fkey_f3_pct", "F3占比%")]
        for i, (k, cn) in enumerate(random_rows):
            rr, cc = divmod(i, 3)
            cell = tk.Frame(rf); cell.grid(row=rr+1, column=cc, sticky="w", padx=4, pady=2)
            tk.Label(cell, text=cn+":", width=13, anchor="e").pack(side="left")
            v = tk.StringVar(value=str(self.cfg.get(k, "")))
            tk.Entry(cell, textvariable=v, width=7).pack(side="left"); self.random_fields[k] = v
        tk.Label(rf, text="提示：按住/间隔/中心/F键均需启用总开关；F3占比50表示F3、F7各一半。",
                 fg="#777", anchor="w").grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 4))

        self.log_txt = tk.Text(self.root, height=7, width=62); self.log_txt.pack(fill="both", expand=True, **pad)
        self._log("就绪。步骤:进游戏站到要farm的平台 → 🎯校准 → 勾调试层核对治愈框/检测 → ▶开始 → 点游戏置顶。")

    def _log(self, s):
        self.log_txt.insert("end", s+"\n"); self.log_txt.see("end")

    def start(self):
        if self.running: return
        self.test_alarm_player.stop()
        self.apply_settings(silent=True)
        try:
            self.ctrl = mf.MonkeyController(self.cfg, log=lambda s: self.q.put(("log", s)),
                                            on_status=lambda **k: self.q.put(("status", k)),
                                            on_debug=lambda d: self.q.put(("debug", d)),
                                            on_alert=lambda **k: self.q.put(("alert", k)), alarm=self.alarm)
        except Exception as e:
            messagebox.showerror("启动失败", str(e)); self._log("启动失败:%s" % traceback.format_exc()); return
        self.running = True
        self.thread = threading.Thread(target=self._run_ctrl, daemon=True); self.thread.start()
        self._log("已开始。请点游戏窗口置顶。F9 暂停/继续,F12 停止。")

    def _run_ctrl(self):
        try: self.ctrl.run()
        except Exception:
            _logexc(*sys.exc_info())
            self.q.put(("log", "运行异常:%s" % traceback.format_exc()))
        self.alarm.stop()
        self.running = False

    def pause(self):
        if self.ctrl: self.ctrl.toggle_pause()

    def stop(self):
        if self.ctrl: self.ctrl.stop()
        self.alarm.stop(); self.test_alarm_player.stop()
        self.alert_state_var.set(ALERT_CN["STOPPED"])
        self.running = False

    def test_alarm(self):
        if self.running:
            self._log("请先停止 farm，再测试报警声音")
            return
        if self.test_alarm_player.playing: return
        self.test_alarm_player.start(); self._log("报警声音测试开始（3秒后自动停止）")
        self.root.after(3000, self._finish_alarm_test)

    def _finish_alarm_test(self):
        self.test_alarm_player.stop(); self._log("报警声音测试结束")

    def stop_alarm(self):
        self.alarm.stop(); self.test_alarm_player.stop()
        if self.ctrl: self.ctrl.acknowledge_alert()
        else: self.alert_state_var.set(ALERT_CN["READY"] if self.alert_var.get() else ALERT_CN["OFF"])

    def calibrate(self):
        def job():
            try:
                ok = mf.calibrate(self.cfg, log=lambda s: self.q.put(("log", s)))
                if ok:
                    mf.save_cfg(self.cfg); self.q.put(("log", "校准完成并保存。勾调试层核对。"))
            except Exception:
                self.q.put(("log", "校准异常:%s" % traceback.format_exc()))
        threading.Thread(target=job, daemon=True).start()

    def capture_hold(self):
        def job():
            try:
                ok = mf.capture_hold(self.cfg, log=lambda s: self.q.put(("log", s)))
                if ok:
                    mf.save_cfg(self.cfg)
                    if self.ctrl: self.ctrl.cfg = self.cfg      # 运行中即时生效
            except Exception:
                self.q.put(("log", "初始化占位异常:%s" % traceback.format_exc()))
        threading.Thread(target=job, daemon=True).start()

    def clear_hold(self):
        mf.clear_hold(self.cfg, log=lambda s: self.q.put(("log", s)))
        mf.save_cfg(self.cfg)
        if self.ctrl: self.ctrl.cfg = self.cfg

    def dump_minimap(self):
        def job():
            try:
                mf.dump_minimap(self.cfg, log=lambda s: self.q.put(("log", s)))
            except Exception:
                self.q.put(("log", "诊断异常:%s" % traceback.format_exc()))
        threading.Thread(target=job, daemon=True).start()

    def apply_settings(self, silent=False):
        bad = []
        for k, v in self.fields.items():
            s = v.get().strip()
            if s == "": continue
            try:
                self.cfg[k] = int(s) if k in ("heal_min", "heal_burst", "center_dead_mm", "cast_zone_mm") else float(s)
            except Exception: bad.append(k)
        for k, v in self.random_fields.items():
            s = v.get().strip()
            if s == "": continue
            try: self.cfg[k] = float(s)
            except Exception: bad.append(k)
        self.cfg["pickup_enable"] = bool(self.pick_var.get())
        self.cfg["randomize_enable"] = bool(self.random_var.get())
        self.cfg["random_fkey_enable"] = bool(self.fkey_var.get())
        self.cfg["alert_enable"] = bool(self.alert_var.get())
        try:
            self.cfg["alert_threshold"] = max(0.3, min(0.99, float(self.alert_thresh_var.get().strip())))
            self.cfg["alert_patch_threshold"] = min(0.99, self.cfg["alert_threshold"] + 0.04)
        except Exception:
            bad.append("alert_threshold")
        self.alert_thresh_var.set(str(self.cfg.get("alert_threshold", 0.76)))
        # 限制到有意义且安全的范围；最短/最长填反时自动交换。
        for k in ("heal_hold_chance_pct", "claw_hold_chance_pct",
                  "heal_interval_jitter_pct", "claw_interval_jitter_pct", "random_fkey_f3_pct"):
            self.cfg[k] = max(0.0, min(100.0, float(self.cfg.get(k, 0.0) or 0.0)))
        for k in ("skill_hold_min", "skill_hold_max", "center_offset_mm"):
            self.cfg[k] = max(0.0, float(self.cfg.get(k, 0.0) or 0.0))
        if self.cfg["skill_hold_max"] < self.cfg["skill_hold_min"]:
            self.cfg["skill_hold_min"], self.cfg["skill_hold_max"] = (
                self.cfg["skill_hold_max"], self.cfg["skill_hold_min"])
        for k in ("center_offset_period_min", "center_offset_period_max"):
            self.cfg[k] = max(0.1, float(self.cfg.get(k, 0.1) or 0.1))
        if self.cfg["center_offset_period_max"] < self.cfg["center_offset_period_min"]:
            self.cfg["center_offset_period_min"], self.cfg["center_offset_period_max"] = (
                self.cfg["center_offset_period_max"], self.cfg["center_offset_period_min"])
        for k in ("random_fkey_min", "random_fkey_max"):
            self.cfg[k] = max(0.1, float(self.cfg.get(k, 0.1) or 0.1))
        if self.cfg["random_fkey_max"] < self.cfg["random_fkey_min"]:
            self.cfg["random_fkey_min"], self.cfg["random_fkey_max"] = (
                self.cfg["random_fkey_max"], self.cfg["random_fkey_min"])
        for k, v in self.random_fields.items(): v.set(str(self.cfg[k]))
        mf.save_cfg(self.cfg)
        if self.ctrl: self.ctrl.cfg = self.cfg
        if not self.running:
            self.alert_state_var.set(ALERT_CN["READY"] if self.cfg["alert_enable"] else ALERT_CN["OFF"])
        if not silent:
            mode = "开" if self.cfg["randomize_enable"] else "关"
            fkeys = "开" if self.cfg["random_fkey_enable"] else "关"
            self._log("参数已应用（随机化:%s，随机F3/F7:%s，治愈/魔双按住占比:%g%%/%g%%，中心偏移:±%gpx）%s" % (
                mode, fkeys, self.cfg["heal_hold_chance_pct"], self.cfg["claw_hold_chance_pct"],
                self.cfg["center_offset_mm"],
                "；这些格式错误已跳过:%s" % "、".join(bad) if bad else ""))

    def _toggle_overlay(self):
        self.overlay.set_enabled(self.dbg_var.get())
        if self.dbg_var.get():
            hwnd, _ = mf.eng.find_game_hwnd(self.cfg["window_title_contains"])
            if hwnd: self.overlay.set_geometry(mf.eng.client_region(hwnd))

    def _poll_window(self):
        hwnd, title = mf.eng.find_game_hwnd(self.cfg["window_title_contains"])
        if hwnd:
            r = mf.eng.client_region(hwnd)
            self.win_var.set("窗口:%s  %dx%d" % (title, r["width"], r["height"]))
            self.overlay.set_geometry(r)
        else:
            self.win_var.set("窗口:未找到")
        self.root.after(1000, self._poll_window)

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                try:
                    if kind == "log": self._log(payload)
                    elif kind == "status":
                        st = payload.get("state", "")
                        self.state_var.set("状态:%s  |  检测:%s" % (STATE_CN.get(st, st), "GPU" if mf._HAS_GPU else "CPU回退"))
                        self.info_var.set("HP %s | MP %s | 僵尸猴 %s | 青蛇 %s | %s" % (
                            _pct(payload.get("hp")), _pct(payload.get("mp")),
                            payload.get("monkeys", "-"), payload.get("snakes", "-"), payload.get("act", "-")))
                    elif kind == "debug": self.overlay.draw(payload)
                    elif kind == "alert":
                        ast = payload.get("state", "READY")
                        score = payload.get("score", 0.0)
                        suffix = " %.3f" % score if ast in ("ALARM", "ACK") else ""
                        self.alert_state_var.set(ALERT_CN.get(ast, ast) + suffix)
                except Exception:
                    pass
        except queue.Empty:
            pass
        finally:
            try: self.root.after(60, self._drain)
            except tk.TclError: pass

    def on_close(self):
        if self.ctrl: self.ctrl.stop()
        self.alarm.stop(); self.test_alarm_player.stop()
        self.root.after(250, self.root.destroy)


def _pct(x):
    return "-" if x is None else "%d%%" % round(x*100)


def main():
    sys.excepthook = _logexc                                          # 主线程未捕获异常→写日志
    try:
        threading.excepthook = lambda a: _logexc(a.exc_type, a.exc_value, a.exc_traceback)
    except Exception:
        pass
    root = tk.Tk(); App(root); root.mainloop()


if __name__ == "__main__":
    main()
