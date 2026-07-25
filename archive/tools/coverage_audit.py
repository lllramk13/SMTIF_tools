# -*- coding: utf-8 -*-
"""干净扫描: 只保留"真对话"残留。判据: 含换行/名字宏 或 (高多样性+含多个助词), 排除单字重复。"""
import json, os
ROOT = r"P:\ROMHacking\SMT IF"
ORIG_TBL = os.path.join(ROOT,"PreWork","if备案","原始码表.txt")
m = json.load(open(os.path.join(ROOT,"extrac","_iso_manifest.json"), encoding="utf-8"))
RS=m["raw_sector_size"]; OFF=m["form1_user_offset"]; US=m["form1_user_size"]
IMG=os.path.join(ROOT,"Game","modified","SMT_IF_CN_config_status_subtitles.bin")
def load_orig():
    t={}
    for line in open(ORIG_TBL,encoding="utf-16-le").read().splitlines():
        k,_,v=line.strip("﻿").partition("=")
        k=k.strip()
        if len(k)==4:
            try: t[int.from_bytes(bytes.fromhex(k),"little")]=v
            except ValueError: pass
    return t
ORIG=load_orig()
KANA_CODES=set(c for c,ch in ORIG.items() if "぀"<=ch<="ヿ")
NL=0x03FF; TRI=0x01FF
NAME_MACROS={0x18FF,0x70FF,0x7BFF,0x1BFF,0x7AFF,0x7FFF,0x77FF,0x7DFF}
PARTICLES=set("はをのにがでとしなるからってただねよわも")
def extract(path):
    e=[x for x in m["entries"] if x.get("path")==path][0]
    lba=e["extent_lba"]; size=e["size"]; data=bytearray()
    with open(IMG,"rb") as f:
        sec=lba
        while len(data)<size:
            f.seek(sec*RS+OFF); data+=f.read(US); sec+=1
    return bytes(data[:size])
def scan(orig, inj):
    res=[]; L=len(orig); i=0
    start=None; codes=[]; has_nl=False; has_macro=False
    def flush(end):
        nonlocal start,codes,has_nl,has_macro
        if start is not None and len(codes)>=6:
            if orig[start:end]==inj[start:end]:
                chars=[ORIG[c] for c in codes if c in ORIG]
                if chars:
                    distinct=len(set(chars))/len(chars)
                    # 最长单字重复
                    maxrun=1;cur=1
                    for a,b in zip(chars,chars[1:]):
                        cur=cur+1 if a==b else 1; maxrun=max(maxrun,cur)
                    part=sum(1 for ch in chars if ch in PARTICLES)
                    real=len(chars)
                    ok = (has_nl or has_macro or (distinct>=0.5 and part>=2)) and maxrun<=4 and distinct>=0.35
                    if ok:
                        s=[]; j=start
                        while j<end:
                            c=orig[j]|(orig[j+1]<<8); j+=2
                            if c==0xFFFF: break
                            if c==NL: s.append("/")
                            elif c==TRI: s.append("|")
                            elif c in ORIG: s.append(ORIG[c])
                            elif (c&0xFF)==0xFF: s.append("{%04X}"%c)
                            else: s.append("〓")
                        res.append((start,"".join(s),real,part))
        start=None; codes=[]; has_nl=False; has_macro=False
    while i<L-1:
        c=orig[i]|(orig[i+1]<<8)
        if c==0xFFFF: flush(i); i+=2; continue
        if c==NL: has_nl=True; i+=2; continue
        if c==TRI: i+=2; continue
        if c in NAME_MACROS: has_macro=True; i+=2; continue
        if c in ORIG:
            if start is None: start=i
            codes.append(c); i+=2; continue
        if (c&0xFF)==0xFF:
            i+=2; continue
        flush(i); i+=2
    flush(L)
    return res
fpaths=sorted(set(e["path"] for e in m["entries"] if e.get("path","").startswith("D/F") and e["path"].endswith(".BIN")))
fpaths.append("SLPM_871.54")
rows=[]
for path in fpaths:
    try:
        o=open(os.path.join(ROOT,"extrac",*path.split("/")),"rb").read()
        j=extract(path)
    except Exception: continue
    if len(o)!=len(j): continue
    runs=scan(o,j)
    if runs: rows.append((path,len(runs),sum(r[2] for r in runs),runs))
rows.sort(key=lambda x:-x[2])
out=[f"{'文件':16}{'串':>6}{'真字':>8}"]
for p,n,rs,_ in rows: out.append(f"{p:16}{n:>6}{rs:>8}")
open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"clean_summary.txt"),"w",encoding="utf-8").write("\n".join(out))
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"clean_detail.txt"),"w",encoding="utf-8") as f:
    for p,n,rs,runs in rows:
        f.write(f"\n===== {p} ({n} runs / {rs} chars) =====\n")
        for off,s,real,part in runs:
            f.write(f"0x{off:06X} {s}\n")
print("done files:",len(rows))
