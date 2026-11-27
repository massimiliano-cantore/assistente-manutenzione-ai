# ruff: noqa
"""PASSO 2 (su Kaggle, GPU T4 x2): classifica le pagine e legge le schede con Qwen2.5-VL-7B. Costo 0.

In un notebook Kaggle con il dataset aggiunto, acceleratore "GPU T4 x2" e Internet attivo, in una cella:
    !wget -q -N https://raw.githubusercontent.com/massimiliano-cantore/assistente-manutenzione-ai/main/archivio_schede/leggi_su_kaggle.py
    !wget -q -N https://raw.githubusercontent.com/massimiliano-cantore/assistente-manutenzione-ai/main/archivio_schede/prompt_scheda.py
    !ANNI=2025,2026 python leggi_su_kaggle.py
Il dataset può contenere direttamente i PDF (cartelle anno/mese/file.pdf, es. resi-pdf-2023-2025): le pagine si
ricavano qui. ANNI sceglie gli anni (dal percorso); MAX_SCHEDE=20 per una prova breve.
Opzionale: ADATTATORE=/kaggle/input/<dataset-lora> per usare il modello addestrato sulle vostre schede.

1. Classifica ogni pagina (DDT, scheda fronte, scheda retro, altro) con un'immagine piccola: ~3 s a pagina.
2. Raggruppa: scheda = pagina fronte + eventuale retro che segue nello stesso PDF.
3. Legge ogni scheda (fronte e retro) con lo stesso prompt del progetto Document AI: ~60 s a scheda.
4. Segna "da_controllare" quando il JSON non è valido, mancano campi stampati o il modello dichiara campi incerti.
Scrive /kaggle/working/schede.jsonl e riprende da dove era rimasto (le sessioni Kaggle durano al massimo 12 ore:
per continuare, aggiungi l'output della sessione precedente come input e rilancia).
"""
import subprocess
subprocess.run("pip install -q -U 'transformers>=4.49,<4.57' accelerate qwen-vl-utils peft", shell=True)

import csv, glob, json, os, re, shutil, sys, time  # noqa: E401,E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
csv_pagine = glob.glob("/kaggle/input/**/pagine.csv", recursive=True)
if csv_pagine:                      # dataset preparato sul PC con prepara_pagine.py
    DATI = os.path.dirname(csv_pagine[0])
    sys.path.insert(0, DATI)
    pagine = list(csv.DictReader(open(f"{DATI}/pagine.csv", encoding="utf-8")))
    CARTELLA_PAGINE = f"{DATI}/pagine"
else:                               # dataset con i PDF: si convertono le pagine qui
    subprocess.run("pip install -q pypdfium2", shell=True)
    import hashlib
    import pypdfium2 as pdfium
    ANNI = [a.strip() for a in os.environ.get("ANNI", "2025,2026").split(",") if a.strip()]
    CARTELLA_PAGINE = "/kaggle/working/pagine"
    os.makedirs(CARTELLA_PAGINE, exist_ok=True)
    pagine = []
    max_pdf = int(os.environ["MAX_SCHEDE"]) if os.environ.get("MAX_SCHEDE") else None   # prova breve: pochi PDF
    n_pdf = 0
    print("Converto le pagine dei PDF in immagini...", flush=True)
    for pdf in sorted(glob.glob("/kaggle/input/**/*.pdf", recursive=True) + glob.glob("/kaggle/input/**/*.PDF",
                                                                                         recursive=True)):
        parti = pdf.split("/")
        anno = next((x for x in parti if re.fullmatch(r"20\d\d", x)), "")
        if anno not in ANNI:
            continue
        mese = parti[parti.index(anno) + 1] if parti.index(anno) + 2 < len(parti) else ""
        if max_pdf and n_pdf >= max_pdf:
            break
        n_pdf += 1
        if n_pdf % 25 == 0:
            print(f"  ... {n_pdf} PDF convertiti ({len(pagine)} pagine)", flush=True)
        sigla = hashlib.sha1(pdf.encode()).hexdigest()[:10]
        try:
            doc = pdfium.PdfDocument(pdf)
        except Exception as e:
            print("PDF non letto:", pdf, e)
            continue
        for k in range(len(doc)):
            nome = f"{anno}_{sigla}_p{k + 1:03d}.jpg"
            f = f"{CARTELLA_PAGINE}/{nome}"
            if not os.path.exists(f):
                doc[k].render(scale=170 / 72, grayscale=True).to_pil().save(f, "JPEG", quality=82)
            pagine.append({"pagina": nome, "anno": anno, "mese": mese,
                           "file": "/".join(parti[parti.index(anno):]), "n": k + 1, "di": len(doc)})
    print(f"Anni {ANNI}: {len(pagine)} pagine da {len({p['file'] for p in pagine})} PDF", flush=True)
from prompt_scheda import PROMPT  # noqa: E402

OUT = "/kaggle/working/schede.jsonl"
CLASSI = "/kaggle/working/classi.json"
for vecchio in glob.glob("/kaggle/input/**/schede.jsonl", recursive=True) + glob.glob("/kaggle/input/**/classi.json",
                                                                                     recursive=True):
    dest = OUT if vecchio.endswith(".jsonl") else CLASSI
    if not os.path.exists(dest):       # ripresa da una sessione precedente
        shutil.copy(vecchio, dest)

import torch  # noqa: E402
from qwen_vl_utils import process_vision_info  # noqa: E402
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration  # noqa: E402

MODELLO = "Qwen/Qwen2.5-VL-7B-Instruct"
print("Carico il modello (la prima volta lo scarica: circa 16 GB, qualche minuto)...", flush=True)
model = Qwen2_5_VLForConditionalGeneration.from_pretrained(MODELLO, torch_dtype=torch.float16, device_map="auto")
if os.environ.get("ADATTATORE"):
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, os.environ["ADATTATORE"])
proc_grande = AutoProcessor.from_pretrained(MODELLO, min_pixels=256 * 28 * 28, max_pixels=1600 * 28 * 28)
proc_piccolo = AutoProcessor.from_pretrained(MODELLO, min_pixels=256 * 28 * 28, max_pixels=768 * 28 * 28)


def chiedi(immagini, testo, proc, max_token):
    contenuto = [{"type": "image", "image": "file://" + f} for f in immagini] + [{"type": "text", "text": testo}]
    msg = [{"role": "user", "content": contenuto}]
    t = proc.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
    img, vid = process_vision_info(msg)
    inp = proc(text=[t], images=img, videos=vid, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=max_token, do_sample=False, repetition_penalty=1.05)
    return proc.batch_decode(out[:, inp.input_ids.shape[1]:], skip_special_tokens=True)[0]


DOMANDA_CLASSE = ("Guarda la pagina e rispondi con UNA sola lettera.\n"
                  "A = in alto c'è un'intestazione stampata con 'Riparazione n.', 'Cliente', 'Articolo' (scheda di "
                  "riparazione OPERA, 'COPIA RIPARAZIONE') e sotto una tabella Codice/Descrizione/Intervento/Pz.\n"
                  "B = la pagina è soprattutto un grande riquadro NOTE scritto a mano, SENZA l'intestazione con cliente "
                  "e articolo (retro della scheda).\n"
                  "C = documento di trasporto, bolla, fattura, lettera, e-mail o modulo di un'altra azienda.\n"
                  "D = pagina bianca o altro.\n"
                  "Lettera:")
LETTERE = {"A": "FRONTE", "B": "RETRO", "C": "DDT", "D": "ALTRO"}

classi = json.load(open(CLASSI)) if os.path.exists(CLASSI) else {}
if classi and classi.get("_versione") != 3:     # classificate con la domanda vecchia: si rifanno
    classi = {}
classi["_versione"] = 3
t0 = time.time()
for i, p in enumerate(pagine):
    if p["pagina"] in classi:
        continue
    r = chiedi([f"{CARTELLA_PAGINE}/{p['pagina']}"], DOMANDA_CLASSE, proc_piccolo, 3).strip().upper()
    classi[p["pagina"]] = LETTERE.get(r[:1], "ALTRO")
    if i % 25 == 0:
        json.dump(classi, open(CLASSI, "w"))
        print(f"classificate {len(classi)}/{len(pagine)} ({time.time() - t0:.0f} s)", flush=True)
json.dump(classi, open(CLASSI, "w"))
valori = [v for k, v in classi.items() if k != "_versione"]
print("Classi:", {c: valori.count(c) for c in set(valori)}, flush=True)

# schede: FRONTE (+ RETRO che segue nello stesso PDF), oppure RETRO da solo (fronte mancante nella scansione)
schede, usate = [], set()
for i, p in enumerate(pagine):
    c = classi.get(p["pagina"])
    if p["pagina"] in usate or c not in ("FRONTE", "RETRO"):
        continue
    gruppo = [p["pagina"]]
    if c == "FRONTE" and i + 1 < len(pagine) and pagine[i + 1]["file"] == p["file"] \
            and classi.get(pagine[i + 1]["pagina"]) == "RETRO":
        gruppo.append(pagine[i + 1]["pagina"])
    usate.update(gruppo)
    schede.append({"id": p["pagina"][:-4], "file": p["file"], "anno": p["anno"], "mese": p["mese"],
                   "pagine": gruppo, "tipo": "fronte e retro" if len(gruppo) == 2 else
                   ("solo fronte" if c == "FRONTE" else "solo retro")})
if os.environ.get("MAX_SCHEDE"):
    schede = schede[:int(os.environ["MAX_SCHEDE"])]
print(len(schede), "schede da leggere", flush=True)

STAMPATI = ["riparazione_n", "articolo"]
fatti = {json.loads(r)["id"] for r in open(OUT)} if os.path.exists(OUT) else set()
with open(OUT, "a") as fo:
    for k, s in enumerate(schede):
        if s["id"] in fatti:
            continue
        t = time.time()
        grezzo = chiedi([f"{CARTELLA_PAGINE}/{x}" for x in s["pagine"]], PROMPT, proc_grande, 1400)
        m = re.search(r"\{.*\}", grezzo, re.S)
        try:
            pred = json.loads(m.group()) if m else None
        except json.JSONDecodeError:
            pred = None
        motivi = []
        if pred is not None:
            # righe vuote ripetute (il modello a volte continua a riempire la tabella)
            pred["righe"] = [r for r in (pred.get("righe") or []) if isinstance(r, dict) and
                             (r.get("codice") or r.get("descrizione"))]
            if pred.get("non_scheda"):
                pred, motivi = None, ["non è una scheda"]
            elif str(pred.get("ditta") or pred.get("cliente")) in ("John Doe", "Mario Rossi", "Compagnia Italiana") \
                    or any(str(r.get("descrizione", "")).startswith("Componente ") for r in pred["righe"]):
                pred, motivi = None, ["non è una scheda (risposta inventata dal modello)"]
            elif not re.fullmatch(r"\s*\d{1,4}\s*/\s*\d{1,4}\s*", str(pred.get("riparazione_n") or "")):
                if s["tipo"] == "solo retro":     # sul retro non c'è l'intestazione: valori inventati, si tolgono
                    for c in ("riparazione_n", "data", "ditta", "articolo", "prodotto_il", "seriale", "firmware",
                              "tempo_riparazione"):
                        pred[c] = None
                else:
                    motivi.append("numero riparazione non valido")
        if pred is None and motivi and motivi[0].startswith("non è una scheda"):
            print(f"{k + 1}/{len(schede)} {s['id']} scartata: {motivi[0]}", flush=True)
            fo.write(json.dumps({**s, "pred": None, "grezzo": None, "scartata": True, "da_controllare": False,
                                 "motivi": motivi}, ensure_ascii=False) + "\n")
            continue
        if pred is None and not motivi:
            motivi.append("JSON non valido")
        elif pred is not None:
            if s["tipo"] != "solo retro":          # sul retro non ci sono numero e articolo
                motivi += [f"manca {c}" for c in STAMPATI if not pred.get(c)]
            nota = str(pred.get("note") or "").strip().lower() not in ("", "null", "none")
            if not pred["righe"] and not nota:     # tabella vuota con le note è normale; senza niente no
                motivi.append("né righe né note")
            elif pred["righe"] and any(not str(r.get("codice") or "").strip() for r in pred["righe"]):
                motivi.append("righe senza codice")
            incerti_codici = [c for c in (pred.get("campi_incerti") or []) if "codice" in str(c)]
            if incerti_codici:
                motivi.append("codici incerti: " + ", ".join(map(str, incerti_codici))[:150])
        fo.write(json.dumps({**s, "pred": pred, "grezzo": None if pred else grezzo, "da_controllare": bool(motivi),
                             "motivi": motivi, "secondi": round(time.time() - t, 1)}, ensure_ascii=False) + "\n")
        fo.flush()
        print(f"{k + 1}/{len(schede)} {s['id']} {time.time() - t:.0f}s {'CONTROLLARE' if motivi else 'ok'}", flush=True)
print("Finito. Scarica /kaggle/working/schede.jsonl")
