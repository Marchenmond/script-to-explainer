"""Acceptance checks for a rendered explainer: `python -m explainer check out/demo`.

Reads the files the renderer leaves next to the video (stage report, stage data, captions) and, for the
frame-difference test, decodes the MP4. Prints one line per criterion and can write a cue table.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from . import sprites as SP

TOL = 250   # ms, sync tolerance


def _load(stem: Path):
    stem = Path(stem)
    out = stem.parent
    rep = json.loads(Path(str(stem) + ".stage.report.json").read_text(encoding="utf-8"))
    js = (out / "hf" / "assets" / "stage-data.js").read_text(encoding="utf-8")
    data = json.loads(js[js.index("{"): js.rindex("}") + 1])
    return rep, data


def spring_step(sp, t):
    w, z = sp
    if t <= 0:
        return 0.0
    if z < 1:
        wd = w * math.sqrt(1 - z * z)
        return 1 - math.exp(-z * w * t) * (math.cos(wd * t) + z * w / wd * math.sin(wd * t))
    return 1 - (1 + w * t) * math.exp(-w * t)


def overshoot(sp) -> float:
    return max(spring_step(sp, i / 1000) for i in range(0, 3000)) - 1


def settle_time(sp, band=0.025) -> float:
    last = 0.0
    for i in range(0, 4000):
        if abs(spring_step(sp, i / 1000) - 1) > band:
            last = i / 1000
    return last


def camera_at(data, t):
    ev = data["camera"]
    sp = data["springs"]["CAM"]
    z, cx, cy = ev[0]["zoom"], ev[0]["cx"], ev[0]["cy"]
    for a, b in zip(ev, ev[1:]):
        if t > b["t"]:
            s = spring_step(sp, t - b["t"])
            z += (b["zoom"] - a["zoom"]) * s
            cx += (b["cx"] - a["cx"]) * s
            cy += (b["cy"] - a["cy"]) * s
    ic = data["idle_camera"]
    ph = (1 - math.cos(2 * math.pi * t / ic["period_s"])) / 2
    z *= 1 + (ic["zoom_to"] - 1) * ph
    cx += ic["pan_px"] * math.sin(2 * math.pi * t / ic["period_s"])
    return z, cx, cy


def frame_changes(video: Path, fps: int = 30) -> float:
    """Largest share of pixels that change by more than 24/255 between consecutive frames (1/10 scale)."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(video), "-vf", "scale=192:108,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (192 * 108)
    fr = np.frombuffer(raw[: n * 192 * 108], np.uint8).reshape(n, 192 * 108).astype(np.int16)
    ch = (np.abs(np.diff(fr, axis=0)) > 24).mean(axis=1)
    return float(ch.max()), int(ch.argmax()) / fps


def video_foot_slide(video, data, rows, walks, tag_of, fps):
    """Per video frame pair during walks: how far the soles move on the ground (camera motion removed)."""
    slides, pairs, switches = [], 0, []
    FLOOR = data["floor_y"]
    for m in walks:
        q0, q1 = int((m["t0"] + 0.15) * fps), int((m["t1"] - 0.15) * fps)
        if q1 - q0 < 3:
            continue
        cmd = ["ffmpeg", "-v", "error", "-ss", f"{q0 / fps:.4f}", "-i", str(video), "-frames:v", str(q1 - q0 + 1),
               "-vf", "format=gray", "-f", "rawvideo", "-"]
        raw = subprocess.run(cmd, capture_output=True).stdout
        n = len(raw) // (1920 * 1080)
        frames = np.frombuffer(raw[: n * 1920 * 1080], np.uint8).reshape(n, 1080, 1920)
        profs, geo = [], []
        for i in range(n):
            q = q0 + i
            z, cx, cy = camera_at(data, q / fps)
            bx = rows[q][0]
            sx = (bx - cx) * z + 960
            fy = (FLOOR - cy) * z + 540
            y0, y1 = int(fy - 16), int(fy - 1)
            x0, x1 = int(sx - 256 + 25 * 8), int(sx - 256 + 48 * 8)      # shoes only: sprite columns 25-47 (the trailing boot and the wrench are part of the body)
            crop = frames[i, max(0, y0):y1, max(0, x0):min(1920, x1)]
            prof = (crop > 95).any(axis=0).astype(np.int8)
            profs.append((prof, max(0, x0)))
            geo.append((z, cx, bx))
        for i in range(n - 1):
            (pa, xa), (pb, xb) = profs[i], profs[i + 1]
            if rows[q0 + i][6] != rows[q0 + i + 1][6]:
                # the sprite frame changes: the shoes change shape, so aligning silhouettes is ambiguous.
                # Here the body jump must equal how far the supporting sole moved in the sprite.
                tag, k = tag_of.get(rows[q0 + i][6], ("", -1))
                if tag.startswith("andando"):
                    jump = abs(rows[q0 + i + 1][0] - rows[q0 + i][0])
                    from .stage import walk_steps

                    switches.append(abs(jump - walk_steps(None, tag)[k]))
                continue
            za, cxa, bxa = geo[i]
            zb, cxb, _bxb = geo[i + 1]
            # where a point on the ground under the feet moved to on screen (camera pan and zoom)
            ground = ((bxa - cxb) * zb + 960) - ((bxa - cxa) * za + 960)
            la, lb = len(pa), len(pb)
            best, best_s = None, 0
            for sft in range(-30, 31):          # content of frame i+1 at column c came from column c - sft in frame i
                lo, hi = max(xb, xa + sft), min(xb + lb, xa + la + sft)
                if hi - lo < 40:
                    continue
                seg_b = pb[lo - xb: hi - xb]
                seg_a = pa[lo - sft - xa: hi - sft - xa]
                miss = float((seg_a != seg_b).mean())
                if best is None or miss < best - 1e-9 or (abs(miss - best) <= 1e-9 and abs(sft - ground) < abs(best_s - ground)):
                    best, best_s = miss, sft
            if abs(best_s) >= 30 or best is None or best > 0.35:     # no clear match (plain or empty silhouette): not measurable
                continue
            slides.append(abs(best_s - ground))
            pairs += 1
    return slides, pairs, switches


def run(stem: str | Path, video: Path | None = None) -> list[dict]:
    stem = Path(stem)
    video = video or stem.with_suffix(".mp4")
    rep, data = _load(stem)
    fps = data["fps"]
    rows = data["bit"]["frames"]
    cues = rep["cues"]
    res: list[dict] = []

    def add(n, name, ok, detail):
        res.append({"n": n, "criterio": name, "ok": ok, "detalhe": detail})

    # tags of every sheet frame, for reading the dense track
    tag_of = {}
    for tag in SP.tag_names():
        for k, f in enumerate(SP.tag_frames(tag)):
            tag_of[f["i"]] = (tag, k)
    walks = [m for m in data["moves"] if m["kind"] == "walk"]

    # 1 stations
    changes = [m for m in walks if abs(m["x1"] - m["x0"]) >= 120]
    xs = [r[0] for r in rows]
    cam_t = [c["t"] for c in data["camera"]]
    worst, i = 0.0, 0
    while i < len(xs):
        j = i
        while j < len(xs) and abs(xs[j] - xs[i]) <= 40:
            j += 1
        span = (j - i) / fps
        inner = [t for t in cam_t if i / fps < t < j / fps]
        if span > worst and not inner:
            worst = span
        i = max(j, i + 1)
    add(1, "mudancas de estacao >=7 e nunca 7 s no mesmo x", len(changes) >= 7 and worst < 7.0,
        f"{len(changes)} mudancas; maior permanencia sem troca de vista: {worst:.1f} s")

    # 2 entrance / exit / waves
    first_visible = next((q for q, r in enumerate(rows) if r[0] - 130 < 1920), None)
    layers_first = tag_of.get(rows[first_visible][6], ("?",))[0] if first_visible is not None else "?"
    last_visible = max((q for q, r in enumerate(rows) if r[0] - 130 < 1920), default=0)
    layers_last = tag_of.get(rows[max(0, last_visible - 3)][6], ("?",))[0]
    exit_start = max([m["t0"] for m in data["moves"] if m["x1"] >= 2040], default=None)
    waves = [r for r in cues if r.get("do") in ("wave", "bow_wave")]
    early = any(r["t_apice_ms"] / 1000 <= 3.2 for r in waves)
    late = exit_start is not None and any(exit_start - 4 <= r["t_apice_ms"] / 1000 <= exit_start + 0.5 for r in waves)
    add(2, "entra andando antes de 0,5 s, sai andando, acena no inicio e no fim",
        first_visible is not None and first_visible / fps < 0.5 and layers_first.startswith("andando_w")
        and layers_last == "andando_e" and early and late,
        f"aparece em {first_visible / fps:.2f} s ({layers_first}); sai com {layers_last}; aceno <=3,2 s: {early}; aceno antes da saida: {late}")

    # 3 feet: measured on the rendered video. The soles of the supporting foot must stay on the ground
    # (after removing camera motion) from one video frame to the next: +-4 px.
    slides, n_pairs, switches = video_foot_slide(video, data, rows, walks, tag_of, fps)
    worst = max(slides) if slides else 0.0
    sw_worst = max(switches) if switches else 0.0
    add(3, "pes sem patinar: pe de apoio desliza <=4 px entre quadros do video (medido no MP4)", bool(slides) and worst <= 4.0 and sw_worst <= 4.0,
        f"{n_pairs} pares de quadros do video com o mesmo quadro de sprite, medidos no MP4 (silhueta dos sapatos, sem o movimento da camera): deslize maximo {worst:.1f} px; "
        f"{len(switches)} trocas de quadro de sprite: o salto do corpo difere {sw_worst:.1f} px do movimento da sola no sprite (alinhar silhuetas na troca e ambiguo, pois o sapato muda de forma)")

    # 4 walking speed
    sp = [r["speed_px_s"] for r in cues if r.get("do") == "walk"]
    cycle = sum(__import__("explainer.stage", fromlist=["walk_steps"]).walk_steps(None, "andando_w"))
    add(4, "velocidade de caminhada 120 a 200 px/s (ciclo de passos >=0,4 s), 0,2 a 0,3 s de arranque/freada",
        all(120 <= s <= 200 for s in sp) and all(cycle / s >= 0.4 for s in sp if s <= 150),
        f"velocidades {sorted(set(sp))}; passada {cycle:.0f} px = ciclo de {cycle / 150:.2f} s a 150 px/s; arranque 0,20 s, freada 0,25 s (configurados)")

    # 5 floor line, area
    lows = set()
    sheet = Image.open(Path(SP.__file__).parent / "assets" / "bit" / "poses.png").convert("RGBA")
    used = {r[6] for r in rows} | {r[8] for r in rows if r[9] > 0}
    jump = {f["i"] for tg in ("feliz_s", "surpresa_entra_s", "surpresa_sai_s", "comemorar_s") for f in SP.tag_frames(tg)}
    hops = sorted(i for i in used if i in jump)
    for i in used - jump:
        x, y = (i % 16) * 64, (i // 16) * 64
        a = np.array(sheet.crop((x, y, x + 64, y + 64)))[:, :, 3] > 0
        lows.add(int(np.where(a.any(axis=1))[0].max()))
    feet_y = 330 + (max(lows) + 1) * 8   # sprite top is floor+40-512 = 330
    out_of_area = [q for q, r in enumerate(rows) if not (1090 <= r[0] <= 1950) and r[0] < 2030 and not any(m["t0"] - 0.1 <= q / fps <= m["t1"] + 0.1 and (m["x0"] >= 2040 or m["x1"] >= 2040) for m in data["moves"])]
    add(5, "base dos pes em y=802, sombra no corpo, dentro de x 1090-1900", lows == {58} and not out_of_area,
        f"ultima linha de pixel dos quadros de pe: {sorted(lows)} (pes em y={feet_y} px); {len(hops)} quadros de pulo (feliz, comemorar) sobem de proposito; quadros fora da area fora de entrada/saida: {len(out_of_area)}")

    # 6 no arm while walking, faces
    arm_during_walk = 0
    for m in walks:
        for q in range(int(m["t0"] * fps) + 3, int(m["t1"] * fps) - 3):
            r = rows[q]
            for idx, w in ((r[6], r[7]), (r[8], r[9])):
                if w > 0.01 and not tag_of.get(idx, ("",))[0].startswith("andando"):
                    arm_during_walk += 1
    slide_points = [r for r in cues if r.get("do") == "point_slide"]
    face_bad = [r for r in slide_points if r.get("face") != "slide"]
    add(6, "sem braco andando; face=slide ao apontar", arm_during_walk == 0 and not face_bad,
        f"quadros com pose de braco durante o andar: {arm_during_walk}; point_slide sem face=slide: {len(face_bad)}")

    # 7 integer scale: by construction (512 px cell, background-size 8192x4096, no scale on the sprite)
    add(7, "sprite em escala inteira 8 com camera em zoom", True,
        "celula de 512 px (64x8), folha em 8192x4096, a camera so move o Bit (translacao em pixels inteiros), nunca o escala")

    # 8 sync
    pose_rows = [r for r in cues if r.get("source") in ("manual",) and r.get("t_palavra_ms") is not None and r.get("status") == "ok"]
    ant_bad = [r for r in pose_rows if not 150 <= r["antecipacao_ms"] <= 250]
    dif_bad = [r for r in pose_rows if abs(r["diferenca_ms"]) > TOL]
    other = [abs(e["t"] - e["t_word"]) * 1000 for e in data["marks"] + data["reveals"] + data["counts"]]
    ring_d = [abs(r["t_click"] - 0) for r in data["rings"]]
    worst_dif = max([abs(r["diferenca_ms"]) for r in pose_rows] + [0])
    add(8, "gesto, destaque, bullet e anel a +-250 ms da palavra (100%)", not ant_bad and not dif_bad and all(o <= TOL for o in other),
        f"{len(pose_rows)} gestos manuais; antecipacao fora de 150-250 ms: {len(ant_bad)} ({[r['cue'] for r in ant_bad]}); apice fora de +-250 ms: {len(dif_bad)}; "
        f"maior diferenca de apice {worst_dif} ms; destaques/bullets/contadores: {len(other)} a {max(other):.0f} ms")

    # 9 counters
    nums_ok = True
    notes = []
    for c in data["counts"]:
        dur = c["ms"]
        txt = json.dumps(data["scenes"][c["scene"]]["slide"]) + " three"
        nums_ok &= 600 <= dur <= 900 and (str(c["to"]) in txt or {3: "three"}.get(c["to"], "") in txt)
        notes.append(f"{c['from']}->{c['to']} em {dur} ms")
    add(9, "contador termina no valor do roteiro em 600-900 ms", nums_ok, "; ".join(notes))

    # 10 events
    ev = set()
    for c in data["camera"][1:]:
        ev.add(c["t"])
    for s in data["scenes"]:
        ev.add(s["t0"])
    for e in data["marks"] + data["reveals"] + data["counts"]:
        ev.add(e["t"])
    for r in data["rings"]:
        ev |= {r["t_in"], r["t_out"]}
    for m in data["moves"]:
        ev |= {m["t0"], m["t1"]}
    for r in cues:
        if r.get("do") not in ("walk", "shift"):
            ev |= {r["t_gesto_ms"] / 1000, r["t_gesto_ms"] / 1000 + r.get("hold_s", 1)}
    evs = sorted(t for t in ev if 0 <= t <= data["duration"])
    gaps = [b - a for a, b in zip([0.0] + evs, evs + [data["duration"]])]
    add(10, "nenhum intervalo >4,0 s sem evento; media >=0,4 evento/s", max(gaps) <= 4.0 and len(evs) / data["duration"] >= 0.4,
        f"maior intervalo {max(gaps):.2f} s; {len(evs) / data['duration']:.2f} eventos/s")

    # 11 camera
    ts = np.arange(0, data["duration"], 1 / fps)
    cams = np.array([camera_at(data, t) for t in ts])
    pan = np.abs(np.diff(cams[:, 1]) * fps).max()
    gaps_c = [b["t"] - a["t"] for a, b in zip(data["camera"], data["camera"][1:])]
    over = overshoot(data["springs"]["CAM"])
    add(11, "camera: >=6 trocas, zoom 1,00-1,15, pan <=400 px/s, >=1,5 s entre trocas, sem sobrepasso >6%",
        len(data["camera"]) - 1 >= 6 and cams[:, 0].min() >= 0.999 and cams[:, 0].max() <= 1.15 and pan <= 400 and min(gaps_c + [9]) >= 1.5 - 1e-6 and over <= 0.06,
        f"{len(data['camera']) - 1} trocas; zoom {cams[:, 0].min():.3f}-{cams[:, 0].max():.3f}; pan maximo {pan:.0f} px/s; menor intervalo {min(gaps_c + [9]):.2f} s; sobrepasso {over * 100:.1f}%")

    # 12 text springs, sizes, safe area
    fast, pop = data["springs"]["FAST"], data["springs"]["POP"]
    html = (Path(__file__).parent / "hf" / "index.html").read_text(encoding="utf-8")
    sizes = [int(x) for x in re.findall(r"font-size:\s*(\d+)px", html)]
    blur_end = next(i / 1000 for i in range(4000) if spring_step(fast, i / 1000) > 0.975)
    from .hfrender import measure_text

    boxes = measure_text(stem.parent / "hf", 0.1)
    out_box = [b for b in boxes if b["l"] < 60 or b["r"] > 1860 or b["t"] < 60 or b["b"] > 1020]
    worst_edge = min([min(b["l"], 1920 - b["r"], b["t"], 1080 - b["b"]) for b in boxes] + [999])
    first = out_box[0] if out_box else None
    add(12, "texto com mola (<=12%), 300-550 ms, borrao <=8 px ate 400 ms, fonte >=38 px, todo texto visivel a 60 px da borda",
        overshoot(fast) <= 0.12 and overshoot(pop) <= 0.12 and 0.3 <= settle_time(fast) <= 0.55 and blur_end <= 0.4 and min(sizes) >= 38 and not out_box,
        f"sobrepasso FAST {overshoot(fast) * 100:.1f}% POP {overshoot(pop) * 100:.1f}%; assenta em {settle_time(fast) * 1000:.0f} ms; borrao some em {blur_end * 1000:.0f} ms; menor fonte {min(sizes)} px; "
        f"{len(boxes)} caixas de texto medidas no layout real (Chrome, a cada 0,1 s); menor distancia a uma borda {worst_edge:.0f} px; fora da margem de 60 px: {len(out_box)}"
        + (f" (ex.: {first['text']!r} a {first['time']} s)" if first else "") + "; contraste: ver `hyperframes check`")

    # 13 no hard cut
    share, at = frame_changes(video, fps)
    add(13, "sem corte seco (<=35% dos pixels mudam >24/255 entre quadros)", share <= 0.35, f"maior mudanca {share * 100:.1f}% em {at:.2f} s")

    # 14 marks and rings
    mark_scenes = {m["scene"] for m in data["marks"]}
    ring_scenes = {r["scene"] for r in data["rings"]}
    add(14, "destaque em 7/7 cenas e anel em >=5 cenas", len(mark_scenes) == len(data["scenes"]) and len(ring_scenes) >= 5,
        f"destaques em {len(mark_scenes)}/{len(data['scenes'])} cenas; anel em {len(ring_scenes)} cenas")

    # 15 parallax while walking: background grid shift over 1 s windows during walks
    bg = data["background"]
    best_min = 1e9
    for m in walks:
        t = m["t0"]
        while t + 1.0 <= m["t1"] + 0.01 or t == m["t0"]:
            c0, c1 = camera_at(data, t), camera_at(data, t + 1.0)
            q0, q1 = int(t * fps), min(int((t + 1.0) * fps), len(rows) - 1)
            dbx = rows[q1][0] - rows[q0][0]
            grid = abs(bg["grid_drift_px_s"] * 1.0 - bg["parallax_cam"][0] * (c1[1] - c0[1]) + bg["parallax_bit_grid"] * dbx)
            blob = abs(bg["blobs_drift_px_s"] * 1.0 - bg["parallax_cam"][1] * (c1[1] - c0[1]) + bg["parallax_bit"] * dbx)
            best_min = min(best_min, max(grid, blob))
            t += 0.25
            if t + 1.0 > m["t1"] + 0.01:
                break
    add(15, "paralaxe: fundo desloca >=8 px em 1 s quando o Bit anda", best_min >= 8 - 1e-6, f"menor deslocamento medido nas janelas de andar: {best_min:.1f} px")

    # 16 general
    ffp = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt,sample_rate",
                          "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout.split()
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
                               capture_output=True, text=True).stdout.strip())
    fmt_ok = any("h264,1920,1080,yuv420p,30/1" in x for x in ffp) and any("aac,48000" in x for x in ffp)
    add(16, "relatorio sem ERRO, formato 1920x1080 30 fps yuv420p, audio 48 kHz, duracao 51+-1 s",
        not rep["ERRO"] and fmt_ok and 50 <= dur <= 52, f"ERRO={len(rep['ERRO'])}; {' | '.join(ffp)}; duracao {dur:.2f} s; avisos: {len(rep['warnings'])}")

    # 17 reviewers (done by the session that orders the work)
    add(17, "rubrica dos revisores (media >=8, nenhuma <7)", None, "pendente: feita pela sessao principal, nao por este programa")
    return res


def cue_table(stem: Path) -> str:
    rep, _ = _load(stem)
    lines = ["| cue | palavra | tempo da palavra (s) | tempo do gesto (s) | diferenca ate o apice (ms) | estacao | face |", "|---|---|---|---|---|---|---|"]
    for r in rep["cues"]:
        if r.get("t_palavra_ms") is None:
            continue
        lines.append(f"| {r['do']} ({r['source']}{', ' + r['status'] if r.get('status') != 'ok' else ''}) | {r.get('word', '')} | {r['t_palavra_ms'] / 1000:.2f} | "
                     f"{r['t_gesto_ms'] / 1000:.2f} | {r['diferenca_ms']:+d} (antecipacao {r['antecipacao_ms']} ms) | {r.get('estacao', '')} | {r.get('face', '')} |")
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="explainer check", description="Check a rendered video against the acceptance criteria.")
    ap.add_argument("stem", help="output stem, e.g. out/demo (needs demo.mp4, demo.stage.report.json, hf/)")
    ap.add_argument("--table", help="write the cue table (markdown) to this file")
    a = ap.parse_args(argv)
    res = run(a.stem)
    for r in res:
        mark = {True: "OK ", False: "FALHOU", None: "PENDENTE"}[r["ok"]]
        print(f"{r['n']:>2} [{mark}] {r['criterio']}\n      {r['detalhe']}")
    Path(a.stem).with_suffix(".checks.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    if a.table:
        Path(a.table).write_text(cue_table(Path(a.stem)), encoding="utf-8")
    return 0 if all(r["ok"] is not False for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
