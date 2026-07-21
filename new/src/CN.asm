.psx
.create "SLPM_871.54", 0x8000F800
.close
.open "base_SLPM_871.54","SLPM_871.54", 0x8000F800


; The original 2bpp F13 stores 0x567 glyphs at 48 bytes each.  The Chinese
; patch halves each glyph to 24 bytes and therefore doubles the available
; indices.  The cache pointer table must grow with it or every code above
; 0x0566 indexes past the allocated table and corrupts unrelated memory.
.org    0x80049578
addiu   v0,$zero,0xACE


.org    0x8005B2E4
addiu   a3,$zero,0xC;宽度固定为12


; The legacy menu/system renderer has an identical proportional-width lookup
; at 0x8004A064 (lbu a3,(v1) indexing width table 0x800F2E80).  The dialogue
; path above (0x8005B2E4) was already forced to width 12, but this one was
; left alone.  Relocated high Chinese codes (>= 0x567) therefore read past the
; 0x567-entry width table and get garbage widths (e.g. 没=129, 有=105), which
; stretches those glyphs into long bars and pushes the rest of the line off
; position -> overlapping menu garbage.  Mirror the dialogue fix: fixed 12.
.org    0x8004A064
addiu   a3,$zero,0xC


; Party-panel and STATUS names are stored as 16-bit internal glyph indices.
; The original calls at 0x8006C27C and 0x8006D9E4 used 0x80046FEC, which first converts those
; indices back to the small Shift-JIS system-font table.  That converter only
; recognizes the original punctuation/kana range (< 0x0109), so translated
; preset names such as 由美 collapse to the shared fallback tile.
; 0x800475FC has the same calling convention, but renders the 16-bit
; indices directly through the 0x0567-entry F14 font.
.org    0x8006C27C
jal     0x800475FC

.org    0x8006D9E4
jal     0x800475FC


.org    0x8005C1D0
sll     r2,0x3

.org    0x8005C218
lbu     a0,0(t0);读取一字节
addiu   a2,0x1  ;
andi    v1,a0,0x1;取第一位
beq     v1,0,tz1
sll     v1,0x2
tz1:
andi    v0,a0,0x2;取第二位
beq     v0,0,tz2
sll     v0,0x2
tz2:
sll     v0,0x3
or      v1,v0
andi    v0,a0,0x4;三位
beq     v0,0,tz3
sll     v0,0x2
tz3:
sll     v0,0x6
or      v1,v0
andi    v0,a0,0x8;四位
beq     v0,0,tz4
sll     v0,0x2
tz4:
sll     v0,0x9
or      v1,v0
andi    v0,a0,0x10;五位
beq     v0,0,tz5
sll     v0,0x2
tz5:
sll     v0,0xC
or      v1,v0
andi    v0,a0,0x20;六位
beq     v0,0,tz6
sll     v0,0x2
tz6:
sll     v0,0xF
or      v1,v0
andi    v0,a0,0x40;七位
beq     v0,0,tz7
sll     v0,0x2
tz7:
sll     v0,0x12
or      v1,v0
andi    v0,a0,0x80;八位
beq     v0,0,tz8
sll     v0,0x2
tz8:
sll     v0,0x15
or      v1,v0
sw      v1,0(a1)
addiu   t0,0x1
slti    v0,a2,0x18
bne     v0,0,0x8005C218
addiu   a1,0x4
b       0x8005C2E4
nop


; Some menu/system windows create glyph textures through 0x8004ACB8
; instead of the dialogue decoder above.  The original routine indexes F13
; at 48 bytes per glyph and expands 2bpp pixels.  F13 is now packed 1bpp at
; 24 bytes per glyph, so leaving this second decoder untouched makes it read
; the wrong glyph and combine adjacent glyph data into dot-pattern garbage.
;
; a0 = glyph index
; a1 = destination for 24 words (8 expanded pixels per word)
.org    0x8004ACB8
andi    a0,a0,0xFFFF
sll     v0,a0,0x1
addu    v0,v0,a0
sll     v0,v0,0x3
lui     t0,0x8011
lw      t0,-0x4B30(t0)
nop
addu    t0,t0,v0
addu    a2,zero,zero

legacy_f13_1bpp_loop:
lbu     a0,0(t0)
nop

lui     v1,0x2222
ori     v1,v1,0x2222

andi    v0,a0,0x01
or      v1,v1,v0

andi    v0,a0,0x02
sll     v0,v0,0x03
or      v1,v1,v0

andi    v0,a0,0x04
sll     v0,v0,0x06
or      v1,v1,v0

andi    v0,a0,0x08
sll     v0,v0,0x09
or      v1,v1,v0

andi    v0,a0,0x10
sll     v0,v0,0x0C
or      v1,v1,v0

andi    v0,a0,0x20
sll     v0,v0,0x0F
or      v1,v1,v0

andi    v0,a0,0x40
sll     v0,v0,0x12
or      v1,v1,v0

andi    v0,a0,0x80
sll     v0,v0,0x15
or      v1,v1,v0

sw      v1,0(a1)
addiu   t0,t0,0x1
addiu   a1,a1,0x4
addiu   a2,a2,0x1
slti    v0,a2,0x18
bne     v0,zero,legacy_f13_1bpp_loop
nop

jr      ra
nop


.close
