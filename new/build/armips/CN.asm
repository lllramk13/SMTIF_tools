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


; Party-panel and STATUS names use the hybrid wrapper installed in the dead
; tail of the rewritten 0x8004ACB8 routine.  Original name-entry codes go back
; to the small Shift-JIS font; translated names go to F14.
.org    0x8006C27C
jal     hybrid_name_renderer

.org    0x8006D9E4
jal     hybrid_name_renderer


; MARKER's type-6 F14 list needs at least 0x100 bytes per row: two passes of
; 6 * 0x14-byte sprites plus two 8-byte state packets.  Its runtime descriptor
; proves the common constructor settled on only 0xD0, so every row overflowed
; by 0x30 and the fourth row overwrote descriptor+0x18 with GPU word
; 0x7811B424.  The final title draw at 0x8006DC70 then used that word as a
; string pointer and ran away.
;
; The earlier test63 patched one guessed caller at 0x80084E94, but the real
; object has different constructor fields and that call is not its source.
; Apply the floor in the common constructor after either automatic or explicit
; sizing and immediately before allocation.  Only type 6 is affected.
.org    0x8006F0A8
j       type6_f14_stride_floor
sll     v0,fp,0x10


; Restore the raw SJIS renderer instructions changed by the test62 diagnostic
; guard.  The bad pointer was a consequence of the descriptor overwrite, not
; the original cause.
.org    0x80046B28
nop
bne     v1,zero,0x800469A0


.org    0x80046980
lbu     v1,0(s4)


.org    0x8004AE70
nop
bne     v0,zero,0x8004AE18


.org    0x8005C1D0
sll     r2,0x3

.org    0x8005C218
lbu     a0,0(t0);读取一字节
addiu   a2,0x1  ;
andi    v1,a0,0x1;取第一位
sll     v1,0x2
andi    v0,a0,0x2;取第二位
sll     v0,0x5
or      v1,v0
andi    v0,a0,0x4;三位
sll     v0,0x8
or      v1,v0
andi    v0,a0,0x8;四位
sll     v0,0xB
or      v1,v0
andi    v0,a0,0x10;五位
sll     v0,0xE
or      v1,v0
andi    v0,a0,0x20;六位
sll     v0,0x11
or      v1,v0
andi    v0,a0,0x40;七位
sll     v0,0x14
or      v1,v0
andi    v0,a0,0x80;八位
sll     v0,0x17
or      v1,v0
sw      v1,0(a1)
addiu   t0,0x1
slti    v0,a2,0x18
bne     v0,0,0x8005C218
addiu   a1,0x4
jr      ra

; 0x8005C294 is the decoder's jr delay slot; keep it harmless and enter the
; constructor helper at the following word.
nop
type6_f14_stride_floor:
sra     v0,v0,0x10
addiu   t0,v0,-6
bne     t0,zero,type6_f14_stride_done
nop
lw      t0,0x800(s1)
sltiu   t1,t0,0x100
beq     t1,zero,type6_f14_stride_done
nop
ori     t0,zero,0x100
sw      t0,0x800(s1)

type6_f14_stride_done:
j       0x8006F0B0
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
addu    a2,zero,zero
addu    t0,t0,v0

legacy_f13_1bpp_loop:
lbu     a0,0(t0)
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
addiu   a2,a2,0x1
slti    v0,a2,0x18
bne     v0,zero,legacy_f13_1bpp_loop
addiu   a1,a1,0x4

jr      ra
nop

nop
nop
nop


; The replacement decoder above returns at 0x8004AD58.  Its old tail
; (0x8004AD60..0x8004ADF7) is unreachable and has no branch targets.  The
; first three words are unused and the remaining 140 bytes hold this wrapper.
;
; A keyboard-entered original name consists exclusively of the exact code set
; restored by original_ui_codetable.json.  Any other code marks translated
; content and selects F14.  a0-a3 and the caller's ra remain untouched.
;
; Both known name call sites use this wrapper so translated role/demon names
; remain visible while original keyboard-entered names retain the small font.
.org    0x8004AD6C
hybrid_name_renderer:
addu    t0,a0,zero

hybrid_name_loop:
lhu     t1,0(t0)
ori     t2,zero,0xFFFF
beq     t1,t2,hybrid_name_small
addiu   t0,t0,0x2

; 0x068..0x108
addiu   t2,t1,-0x68
sltiu   t2,t2,0xA1
bne     t2,zero,hybrid_name_loop
nop

; 0x02A..0x04D
addiu   t2,t1,-0x2A
sltiu   t2,t2,0x24
bne     t2,zero,hybrid_name_loop
nop

; 0x004..0x007
addiu   t2,t1,-0x4
sltiu   t2,t2,0x4
bne     t2,zero,hybrid_name_loop
nop

addiu   t2,zero,0x0D
beq     t1,t2,hybrid_name_loop
nop
addiu   t2,zero,0x10
beq     t1,t2,hybrid_name_loop
nop
addiu   t2,zero,0x15
beq     t1,t2,hybrid_name_loop
nop

; Name-entry blank and the original converter's special double-tilde code.
beq     t1,zero,hybrid_name_loop
nop
ori     t2,zero,0xFFFE
beq     t1,t2,hybrid_name_loop
nop

j       0x800475FC
nop
hybrid_name_small:
j       0x80046FEC
nop


.close
