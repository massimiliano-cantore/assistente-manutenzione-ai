# ruff: noqa
"""PASSO 2 (su Kaggle, GPU T4 x2): classifica le pagine e legge le schede con Qwen2.5-VL-7B. Costo 0.

In un notebook Kaggle con il dataset privato aggiunto e l'acceleratore "GPU T4 x2", in una cella:
    !python /kaggle/input/<nome-dataset>/leggi_su_kaggle.py
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
DATI = os.path.dirname(glob.glob("/kaggle/input/**/pagine.csv", recursive=True)[0])
sys.path.insert(0, DATI)
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
model = Qwen2_5_VLForConditionalGeneration.from_pretrained(MODELLO, torch_dtype=torch.float16, device_map="auto")
if os.environ.get("ADATTATORE"):
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, os.environ["ADATTATORE"])
proc_grande = AutoProcessor.from_pretrained(MODELLO, min_pixels=256 * 28 * 28, max_pixels=1600 * 28 * 28)
proc_piccolo = AutoProcessor.from_pretrained(MODELLO, min_pixels=128 * 28 * 28, max_pixels=320 * 28 * 28)


def chiedi(immagini, testo, proc, max_token):
    contenuto = [{"type": "image", "image": "file://" + f} for f in immagini] + [{"type": "text", "text": testo}]
    msg = [{"role": "user", "content": contenuto}]
    t = proc.apply_chat_template(msg, tokenize=False, add_generation_prompt=True)
    img, vid = process_vision_info(msg)
    inp = proc(text=[t], images=img, videos=vid, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inp, max_new_tokens=max_token, do_sample=False)
    return proc.batch_decode(out[:, inp.input_ids.shape[1]:], skip_special_tokens=True)[0]


DOMANDA_CLASSE = ("Che pagina è? Rispondi con UNA parola: DDT (documento di trasporto / bolla), FRONTE (fronte di una "
                  "scheda di riparazione: intestazione con numero riparazione, cliente, articolo e tabella codici), "
                  "RETRO (retro della scheda: NOTE, continuazione tabella, eseguito il), ALTRO.")

pagine = list(csv.DictReader(open(f"{DATI}/pagine.csv", encoding="utf-8")))
classi = json.load(open(CLASSI)) if os.path.exists(CLASSI) else {}
t0 = time.time()
for i, p in enumerate(pagine):
    if p["pagina"] in classi:
        continue
    r = chiedi([f"{DATI}/pagine/{p['pagina']}"], DOMANDA_CLASSE, proc_piccolo, 5).upper()
    classi[p["pagina"]] = next((c for c in ("DDT", "FRONTE", "RETRO") if c in r), "ALTRO")
    if i % 100 == 0:
        json.dump(classi, open(CLASSI, "w"))
        print(f"classificate {len(classi)}/{len(pagine)} ({time.time() - t0:.0f} s)", flush=True)
json.dump(classi, open(CLASSI, "w"))
print("Classi:", {c: list(classi.values()).count(c) for c in set(classi.values())}, flush=True)

# schede: FRONTE + RETRO successivo nello stesso PDF
schede = []
for i, p in enumerate(pagine):
    if classi.get(p["pagina"]) != "FRONTE":
        continue
    retro = None
    if i + 1 < len(pagine) and pagine[i + 1]["file"] == p["file"] and classi.get(pagine[i + 1]["pagina"]) == "RETRO":
        retro = pagine[i + 1]["pagina"]
    schede.append({"id": p["pagina"][:-4], "file": p["file"], "anno": p["anno"], "mese": p["mese"],
                   "pagine": [p["pagina"]] + ([retro] if retro else [])})
print(len(schede), "schede da leggere", flush=True)

STAMPATI = ["riparazione_n", "data", "cliente", "articolo"]
fatti = {json.loads(r)["id"] for r in open(OUT)} if os.path.exists(OUT) else set()
with open(OUT, "a") as fo:
    for k, s in enumerate(schede):
        if s["id"] in fatti:
            continue
        t = time.time()
        grezzo = chiedi([f"{DATI}/pagine/{x}" for x in s["pagine"]], PROMPT, proc_grande, 1400)
        m = re.search(r"\{.*\}", grezzo, re.S)
        try:
            pred = json.loads(m.group()) if m else None
        except json.JSONDecodeError:
            pred = None
        motivi = []
        if pred is None:
            motivi.append("JSON non valido")
        else:
            motivi += [f"manca {c}" for c in STAMPATI if not pred.get(c)]
            if pred.get("campi_incerti"):
                motivi.append("incerti: " + ", ".join(map(str, pred["campi_incerti"]))[:200])
        fo.write(json.dumps({**s, "pred": pred, "grezzo": None if pred else grezzo, "da_controllare": bool(motivi),
                             "motivi": motivi, "secondi": round(time.time() - t, 1)}, ensure_ascii=False) + "\n")
        fo.flush()
        print(f"{k + 1}/{len(schede)} {s['id']} {time.time() - t:.0f}s {'CONTROLLARE' if motivi else 'ok'}", flush=True)
print("Finito. Scarica /kaggle/working/schede.jsonl")
