# -*- coding: utf-8 -*-
"""从服务端 WZ XML 提取猴子沼泽地Ⅲ(107000403)几何→geo_107000403.json,
并据 footholds 合成小地图(定位用)。权威数据源:用户自建服 BeiDou WZ。"""
import sys, os, json
import xml.etree.ElementTree as ET
import numpy as np, cv2
sys.path.insert(0, r"C:\Workspace\subway_farm")
from navmap import NavMap

SDIR = r"D:\BeiDouGMS083\2.单机服务端及客户端\BeiDou-Server-1.10-x64\BeiDou-Server-1.10-x64"
MAPID = 107000403
MAPXML = os.path.join(SDIR, "wz", "Map.wz", "Map", "Map1", "%d.img.xml" % MAPID)
HERE = os.path.dirname(os.path.abspath(__file__))
OUTGEO = os.path.join(HERE, "mapdata", "geo_%d.json" % MAPID)
OUTMM = os.path.join(HERE, "mapdata", "minimap%d.png" % MAPID)


def g(node):
    return {c.get("name"): c.get("value") for c in node if c.tag in ("int", "string", "float", "short", "double")}


root = ET.parse(MAPXML).getroot()
info = g(root.find("./imgdir[@name='info']"))
vr = [int(info["VRLeft"]), int(info["VRTop"]), int(info["VRRight"]), int(info["VRBottom"])]
mm = g(root.find("./imgdir[@name='miniMap']"))
miniMap = {"centerX": int(mm["centerX"]), "centerY": int(mm["centerY"]),
           "width": int(mm["width"]), "height": int(mm["height"]), "mag": int(mm["mag"])}

# footholds: foothold → 层 → 组 → 条目
fhs = []
for layer in root.find("./imgdir[@name='foothold']"):
    for grp in layer:
        for f in grp:
            d = g(f)
            try:
                fhs.append({"id": int(f.get("name")),
                            "x1": int(d["x1"]), "y1": int(d["y1"]),
                            "x2": int(d["x2"]), "y2": int(d["y2"]),
                            "prev": int(d.get("prev", 0)), "next": int(d.get("next", 0))})
            except (KeyError, TypeError, ValueError):
                pass

ropes = []
lr = root.find("./imgdir[@name='ladderRope']")
for e in (lr if lr is not None else []):
    d = g(e)
    ropes.append({"x": int(d["x"]), "y1": int(d["y1"]), "y2": int(d["y2"])})

portals = []
for e in root.find("./imgdir[@name='portal']"):
    d = g(e)
    portals.append({"pn": d.get("pn"), "tm": int(d.get("tm", 999999999)),
                    "x": int(d["x"]), "y": int(d["y"])})

mobs = []
for e in root.find("./imgdir[@name='life']"):
    d = g(e)
    if d.get("type") == "m":
        mobs.append({"id": d.get("id"), "x": int(d["x"]), "y": int(d["y"])})

xs = [c for f in fhs for c in (f["x1"], f["x2"])]
ys = [c for f in fhs for c in (f["y1"], f["y2"])]
worldX = [min(min(xs), vr[0]), max(max(xs), vr[2])]
worldY = [min(min(ys), vr[1]), max(max(ys), vr[3])]

geo = {"map": MAPID, "worldX": worldX, "worldY": worldY,
       "footholds": fhs, "ropes": ropes, "portals": portals, "mobs": mobs,
       "miniMap": miniMap, "vr": vr}
json.dump(geo, open(OUTGEO, "w", encoding="utf-8"), ensure_ascii=False)
print("写出", OUTGEO, "| footholds", len(fhs), "ropes", len(ropes), "portals", len(portals), "mobs", len(mobs))
print("vr", vr, "worldX", worldX, "worldY", worldY, "miniMap", miniMap)

# ---- 合成小地图(WZ 画布尺寸, footholds ÷16 白线) ----
cw, ch = int(round(miniMap["width"] / 16.0)), int(round(miniMap["height"] / 16.0))
canvas = np.zeros((ch, cw, 3), np.uint8)
cX, cY = miniMap["centerX"], miniMap["centerY"]
def w2c(x, y): return (int(round((x + cX) / 16.0)), int(round((y + cY) / 16.0)))
for f in fhs:
    p1 = w2c(f["x1"], f["y1"]); p2 = w2c(f["x2"], f["y2"])
    cv2.line(canvas, p1, p2, (255, 255, 255), 1)
for r in ropes:
    cv2.line(canvas, w2c(r["x"], r["y1"]), w2c(r["x"], r["y2"]), (170, 170, 170), 1)
cv2.imwrite(OUTMM, canvas)
print("合成小地图", OUTMM, "尺寸", (cw, ch))

# ---- 平台分析 ----
nav = NavMap(geo)
print("\n平台数", len(nav.platforms), "| 各平台附近怪:")
def near_count(p, kind_ids):
    n = 0
    for m in mobs:
        if m["id"] in kind_ids and p["xl"] - 40 <= m["x"] <= p["xr"] + 40 and abs(m["y"] - p["y"]) <= 60:
            n += 1
    return n
rows = []
for p in nav.platforms:
    mk = near_count(p, {"4230101"}); sk = near_count(p, {"2130103"})
    if p["xr"] - p["xl"] >= 60 and (mk + sk) > 0:
        rows.append((mk + sk, p, mk, sk))
rows.sort(reverse=True, key=lambda r: r[0])
for tot, p, mk, sk in rows[:12]:
    print("  P%2d y=%5d x[%5d,%5d] 宽%4d 中心cx=%5d | 僵尸猴%2d 青蛇%2d" %
          (p["i"], p["y"], p["xl"], p["xr"], p["xr"] - p["xl"], p["cx"], mk, sk))
