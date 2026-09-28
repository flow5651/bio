#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pymupdf, re, json, os

PDF = "/Users/fomenko75/Desktop/Khimia_Kolki_260422_132139.pdf"
OUT = os.path.dirname(os.path.abspath(__file__))
IMGDIR = os.path.join(OUT, "img")
os.makedirs(IMGDIR, exist_ok=True)

TOPICS = [
    ("1", "Способы выражения концентрации растворов"),
    ("2", "Основы титриметрического анализа"),
    ("3", "Водородный показатель (рН)"),
    ("4", "Буферные системы"),
    ("5", "Коллигативные свойства растворов"),
    ("6", "Гетерогенные равновесия"),
    ("7", "Комплексные соединения"),
]

ALL16 = [
    ("8", "Основы химической термодинамики"),
    ("9", "Основы химической кинетики"),
    ("10", "Окислительно-восстановительные реакции. Электродные и редокс-потенциалы"),
    ("11", "Поверхностные явления"),
    ("12", "Дисперсные системы"),
    ("13", "Химия липидов"),
    ("14", "Химия углеводов"),
    ("15", "Химия аминокислот, пептидов и белков"),
    ("16", "Химия нуклеиновых кислот"),
]
BOUNDS = TOPICS + ALL16  # full list used only to compute topic page bounds
OPT_RE = re.compile(r'^(\d{1,2})\)')
QRE = re.compile(r'^\s*(\d{1,3})\.\s+(.+)$')
FOOTER_RE = re.compile(r'^\d{1,3}$')

def norm(s):
    return re.sub(r'\s+', '', s).upper()

doc = pymupdf.open(PDF)
pages_h = [doc[i].rect.height for i in range(doc.page_count)]
page_scanned = []
for pi in range(doc.page_count):
    info = doc[pi].get_image_info()
    page_scanned.append(bool(any(i["bbox"][2] >= 540 and i["bbox"][0] <= 8 for i in info)))

# normalize page text for topic detection
page_text = []
for pi in range(doc.page_count):
    page_text.append(norm(doc[pi].get_text()))

# answers section: first page in last pages whose text contains ОТВЕТЫ
answer_page = None
for pi in range(155, doc.page_count):
    if "ОТВЕТЫ" in page_text[pi]:
        answer_page = pi
        break
if answer_page is None:
    for pi in range(1, doc.page_count):
        if "ОТВЕТЫ" in page_text[pi].split("СПИСОК")[0][:300]:
            answer_page = pi

# collect lines globally sorted by (page, y)
scanned = page_scanned
lines = []
for pi in range(doc.page_count):
    d = doc[pi].get_text("dict")
    for b in d["blocks"]:
        if "lines" not in b:
            continue
        for l in b["lines"]:
            spans = l["spans"]
            txt = "".join(s["text"] for s in spans).strip()
            if not txt:
                continue
            if FOOTER_RE.match(txt) and l["bbox"][1] > pages_h[pi] - 45:
                continue
            sizes = [s["size"] for s in spans]
            maxs = max(sizes)
            m = OPT_RE.match(txt)
            line = dict(
                page=pi, y=l["bbox"][1], y1=l["bbox"][3], x=l["bbox"][0],
                bold=any(s["flags"] & 16 for s in spans),
                symbol=any("Symbol" in s["font"] or "MTExtra" in s["font"] or "MTSYN" in s["font"] or "MTSY" in s["font"] for s in spans),
                small=any((s["size"] or 0) + 1.5 < maxs for s in spans),  # sub/superscript present
                opt=m.group(1) if m else None,
                text=txt,
            )
            lines.append(line)

lines.sort(key=lambda r: (r["page"], r["y"]))

# map topic page -> start index in lines
def first_line_at_or_after(page, y):
    for i, r in enumerate(lines):
        if r["page"] > page or (r["page"] == page and r["y"] >= y):
            return i
    return len(lines)

# locate topic start line index in body (pages before answers), using full 16-topic bounds
bounds_idx = []
search = 1  # skip TOC page
for tno, tname in BOUNDS:
    key = norm(tno + ". " + tname)
    found = None
    for j in range(search, len(lines)):
        if lines[j]["bold"] and re.match(r'^\s*' + tno + r'\.', lines[j]["text"]) and lines[j]["page"] < (answer_page or doc.page_count):
            # join consecutive bold lines (wrapped header)
            cand = norm(lines[j]["text"])
            k = j + 1
            while k < len(lines) and lines[k]["bold"] and lines[k]["page"] == lines[j]["page"] and lines[k]["y"] - lines[k - 1]["y1"] < 21:
                cand += norm(lines[k]["text"])
                k += 1
            if cand == key or cand.startswith(key[:30]):
                found = j
                break
    bounds_idx.append(found)
    if found is not None:
        search = found + 1

topic_start_idx = bounds_idx[:len(TOPICS)]
print("topic idx pages:", [(i + 1, (lines[v]["page"] + 1 if v is not None else None)) for i, v in enumerate(topic_start_idx)])

# determine topic header text (bold line matching QRE equal to header) to skip
topic_header_text = {}
for i, (tno, tname) in enumerate(TOPICS):
    if topic_start_idx[i] is None:
        continue
    for j in range(topic_start_idx[i], min(topic_start_idx[i] + 3, len(lines))):
        if lines[j]["bold"] and norm(lines[j]["text"]).startswith(norm(tno + ". " + tname)[:20]):
            topic_header_text[i] = norm(lines[j]["text"])
            break

# ---------- Answers parsing ----------

answers = {}  # topic index -> {qno: value}
cur_topic = None
answer_buf = {}
in_answers = False
for r in lines:
    if r["page"] < (answer_page or 0):
        continue
    # detect topic header inside answers
    t = norm(r["text"])
    if "ИСПОЛЬЗОВАННОЙЛИТЕРАТУРЫ" in t or t.startswith("СПИСОК"):
        break
    hit = False
    head = t
    mm = re.match(r'^\s*\d+\.\s*(.*)$', r["text"])
    if mm:
        head = norm(mm.group(1))
    for i, (tno, tname) in enumerate(BOUNDS):
        key = norm(tname)
        if r["bold"] and len(head) > 4 and (head == key or head.startswith(key[:25])):
            cur_topic = i
            hit = True
            break
    if hit:
        continue
    if cur_topic is not None:
        answer_buf.setdefault(cur_topic, []).append(r["text"])

for i, arr in answer_buf.items():
    joined = " ".join(arr)
    answers[i] = {}
    # tokens "qno. value;" possibly "qno.value;"
    toks = re.findall(r'(\d{1,3})\s*\.\s*([^;]+?)(?=\s*\d{1,3}\s*\.\s|;)', joined)
    for qno, val in toks:
        v = val.strip().rstrip('.')
        answers[i][int(qno)] = v

print("answers found topics:", sorted(answers.keys()))
for i in sorted(answers):
    print(" topic", i, "count", len(answers[i]))

# ---------- Questions ----------
def build_questions():
    data = []
    for ti, (tno, tname) in enumerate(TOPICS):
        s = topic_start_idx[ti]
        if s is None:
            continue
        e = bounds_idx[ti + 1] if ti + 1 < len(bounds_idx) and bounds_idx[ti + 1] is not None else len(lines)
        # build from authoritative answer-key qnums in order
        qnums = sorted(answers.get(ti, {}))
        titles = []
        for qn in qnums:
            pat = re.compile(r'^\s*' + str(qn) + r'\.\s*(\S.*)?$')
            j = None
            for x in range(s + 1, e):
                if lines[x]["bold"] and pat.match(lines[x]["text"]):
                    j = x
                    break
            if j is not None:
                titles.append((qn, j))
        qlist = []
        for k, (qno, qi) in enumerate(titles):
            qe = titles[k + 1][1] if k + 1 < len(titles) else e
            region = lines[qi:qe]
            opts = [r for r in region if r["opt"] is not None]
            correct = answers.get(ti, {}).get(qno)
            if correct is None:
                correct = ""
            rg_pages = set(r["page"] for r in region)
            messy = any(r["symbol"] or r["small"] for r in region)
            is_scan = all(page_scanned[p] for p in rg_pages)
            ys = [round(r["y"], 1) for r in region]
            frag = len(set(ys)) < len(ys)  # overlapping/scattered spans on same baseline
            opt_nums = [int(o["opt"]) for o in opts]
            nopts = max(opt_nums) if opt_nums else 0

            # classify
            if not opts:
                qtype = "fill"
            elif len(correct) > 1:
                qtype = "match"
            else:
                qtype = "single"

            need_image = (qtype in ("fill", "match")) or messy or is_scan or frag
            imgs = []
            if need_image:
                imgs = render_region(region, ti, k)
            else:
                # text question: parse stem + option text
                for o in opts:
                    pass  # handled below
                pass

            q = dict(id=qno, type=qtype, correct=correct)
            if qtype == "single" and not need_image:
                # rebuild options: accumulate continuation lines into current option
                cur_opt = None
                parts = {}
                stem_parts = []
                for r in region:
                    if r["opt"] is not None:
                        cur_opt = int(r["opt"])
                        parts[cur_opt] = re.sub(OPT_RE, '', r["text"]).strip()
                    elif cur_opt is None:
                        stem_parts.append(r["text"])
                    else:
                        parts[cur_opt] += ' ' + r["text"].strip()
                opts_dict = {}
                for num in sorted(parts):
                    opts_dict[str(num)] = re.sub(r'\s+', ' ', parts[num]).strip()
                q["opts"] = opts_dict
                q["nopts"] = nopts
                q["stem"] = re.sub(r'\s+', ' ', " ".join(stem_parts)).strip()
            else:
                q["nopts"] = nopts
                q["imgs"] = imgs
                if qtype == "match":
                    q["items"] = len(correct) if correct else 0
            qlist.append(q)
        data.append(dict(num=int(tno), title=tname, questions=qlist))
    return data

def render_region(region, ti, idx):
    # group by page, render each page slice full-width
    filenames = []
    x0, x1 = 45, 556
    by_page = {}
    for r in region:
        by_page.setdefault(r["page"], []).append(r)
    for pi in sorted(by_page):
        rs = by_page[pi]
        ymin = min(r["y"] for r in rs) - 4
        ymax = max(r["y1"] for r in rs) + 4
        ymax = min(ymax, pages_h[pi] - 30)
        clip = pymupdf.Rect(x0, max(0, ymin), x1, ymax)
        fname = "t%02d_q%03d" % (ti + 1, idx + 1)
        if len(by_page) > 1:
            fname += "_p%d" % (pi + 1)
        fname += ".png"
        doc[pi].get_pixmap(matrix=pymupdf.Matrix(3, 3), clip=clip, alpha=False).save(os.path.join(IMGDIR, fname))
        filenames.append(fname)
    return filenames

data = build_questions()
with open(os.path.join(OUT, "data.json"), "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=1)

tot = sum(len(t["questions"]) for t in data)
bytype = {}
for t in data:
    for q in t["questions"]:
        bytype[q["type"]] = bytype.get(q["type"], 0) + 1
print("total questions:", tot)
print("types:", bytype)
print("wrote data.json and rendered images")