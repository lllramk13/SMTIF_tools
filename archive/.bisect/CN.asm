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


; F14 was 208x252 = 17 columns x 21 rows = 357 cells per bit plane, of which the
; original used 346 -> 4*346-1 = 0x567 glyphs.  The engine's own U/V loop
; (0x800474E0) divides the glyph index by 441 = 21*21, i.e. exactly what one
; 256x256 texture page holds at 12px cells, so the original never filled the
; page it already owned.  The texture is now rebuilt 252x252 (21 columns), which
; still fits that page (F14 sits at VRAM x=576,y=256, page 576..640, and all 12
; spare columns were verified blank).  That lifts the static font from 1383 to
; 4*441 = 1764 glyphs, which is what stops menu/skill/option text from running
; past the glyph table and painting stray tiles.
.org    0x8004740C
addiu   s2,$zero,0x1B9      ; glyphs per bit plane: 346 -> 441

.org    0x80047430
addiu   v0,$zero,0x6E3      ; static font capacity: 0x567 -> 4*441-1

.org    0x80078268
addiu   a3,$zero,0x6E3      ; same capacity, second hardcoded copy

; The static width table (0x800F2910, one byte per glyph) is only 0x567 entries
; long -- the menu width table starts immediately after it at 0x800F2E80 -- so
; it cannot grow with F14.  The build already fills every entry with the same
; value, so force both read sites to that constant; codes past the old table
; then advance correctly instead of reading the menu table as widths.
; The byte is two nibbles (0x8004789C does srl 4 on it); the build writes 0x0B,
; i.e. high nibble 0, so the constant reproduces today's behaviour exactly.
.org    0x80047890
addiu   v1,$zero,0xB

.org    0x80048428
addiu   v0,$zero,0xB


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
