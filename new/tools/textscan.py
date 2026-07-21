#!/usr/bin/env python3
"""
文本侦探工具 —— 用来定位"名字/物品名/恶魔名"这类字符串存在哪。

原理：游戏里每个字 = 一个 2 字节小端编号，指向字库里的字形。
  - 原版文件里存的是【原版编号】(对应日文)。
  - 我们的字库把这些编号换成了中文字，所以未翻译的原版串就显示成错字。

两张表：
  - 原版码表 (PreWork/if备案/原始码表.txt)：编号 -> 原版日文。用来把原版文件解码成日文。
  - 我们的码表 (new/data/codetable.json)：编号 -> 我们的中文字。用来做"错字 -> 编号"反查。

用法（在 new/ 目录下跑）：
  python tools/textscan.py find  "弓子"        # 在所有文件里搜这个日文，报告 文件+偏移
  python tools/textscan.py decode F0077 0x1234  # 把某文件某偏移解码成日文(看那里是什么)
  python tools/textscan.py scan  F0077          # 把整个文件里能解码的日文串全列出来(找名字表)
  python tools/textscan.py rev   "男男听肚"      # 反查：屏幕上这些错字用的是哪些编号
  python tools/textscan.py slpm  0xE5C44         # 解码 SLPM 可执行文件某偏移
"""
import sys, os, json, glob

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # 项目根 P:\ROMHacking\SMT IF
EXTRAC = os.path.join(ROOT, 'extrac')
ORIG_TBL = os.path.join(ROOT, 'PreWork', 'if备案', '原始码表.txt')
OUR_TBL  = os.path.join(HERE, '..', 'data', 'codetable.json')
SLPM_LOAD = 0x8000F800   # SLPM 装入 RAM 的基址；文件偏移 = RAM地址 - 这个值


def load_orig():
    """原版：编号(int) -> 日文字"""
    t = {}
    for line in open(ORIG_TBL, encoding='utf-16-le').read().splitlines():
        k, _, v = line.strip('﻿').partition('=')
        k = k.strip()
        if len(k) == 4:
            try: t[int.from_bytes(bytes.fromhex(k), 'little')] = v
            except ValueError: pass
    return t

def load_ours():
    """我们的：字 -> 编号(int) 反查"""
    ct = json.load(open(OUR_TBL, encoding='utf-8'))
    rev = {}
    for k, v in ct.items():
        rev.setdefault(v, int.from_bytes(bytes.fromhex(k), 'little'))
    return rev

# 常见控制码（高字节 FF）
CTRL = {0x01FF:'▽',0x03FF:'\\n',0xFF72:'{72FF}',0x18FF:'{名1}',0x92FF:'{停顿}',0x70FF:'{仲魔}',
        0x7BFF:'{魔法}',0x1BFF:'{道具}',0x7AFF:'{恶魔1}',0x7FFF:'{恶魔2}',0x77FF:'{名3}',0x7DFF:'{名2}'}

def decode(data, off, orig, maxn=40):
    """从 off 解码，遇 FFFF 停。返回 (日文串, 结束偏移)"""
    out=[]; i=off; n=0
    while i < len(data)-1 and n < maxn:
        c = data[i] | (data[i+1] << 8); i += 2; n += 1
        if c == 0xFFFF: break
        if c in CTRL: out.append(CTRL[c])
        elif c in orig: out.append(orig[c])
        elif (c & 0xFF) == 0xFF: out.append('{%04X}' % c)
        else: out.append('〓')          # 该编号原版没定义
    return ''.join(out), i

def files():
    fs = sorted(glob.glob(os.path.join(EXTRAC, 'D', 'F0*.BIN')))
    fs.append(os.path.join(EXTRAC, 'SLPM_871.54'))
    return fs

def cmd_find(jp):
    """把日文串用原版码表编码成字节，在所有文件里搜"""
    orig = load_orig()
    rev = {v:k for k,v in orig.items()}
    try:
        pat = b''.join(rev[ch].to_bytes(2,'little') for ch in jp)
    except KeyError as e:
        print(f"字 {e} 不在原版码表里，换个字试"); return
    print(f"搜 {jp!r}  = 字节 {pat.hex(' ')}")
    for f in files():
        d = open(f,'rb').read(); start=0
        while True:
            i = d.find(pat, start)
            if i < 0: break
            name = os.path.basename(f)
            extra = f"  RAM≈0x{i+SLPM_LOAD:08X}" if 'SLPM' in name else ''
            print(f"   {name} @0x{i:X}{extra}")
            start = i+1

def cmd_decode(fname, off):
    orig = load_orig()
    d = open(os.path.join(EXTRAC,'D',fname if fname.endswith('.BIN') else fname+'.BIN'),'rb').read()
    s,_ = decode(d, int(off,0), orig, maxn=60)
    print(f"{fname} @{off}: {s}")

def cmd_slpm(off):
    orig = load_orig()
    d = open(os.path.join(EXTRAC,'SLPM_871.54'),'rb').read()
    s,_ = decode(d, int(off,0), orig, maxn=60)
    print(f"SLPM @{off}: {s}")

def cmd_scan(fname):
    """列出文件里所有"看着像文本"的串（连续 >=2 个原版字，FFFF 分隔）"""
    orig = load_orig()
    d = open(os.path.join(EXTRAC,'D',fname if fname.endswith('.BIN') else fname+'.BIN'),'rb').read()
    off=0
    while off < len(d)-1:
        s,nxt = decode(d, off, orig)
        real = sum(1 for ch in s if ch not in '〓' and not ch.startswith('{'))
        if real >= 2 and s.count('〓') <= real*0.3 and nxt > off:
            print(f"0x{off:06X}: {s}")
            off = nxt
        else:
            off += 2

def cmd_rev(chars):
    rev = load_ours()
    for ch in chars:
        c = rev.get(ch)
        print(f"  {ch} -> 编号 0x{c:04X}  (字节 {c.to_bytes(2,'little').hex(' ')})" if c else f"  {ch} -> 不在我们的码表")

if __name__ == '__main__':
    a = sys.argv
    if len(a) < 2: print(__doc__); sys.exit()
    cmd = a[1]
    if   cmd=='find':   cmd_find(a[2])
    elif cmd=='decode': cmd_decode(a[2], a[3])
    elif cmd=='slpm':   cmd_slpm(a[2])
    elif cmd=='scan':   cmd_scan(a[2])
    elif cmd=='rev':    cmd_rev(a[2])
    else: print(__doc__)
