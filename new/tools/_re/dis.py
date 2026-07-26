import sys,io,os,json,glob,struct
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding="utf-8")
ROOT=r"P:\ROMHacking\SMT IF"
m=json.load(open(os.path.join(ROOT,"extrac","_iso_manifest.json"),encoding="utf-8"))
RS=m["raw_sector_size"];OFF=m["form1_user_offset"];US=m["form1_user_size"]
ent={e["path"]:e for e in m["entries"] if e.get("path")}
img=open(glob.glob(os.path.join(ROOT,"Game","ogd","*.bin"))[0],"rb").read()
e=ent["SLPM_871.54"];lba=e["extent_lba"];size=e["size"];out=bytearray();s=lba
while len(out)<size: base=s*RS+OFF;out+=img[base:base+US];s+=1
SN=bytes(out[:size]); BASE=0xF800
R=["zero","at","v0","v1","a0","a1","a2","a3","t0","t1","t2","t3","t4","t5","t6","t7","s0","s1","s2","s3","s4","s5","s6","s7","t8","t9","k0","k1","gp","sp","fp","ra"]
def dis(w,pc):
    op=w>>26;rs=(w>>21)&31;rt=(w>>16)&31;rd=(w>>11)&31;sh=(w>>6)&31;fn=w&63
    imm=w&0xFFFF;simm=imm-0x10000 if imm>0x7FFF else imm
    if w==0:return "nop"
    if op==0:
        d={0x20:"add",0x21:"addu",0x22:"sub",0x23:"subu",0x24:"and",0x25:"or",0x26:"xor",0x27:"nor",0x2A:"slt",0x2B:"sltu",0x18:"mult",0x19:"multu",0x1A:"div",0x1B:"divu",0x04:"sllv",0x06:"srlv",0x07:"srav"}
        if fn in(0x18,0x19,0x1A,0x1B):return f"{d[fn]} {R[rs]},{R[rt]}"
        if fn==0x10:return f"mfhi {R[rd]}"
        if fn==0x12:return f"mflo {R[rd]}"
        if fn==0x08:return f"jr {R[rs]}"
        if fn==0x09:return f"jalr {R[rd]},{R[rs]}"
        if fn in(0,2,3):return f"{'sll' if fn==0 else 'srl' if fn==2 else 'sra'} {R[rd]},{R[rt]},{sh}"
        if fn in d:return f"{d[fn]} {R[rd]},{R[rs]},{R[rt]}"
        return f"spec fn=0x{fn:02X}"
    if op==1: return f"{'bltz' if rt==0 else 'bgez'} {R[rs]},0x{pc+4+simm*4:08X}"
    if op==2:return f"j 0x{(pc&0xF0000000)|((w&0x3FFFFFF)<<2):08X}"
    if op==3:return f"jal 0x{(pc&0xF0000000)|((w&0x3FFFFFF)<<2):08X}"
    if op in(4,5):return f"{'beq' if op==4 else 'bne'} {R[rs]},{R[rt]},0x{pc+4+simm*4:08X}"
    if op in(6,7):return f"{'blez' if op==6 else 'bgtz'} {R[rs]},0x{pc+4+simm*4:08X}"
    n={8:"addi",9:"addiu",0x0A:"slti",0x0B:"sltiu",0x0C:"andi",0x0D:"ori",0x0E:"xori"}
    if op in n:return f"{n[op]} {R[rt]},{R[rs]},{(simm if op in(8,9,0x0A,0x0B) else imm):#x}"
    if op==0x0F:return f"lui {R[rt]},{imm:#x}"
    l={0x20:"lb",0x21:"lh",0x23:"lw",0x24:"lbu",0x25:"lhu",0x28:"sb",0x29:"sh",0x2B:"sw"}
    if op in l:return f"{l[op]} {R[rt]},{simm:#x}({R[rs]})"
    return f"op=0x{op:02X}"
def dump(start,count,label=""):
    print(f"\n===== {label} 0x{start:08X} =====")
    off=start-0x80000000-BASE
    for i in range(count):
        a=off+i*4;w=struct.unpack_from("<I",SN,a)[0];pc=0x80000000+a+BASE
        print(f"  0x{pc:08X}: {w:08X}  {dis(w,pc)}")
