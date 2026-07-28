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


; The remaining leaks in the other direction: these draw slot/list strings
; straight through F14, whose low cells now hold the context aliases, so an
; original keyboard-entered name -- and the built-in ＮＯＤＡＴＡ placeholder
; stored as `Ｎ Ｏ {FFFE} Ｄ Ａ Ｔ Ａ` -- comes out as unrelated Chinese.
;
; SLPM has exactly three `jal 0x800475FC` (0x80072C34, 0x80074F70,
; 0x800B85C8) and the overlays exactly three more, all in F0088 and handled by
; src/overlay_code_patch.py.  0x80074F70 is deliberately left alone: patching
; it changed nothing on screen, and it is the only one whose a3 lacks bit 0, so
; routing it would cost F14's second shadow pass for no benefit.
;
; Both sites below already set a3 bit 0, so the wrapper's `ori a3,a3,1` on the
; F14 leg is a no-op and translated text keeps byte-identical rendering.
.org    0x80072C34
jal     hybrid_name_renderer

.org    0x800B85C8
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
; Apply the correction in the common constructor after either automatic or
; explicit sizing and immediately before allocation.  Type 6 alone is not a
; sufficient signature: EQUIP also creates type-6 objects whose smaller
; natural stride is valid.  Restrict the correction to the observed MARKER
; failure signature, type 6 with an exact 0xD0 stride.
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


; The second pass at 0x80047C6C darkens opaque 0x64 sprites.  A native F14
; skill-list context can also contain semi-transparent 0x66 sprites.  The
; original loop sends every non-0x64 packet down its 8-byte DR_TPAGE copy
; path, even though 0x66 still has a four-word SPRT tag.  That emits malformed
; DMA packets and eventually self-links both frame buffers.  Divert nonopaque
; packets through a classifier: 0x66 advances over the source packet without
; emitting a redundant shadow; genuine state packets retain the original path.
.org    0x80047C94
bne     v0,v1,f14_shadow_classify_nonopaque


.org    0x8004AE70
nop
bne     v0,zero,0x8004AE18


; 0x80047688 is the *shared* big-font text renderer: it picks the font object
; from the table at 0x8010B4C0 using (a3 >> 3) & 0x3C, so F14 is reached from
; here as well as from the 0x800475FC convenience wrapper.  SLPM calls it from
; 24 sites and eight overlays call it too, which is why routing the three
; `jal 0x800475FC` sites fixed nothing: the status header and the SAVE/LOAD
; slot names come through here.
;
; F14's low cells hold the context aliases, so a keyboard-entered name
; (あああぱ -> 决决决扫) or the built-in ＮＯＤＡＴＡ (Ｎ Ｏ {FFFE} Ｄ Ａ Ｔ Ａ
; -> 菩濒 Ｄ Ａ 突 Ａ) comes out as unrelated Chinese.  Gate the renderer itself
; instead of chasing call sites: a string made only of original name-entry
; codes goes to the small font, everything else continues unchanged.
;
; This is safe because the game never draws Latin UI labels through F14 --
; GUARDIAN / NORMAL ITEM / EMPTY / FILE n all contain Ｎ, Ｏ or Ｔ and render
; correctly, so they come from the small font.  A big-font string built purely
; from original codes is a name or the ＮＯＤＡＴＡ placeholder.
;
; The gate runs before the prologue takes effect, so it undoes the delay-slot
; `addiu sp,sp,-72` first; both renderers read their drawing buffer from the
; caller's sp+0x10 (0x80047688 reads 88(sp) of a -72 frame, 0x80046FEC reads
; 128(sp) of a -112 frame), so no stack fixup is needed on either exit.
; t0-t2 are dead at entry: 0x80047688 initialises t1 and loads t0 itself.
.org    0x80047688
j       big_font_name_gate
addiu   sp,sp,-0x48             ; displaced first instruction (delay slot)


; The 592 bytes at 0x80047DBC are a second, fully unreferenced copy of the F14
; renderer -- the same duplicate-inlining the legacy decoder shows.  Nothing in
; the executable or any overlay branches, jumps or points into it.
.org    0x80047DBC
big_font_name_gate:
addiu   sp,sp,0x48              ; restore the caller's sp for the scan
addu    t0,a0,zero

big_font_name_loop:
lhu     t1,0(t0)
ori     t2,zero,0xFFFF
beq     t1,t2,big_font_name_small
addiu   t0,t0,0x2

; 0x068..0x108 kana, 0x02A..0x04D Latin/digits, 0x004..0x007 punctuation.
; Each test's delay slot sets up the next comparand; on a taken branch the loop
; head recomputes both t1 and t2, so the early clobber is harmless.
addiu   t2,t1,-0x68
sltiu   t2,t2,0xA1
bne     t2,zero,big_font_name_loop
addiu   t2,t1,-0x2A

sltiu   t2,t2,0x24
bne     t2,zero,big_font_name_loop
addiu   t2,t1,-0x4

sltiu   t2,t2,0x4
bne     t2,zero,big_font_name_loop
addiu   t2,zero,0x0D

beq     t1,t2,big_font_name_loop
addiu   t2,zero,0x10
beq     t1,t2,big_font_name_loop
addiu   t2,zero,0x15
beq     t1,t2,big_font_name_loop
ori     t2,zero,0xFFFE

; Name-entry blank and the original converter's special double-tilde code.
beq     t1,t2,big_font_name_loop
nop
beq     t1,zero,big_font_name_loop
nop

; Translated content: redo the prologue we displaced and resume.
addiu   sp,sp,-0x48
sw      s2,0x28(sp)
j       0x80047690
nop

big_font_name_small:
j       0x80046FEC
nop



; The SAVE/LOAD slot widget at 0x8004800C lays its text out inline instead of
; calling a renderer, and its bounds check is a spin loop:
;
;   80048440  slt a0,a0,v1          ; glyph code < font glyph count?
;   80048444  bne a0,zero,0x80048454
;   8004844C  j   0x8004844C        ; original: hang here forever
;
; So a single code >= F14's 0x567 anywhere in a slot string freezes the save
; screen permanently -- the reported 嫉妒界/贪欲界 hang, which would also hit
; every later area whose name overflows.  Skip the character instead:
; 0x80048974 is the loop's own "advance to the next character" point, and s2
; (the primitive pointer) and s5 (the x cursor) have not been advanced yet, so
; nothing else needs unwinding.  An overflowing string now loses one glyph
; instead of locking the game, and the gap shows which string to fix.
.org    0x8004844C
j       0x80048974
nop


; Same widget, second defect.  0x80048514 is its AddPrim: it writes the current
; OT head into the node's link word, then makes the node the new head.  The
; glyph path can reach it twice for one node (the shadow pass at 0x8004853C
; re-enters with a0 unchanged), and the second insert therefore stores the
; node's own address into its own link.  The GPU then walks a one-node loop
; forever: the game does not crash, it just crawls -- the reported "save screen
; is playable but needs fast-forward".
;
; `ram_vram/save_slow.bin` shows it directly: 0x801D58C8 links to itself and is
; reachable from 0x801D58DC, plus the same pair 0xC8 later in the other frame
; buffer.  Skip the insert when the node already is the head; the first insert
; left both the link and the head correct, so the chain stays valid.  When the
; double insert does not happen this is byte-for-byte the original behaviour.
;
; t8/t9 are never written anywhere in 0x8004800C, so borrowing them is safe.
.org    0x80048514
j       ot_self_link_guard
and     v1,v1,s6                ; displaced 0x80048518 (delay slot)


.org    0x80047E3C
ot_self_link_guard:
lw      v0,0(s4)                ; current OT head
and     t8,a0,s3                ; this node, 24-bit
and     t9,v0,s3                ; head, 24-bit
beq     t8,t9,ot_self_link_done ; already the head -> inserting again self-links
and     v0,v0,s3                ; delay slot, harmless on the skip path

or      v1,v1,v0
sw      v1,0(a0)                ; node.link = old head
lw      v0,0(s4)
and     v0,v0,s6                ; keep the head word's length byte
or      v0,v0,t8
sw      v0,0(s4)                ; head = this node

ot_self_link_done:
j       0x8004853C
nop




; The live self-loop.  `ram_vram/save_slow.bin` (the slow SAVE screen) has
; 0x801D58C8 linking to itself while being reachable from the real display
; list: ...->0x801D5904->0x801D58F0->0x801D58DC->0x801D58C8->itself.  The GPU
; then walks that one node forever, which is why the screen is playable but
; crawls and a captured frame shows only half the list drawn.
;
; It is produced by F14's shadow pass at 0x80047C6C: for every opaque 0x64
; sprite it duplicates the packet at t0, darkens it and links it in at
; 0x80047CFC.  If the OT head already is t0 the copy links to itself.  (This is
; the same loop Codex classified 0x66 packets out of at 0x80047C94; these are
; 0x64 and take the normal shadow path, so that fix does not cover them.)
;
; Refuse the link when the head already is this node -- the previous insert
; left both the link and the head correct, so the chain stays valid, and when
; the double insert does not happen this is byte-for-byte the original.
; Only at/k0/k1 are unwritten anywhere in 0x800475FC, so at it is.
.org    0x80047CFC
j       f14_shadow_addprim_guard
lw      v1,0(t0)                ; displaced 0x80047CFC (delay slot)


.org    0x80047E70
f14_shadow_addprim_guard:
lw      v0,0(t3)                ; OT head
and     v1,v1,a2                ; keep this packet's length byte
and     v0,v0,a1                ; head, 24-bit
and     at,t0,a1                ; this packet, 24-bit
beq     v0,at,f14_shadow_addprim_done
or      v1,v1,v0                ; delay slot, dead on the skip path
sw      v1,0(t0)                ; copy.link = old head

f14_shadow_addprim_done:
j       0x80047D14
nop


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
addiu   t1,t0,-0xD0
bne     t1,zero,type6_f14_stride_done
nop
ori     t0,zero,0x100
sw      t0,0x800(s1)

type6_f14_stride_done:
j       0x8006F0B0
nop

; Adapter for the two executable UI strings whose original callers allocated
; a single-pass small-font packet buffer.  F14 normally adds a second shadow
; pass and can overrun those fixed buffers even when the translated string is
; shorter.  Preserve every other style bit but request F14's single-pass mode.
direct_ui_f14_single_pass:
ori     a3,a3,0x1
j       0x800475FC
nop

f14_shadow_classify_nonopaque:
addiu   at,v0,-0x66
bne     at,zero,0x80047D24
nop
j       0x80047D68
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
; The old small-font renderer emits only one sprite pass.  Set F14 mode bit 0
; on the translated leg so it does the same; otherwise a semi-transparent
; 0x66 sprite can enter F14's 0x64-only shadow-copy loop and poison the GPU
; DMA list.  This is intentionally local to calls redirected by this wrapper.
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
ori     a3,a3,0x1
hybrid_name_small:
j       0x80046FEC
nop


.close
