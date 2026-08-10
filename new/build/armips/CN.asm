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


; Guardian-label VRAM probe.  0x8006A2DC uploads one of the common UI texture
; resources and releases its staging buffer through 0x8008C5C0 at 0x8006A3DC.
; Route that release through a wrapper which preserves the original call and
; then overwrites the known top-label texture rectangle with a solid 4bpp
; block.  If the Guardian title becomes a bar, both the hook timing and the
; VRAM coordinates are confirmed; the block can then be replaced by Chinese
; pixels.  This is a diagnostic step, not the final artwork.
.org    0x8006A3DC
jal     guardian_vram_probe


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
; explicit sizing and immediately before allocation.
;
; This started out matching an exact stride of 0xD0, the value measured in
; 嫉妒界, on the theory that EQUIP's type-6 objects have smaller strides that
; are legitimately fine.  They are fine, but they are also not harmed by being
; given a full row: 0x100 is simply what this renderer writes, so any stride
; below it overflows.  怠惰界 and 暴食界 proved the point -- their constructor
; settles on 0xF8, eight bytes short, and the exact match never fired.  Those
; eight bytes are the row's trailing state packet, and they land on the first
; sprite of the next row, corrupting its ordering-table link.  A savestate on a
; slow 怠惰界 MARKER has nine three-node rings of 12x12 glyph sprites, each one
; a chain that closes back on itself and that the GPU then walks forever.
;
; A constant floor of 0x100 was the next attempt, and it is still wrong: 0x100
; is what *six* glyphs need, and the requirement scales with the row.  Four
; savestates taken on slow MARKER screens all contain rows the floor was too
; small for -- one of them 11 glyphs wide, needing 0x1C8.  The shadow pass then
; runs into the normal pass and its last node is left holding only a tag and a
; colour word, so the GPU reads the *next* node's words as that sprite's
; position and size and draws a textured rectangle hundreds of pixels across.
; Two to eight of those per frame is what makes the screen crawl while still
; looking correct: the garbage is clipped away, but the GPU still fills it.
;
; The measured value is one pass plus one state packet, n*0x14 + 8, and the
; renderer writes two passes plus two state packets, 2*(n*0x14) + 0x10 -- which
; is exactly twice the measurement.  Six glyphs measure 0x80 and need 0x100,
; eleven measure 0xE4 and need 0x1C8; both check out.  So double it, and objects
; that need less than 0x100 (EQUIP's) keep getting less than 0x100.
;
; The stride load needs its delay slot honoured, and for a long time it did not.
; `lw t0,0x800(s1)` was read one instruction later, so the comparison actually
; saw the *previous* t0 -- which is `type - 6`, and therefore always zero here.
; The original `addiu t1,t0,-0xD0 / bne` was consequently never true and the
; whole correction never ran; the floor that replaced it was always true and
; rewrote every type-6 object, EQUIP's included, which hung the equip screen.
; Neither behaviour was the intended one.  The compiler's own code two
; instructions away (0x8006F074) shows the nop this needs.
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
; The old patch sent any all-Latin/all-digit string to the small font so the
; context aliases then covering C-Z could not corrupt keyboard-entered names.
; The build now restores A-Z in F14 and moves those 22 aliases to globally
; released cells.  Keeping the gate would therefore be harmful: LEVEL, LAW,
; CHAOS, BGM1..19, KENO and other genuine F14 labels also become original-code
; strings after the global A-Z re-pin and would silently switch from 11px F14
; layout to the 10px small font.  Restore the shared renderer's original
; prologue.  Explicit name call sites still use hybrid_name_renderer where the
; small-font appearance is desired; every direct F14 path can now draw original
; names and NO DATA correctly by itself.
.org    0x80047688
addiu   sp,sp,-0x48
sw      s2,0x28(sp)


; The 592 bytes at 0x80047DBC are a second, fully unreferenced copy of the F14
; renderer -- the same duplicate-inlining the legacy decoder shows.  Nothing in
; the executable or any overlay branches, jumps or points into it.  The retired
; gate remains here as unreachable historical code; no live hook targets it.
.org    0x80047DBC
big_font_name_gate:
addiu   sp,sp,0x48              ; restore the caller's sp for the scan
addu    t0,a0,zero

big_font_name_loop:
lhu     t1,0(t0)
ori     t2,zero,0xFFFF
beq     t1,t2,big_font_name_small
addiu   t0,t0,0x2

; Still-reserved cells only: 0x02A..0x04D Latin/digits, 0x004..0x007
; punctuation.  The kana block 0x068..0x108 was released and now holds ordinary
; Chinese, so it must not count as "original UI codes" any more.
; Each test's delay slot sets up the next comparand; on a taken branch the loop
; head recomputes both t1 and t2, so the early clobber is harmless.
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


; Free tail of the unreferenced duplicate F14 renderer (0x80047DBC..8004800B).
; Keep the replacement self-contained: RECT and a 16-word x 12-row pixel
; buffer live on the stack.  The three Chinese glyphs are decoded directly
; from the rebuilt 1bpp F13, so this needs no second bitmap/font copy.
.org    0x80047E94
guardian_vram_probe:
addiu   sp,sp,-0x1B0
sw      ra,0x1A0(sp)

; Preserve the displaced resource-release call.
jal     0x8008C5C0
nop

; RECT { x=684, y=314, w=16 VRAM words, h=12 }.
ori     t0,zero,0x02AC
sh      t0,0x10(sp)
ori     t0,zero,0x013A
sh      t0,0x12(sp)
ori     t0,zero,0x0010
sh      t0,0x14(sp)
ori     t0,zero,0x000C
sh      t0,0x16(sp)

; Clear the old 64x12 Japanese label.
addiu   t0,sp,0x20
ori     t2,zero,0x0060

guardian_vram_clear:
sw      zero,0(t0)
addiu   t0,t0,0x4
addiu   t2,t2,-1
bne     t2,zero,guardian_vram_clear
nop

; Render 守护灵 (glyph indices 0x27D, 0x32F, 0x0F0) into the first 36 pixels.
; Two 4bpp pixels occupy one output byte, hence the 6-byte cell advance.
ori     a0,zero,0x027D
addiu   a1,sp,0x20
jal     guardian_render_f13_glyph
nop

ori     a0,zero,0x032F
addiu   a1,sp,0x26
jal     guardian_render_f13_glyph
nop

ori     a0,zero,0x00F0
addiu   a1,sp,0x2C
jal     guardian_render_f13_glyph
nop

addiu   a0,sp,0x10
jal     0x800E2948
addiu   a1,sp,0x20

j       guardian_bottom_upload
nop


; a0 = 1bpp F13 glyph index
; a1 = byte position of this glyph in the first destination row
; Each source byte expands to four 4bpp bytes.  F13 uses inverted bits
; (0=ink, 1=transparent); destination palette index 0xF is the title colour.
guardian_render_f13_glyph:
sll     t0,a0,0x1
addu    t0,t0,a0
sll     t0,t0,0x3
lui     t1,0x8011
lw      t1,-0x4B30(t1)
nop
beq     t1,zero,guardian_render_done
nop
addu    t0,t0,t1
ori     t2,zero,0x000C

guardian_render_row:
lbu     t3,0(t0)
addiu   t0,t0,0x1
ori     t6,zero,0x0004

guardian_render_first_byte:
andi    t4,t3,0x1
xori    t4,t4,0x1
subu    t4,zero,t4
andi    t4,t4,0xF
srl     t3,t3,0x1
andi    t5,t3,0x1
xori    t5,t5,0x1
subu    t5,zero,t5
andi    t5,t5,0xF
sll     t5,t5,0x4
or      t4,t4,t5
sb      t4,0(a1)
addiu   a1,a1,0x1
srl     t3,t3,0x1
addiu   t6,t6,-1
bne     t6,zero,guardian_render_first_byte
nop

; Only the first four pixels of the glyph's second byte belong to its
; 12-pixel cell; the generated font's final four columns are padding.
lbu     t3,0(t0)
addiu   t0,t0,0x1
ori     t6,zero,0x0002

guardian_render_second_byte:
andi    t4,t3,0x1
xori    t4,t4,0x1
subu    t4,zero,t4
andi    t4,t4,0xF
srl     t3,t3,0x1
andi    t5,t3,0x1
xori    t5,t5,0x1
subu    t5,zero,t5
andi    t5,t5,0xF
sll     t5,t5,0x4
or      t4,t4,t5
sb      t4,0(a1)
addiu   a1,a1,0x1
srl     t3,t3,0x1
addiu   t6,t6,-1
bne     t6,zero,guardian_render_second_byte
nop

addiu   a1,a1,0x1A
addiu   t2,t2,-1
bne     t2,zero,guardian_render_row
nop

guardian_render_done:
jr      ra
nop


; Read and decode one complete F0093-compatible 320x240 8bpp/256-colour
; resource.  The R&D page has already faded out, so deliberately overwrite its
; original texture at VRAM word (320,0) and reuse its texture pages 5/7.
;
; One seven-sector raw read fits safely below 0x801E2800.  The image block uses
; the original Atlus RLE grammar and is followed on a four-byte boundary by
; the original 256x1 CLUT block.  Decode/upload everything before returning to
; the existing fade/hold/draw loop, so the page appears atomically.
.org    0x80105DF4
boot_read_and_upload:
watermark_upload:
addiu   sp,sp,-0x190
sw      ra,0x18C(sp)
sw      s0,0x188(sp)
sw      s1,0x184(sp)
sw      s2,0x180(sp)
sw      s3,0x17C(sp)
sw      s4,0x178(sp)
sw      s5,0x174(sp)
sw      s6,0x170(sp)

; Read the complete resource once through the proven blocking raw path.
lui     a0,0x0001
ori     a0,a0,0x748B               ; LBA 95371, head of ZZZ.BIN
ori     a1,zero,0x3800              ; seven safe Mode 2 Form 1 sectors
lui     a2,0x801D
ori     a2,a2,0xF000               ; retired boot ring-buffer storage
jal     0x8002904C                  ; read_raw_blocking
nop

; Locate the aligned CLUT block from the image block's declared size.
lui     t0,0x801D
ori     t0,t0,0xF000
lw      t1,0x4(t0)
nop
addiu   t1,t1,0x3
addiu   t2,zero,-0x4
and     t1,t1,t2
addu    t1,t1,t0
addiu   t1,t1,0x10                 ; skip the 16-byte CLUT header
sw      t1,0x20(sp)

; Static part of row RECT {x=320, y=<s1>, w=160 VRAM words, h=1}.
ori     t1,zero,0x0140
sh      t1,0x10(sp)
ori     t1,zero,0x00A0
sh      t1,0x14(sp)
ori     t1,zero,0x0001
sh      t1,0x16(sp)

addiu   s0,t0,0x10                 ; RLE source after image header
addu    s1,zero,zero                ; overwrite R&D texture from VRAM y=0
ori     s2,zero,0x00F0              ; 240 rows
addu    s4,zero,zero                ; current RLE token remaining bytes
addu    s5,zero,zero                ; 0=literal, 1=repeat

watermark_row:
addiu   a0,sp,0x30                  ; 320-byte decoded row
ori     a1,zero,0x0140
jal     watermark_rle_decode
nop

sh      s1,0x12(sp)
addiu   a0,sp,0x10
jal     0x800E2948                  ; LoadImage
addiu   a1,sp,0x30
addiu   s1,s1,0x1
addiu   s2,s2,-1
bne     s2,zero,watermark_row
nop

; Upload the complete original-format 256x1 CLUT at (0,480).
sh      zero,0x10(sp)
ori     t0,zero,0x01E0
sh      t0,0x12(sp)
ori     t0,zero,0x0100
sh      t0,0x14(sp)
ori     t0,zero,0x0001
sh      t0,0x16(sp)
lw      a1,0x20(sp)
nop
addiu   a0,sp,0x10
jal     0x800E2948
nop

jal     0x800E269C                  ; DrawSync(0)
addu    a0,zero,zero

lw      ra,0x18C(sp)
lw      s0,0x188(sp)
lw      s1,0x184(sp)
lw      s2,0x180(sp)
lw      s3,0x17C(sp)
lw      s4,0x178(sp)
lw      s5,0x174(sp)
lw      s6,0x170(sp)
addiu   sp,sp,0x190
jr      ra
nop


; A second, unreferenced zero-filled executable gap.  The top wrapper tail-
; jumps here while its stack frame is still live.  Upload the preserved lower
; bar background plus GUARDIAN PTS, then perform the wrapper's common epilogue.
.org    0x80105F80
guardian_bottom_upload:
lui     t0,0x8010
ori     t0,t0,0x6000
addiu   t1,sp,0x20
ori     t2,zero,0x0040

guardian_bottom_copy:
lw      t3,0(t0)
nop
sw      t3,0(t1)
addiu   t0,t0,0x4
addiu   t1,t1,0x4
addiu   t2,t2,-1
bne     t2,zero,guardian_bottom_copy
nop

; RECT { x=673, y=475, w=16 VRAM words, h=8 }.
ori     t0,zero,0x02A1
sh      t0,0x10(sp)
ori     t0,zero,0x01DB
sh      t0,0x12(sp)
ori     t0,zero,0x0010
sh      t0,0x14(sp)
ori     t0,zero,0x0008
sh      t0,0x16(sp)

addiu   a0,sp,0x10
jal     0x800E2948
addiu   a1,sp,0x20

lw      ra,0x1A0(sp)
addiu   sp,sp,0x1B0
jr      ra
nop


.org    0x80106000
guardian_bottom_bitmap:
; 64x8 4bpp strip containing 8px GUARDIAN PTS.
; Palette index 0xF is ink and the original 0x5/0x6 bar pixels are preserved.
.db 0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66
.db 0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x55
.db 0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66
.db 0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x66,0x56
.db 0xF6,0xFF,0x66,0xF6,0x66,0x6F,0x66,0x6F,0x66,0xFF,0xFF,0x66,0xFF,0x6F,0x66,0x6F
.db 0xF6,0x66,0xF6,0x66,0x6F,0x66,0xF6,0xFF,0xF6,0xFF,0xFF,0xF6,0xFF,0x66,0x66,0x66
.db 0x6F,0x66,0x6F,0xF6,0x66,0x6F,0xF6,0xF6,0x66,0x6F,0xF6,0x66,0x6F,0xF6,0x66,0x6F
.db 0x6F,0x6F,0xF6,0x6F,0x6F,0x66,0xF6,0xF6,0x66,0xF6,0x66,0x6F,0x66,0x6F,0x66,0x66
.db 0x6F,0x66,0x66,0xF6,0x66,0x6F,0xF6,0xF6,0x66,0xFF,0xFF,0x66,0x6F,0xF6,0x66,0x6F
.db 0x6F,0x6F,0xF6,0x6F,0x6F,0x66,0xF6,0xF6,0x66,0xF6,0x66,0xFF,0x66,0x66,0x66,0x66
.db 0x6F,0xF6,0x6F,0xF6,0x66,0x6F,0xF6,0xFF,0x66,0x6F,0x6F,0x66,0x6F,0xF6,0x66,0x6F
.db 0xFF,0x6F,0xF6,0xF6,0x6F,0x66,0xF6,0xFF,0x66,0xF6,0x66,0x66,0xFF,0x6F,0x66,0x66
.db 0x6F,0x66,0x6F,0xF6,0x66,0x6F,0x6F,0x66,0x6F,0x6F,0xF6,0x66,0x6F,0xF6,0x66,0xFF
.db 0x66,0xF6,0xF6,0xF6,0x6F,0x66,0xF6,0x66,0x66,0xF6,0x66,0x6F,0x66,0x6F,0x66,0x66
.db 0xF6,0xFF,0x66,0x66,0xFF,0x66,0x6F,0x66,0x6F,0x6F,0xF6,0x66,0xFF,0x6F,0x66,0xFF
.db 0x66,0xF6,0xF6,0x66,0x6F,0x66,0xF6,0x66,0x66,0xF6,0x66,0xF6,0xFF,0x66,0x66,0x66


; Last 120 bytes of the same verified zero-filled gap.  Decode `a1` bytes
; from the F0093 RLE stream at s0 into a0 while preserving token state across
; all 240 row calls.  s4 = remaining token bytes, s5 = repeat flag,
; s6 = repeat value.  These are intentionally updated for the caller.
.org    0x80106100
watermark_rle_decode:
watermark_rle_next:
bne     s4,zero,watermark_rle_token_ready
nop
lbu     t2,0(s0)
addiu   s0,s0,0x1
sltiu   t3,t2,0x80
bne     t3,zero,watermark_rle_literal_token
nop
addiu   s4,t2,-0x7D
lbu     s6,0(s0)
addiu   s0,s0,0x1
ori     s5,zero,0x1
j       watermark_rle_token_ready
nop

watermark_rle_literal_token:
addiu   s4,t2,0x1
addu    s5,zero,zero

watermark_rle_token_ready:
bne     s5,zero,watermark_rle_repeat
nop
lbu     t2,0(s0)
addiu   s0,s0,0x1
j       watermark_rle_store
nop

watermark_rle_repeat:
addu    t2,s6,zero

watermark_rle_store:
sb      t2,0(a0)
addiu   a0,a0,0x1
addiu   s4,s4,-1
addiu   a1,a1,-1
bne     a1,zero,watermark_rle_next
nop
jr      ra
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
sra     v0,v0,0x10              ; v0 = object type, still needed on return
lw      t0,0x800(s1)            ; stride; safe to read for any type
addiu   t1,v0,-6                ; fills the load delay slot -- reads v0, not t0
bne     t1,zero,type6_f14_stride_done
nop
sll     t0,t0,1                 ; the row is written twice; give it both passes
sw      t0,0x800(s1)
nop                             ; keep this routine 12 words so the code after
nop                             ; it, and 0x80047C94's branch into it, stay put
nop

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

; 0x068..0x108 was the kana block.  It is no longer reserved -- those cells now
; hold ordinary Chinese glyphs -- so a translated name that happens to use one
; must NOT be mistaken for keyboard-entered Japanese and sent to the small font.
; What is still reserved (digits, Latin, punctuation) is tested below.
;
; Accepting the block here looks tempting, because it would send a name mixing
; Chinese and Latin to the small font and both halves are typeable.  It does not
; work: the small font is F0012, which the build never replaces, so those cells
; still hold the original kana.  F0073 is only the keyboard graphic the player
; picks from, not the font a name is drawn with.
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


; ---------------------------------------------------------------------------
; Boot logo screens.
;
; 0x8002C794 shows one full-screen 320x240 8bpp image: it builds the display,
; reads 5 sectors starting at a raw LBA, fades in, holds 0x78 frames (button
; skippable) and fades out.  Confirmed against a savestate taken on the R&D
; screen -- its pc sat in the hold loop at 0x800C9680 and the $ra chain runs
; main -> 0x8002BC48 -> 0x8002BEF0 -> 0x8002BF64 -> here.
;
; The image is chosen by a single instruction, 0x8002C82C, which reads
; FILEPOS[93].lba as a fixed 0x7A28 offset from the 0x80100000 base that
; 0x8002C818 already set up.  Repointing that load at a variable turns the
; routine into "show whatever LBA I put here", so the boot can run it more
; than once.
;
; 0x80100000 - 0x1DA0 == 0x800FE260, so the existing `lui a0,0x8010` needs no
; change at all -- only the load's offset moves.
; .org  0x8002C82C
; lw    a0,-0x1DA0(a0)

; 160 unreferenced zero bytes between two data tables (the preceding one ends
; with its 0xFFFF terminator at 0x800FE25C).  Nothing computes an address
; inside this range.
; The original five-sector F0093 transaction remains untouched.  Once the
; normal R&D page has faded out, boot_read_and_upload performs separate
; blocking raw-sector read through the normal state-10/11 path, decodes an
; F0093-compatible RLE resource over the now-unused R&D texture, and uploads
; its 256-entry CLUT.  The proven page loop reuses the original draw settings.

; Calling 0x8002C794 twice does NOT work: its head re-runs 0x800E2604 /
; 0x800E2320, which tears the graphics and callback subsystem back down.  The
; second pass then free-runs without VSync (the logo flashes by instead of
; holding two seconds) and the CD wait at 0x8002870C spins forever because its
; completion interrupt never arrives.  So loop *inside* the routine instead,
; re-entering at 0x8002C810 -- past the one-time init, and the point where s3
; is recomputed from s2.
.org    0x800FE260
boot_screen_lba:
.word   0
boot_screen_page:
.word   0
boot_screen_saved_s4:
.word   0
boot_screen_saved_s5:
.word   0

; Entry from the routine's only caller.  A tail jump, so 0x8002C794 returns
; straight to 0x8002BF6C on the original ra and no frame is needed here.
boot_screen_start:
lui     t0,0x8010
sw      zero,-0x1D9C(t0)
sw      s4,-0x1D98(t0)              ; the caller's s4/s5 are not ours to lose
sw      s5,-0x1D94(t0)
ori     s4,zero,0x5                 ; page 0 keeps the original texture pages
ori     s5,zero,0x7
j       0x8002C794
nop

; Reached in place of the routine's closing 0x800E2604 call.  a0 is already
; zero from that call's delay slot, which the teardown path still needs.
boot_screen_next:
lui     t0,0x8010
lw      t1,-0x1D9C(t0)
nop
addiu   t1,t1,0x1
sw      t1,-0x1D9C(t0)
addiu   t2,zero,0x1
bne     t1,t2,boot_screen_done
nop

; Finish one clean R&D frame before replacing its VRAM texture.  Without this
; submission the next page can briefly reveal the dim tail of the previous
; framebuffer during the transition.  0x8002C978 performs the proven closing
; frame pass; restore our dispatcher state afterwards so the inserted page
; still enters the normal fade/hold/draw loop.
jal     0x8002C978
nop
lui     t0,0x8010
ori     t1,zero,0x1
sw      t1,-0x1D9C(t0)

; Page 1: perform an independent blocking raw read, upload it, then re-enter
; after the boot resource loader so it is not invoked a second time.
jal     boot_read_and_upload
nop
addiu   s0,zero,0xF0                ; sprite height, clobbered by the fade-out
addu    s1,zero,zero                ; fade counter, ends negative
ori     s4,zero,0x5                 ; reuse R&D tpage at VRAM word (320, 0)
ori     s5,zero,0x7                 ; its 64-texel remainder
j       0x8002C850
nop

boot_screen_done:
lw      s4,-0x1D98(t0)
lw      s5,-0x1D94(t0)
j       0x800E2604
nop





; The sprite's texture page (written to offset 0x0C of the primitive by
; 0x8002CA9C) is 5 and 7 -- VRAM words 320 and 448 on line 0.  Both pages now
; deliberately reuse those original R&D positions; s4/s5 remain variables so
; the dispatcher still preserves the proven page-loop structure.
.org   0x8002C860
addu   v0,zero,s4

.org   0x8002C888
addu   v0,zero,s5

; Seven sectors -- the most this read can carry.  Its destination is 0x801DF000
; and the next structure sits at 0x801E2800, 0x3800 bytes later; ten sectors
; overruns that and 0x801E4000 as well, both CD driver state, and the boot then
; dies on its next load with nothing on screen to show why.
; .org  0x800EB7C8
; .halfword 7


; The routine's only caller in the whole executable.
.org   0x8002BF64
jal    boot_screen_start

; Closing teardown call -> our page dispatcher.  The delay slot (a0 = 0) is
; left untouched and still applies to 0x800E2604 on the final pass.
.org   0x8002C954
jal    boot_screen_next


; The shared F14 renderer has its own AddPrim for glyph sprites at 0x80047A6C,
; the direct analogue of the save-slot widget's 0x80048514 that
; ot_self_link_guard already covers -- both write the sprite's v coordinate with
; `sh v0,0xe(a0)` immediately before linking, and both self-link when the node
; being inserted already is the ordering-table head.
;
; Evidence it is this site and not the shadow pass: a savestate taken on a slow
; MARKER screen in 嫉妒界 has three live OT chains that each walk into a one-node
; loop -- heads 0x801324B8 (72 nodes) and 0x80133FF8 (70) both end on
; 0x80136798, and 0x801330B8 (75) ends on 0x80136AD8, the same node in the other
; frame buffer.  The looping node's primitive is `64808080`: the *normal* pass.
; The existing guard at 0x80047CFC sits on the shadow pass and never sees it.
; The GPU then walks that loop forever -- the screen still draws, the game just
; crawls, and only in the larger worlds, never at school.
;
; t1 is 0x00FFFFFF (0x80047858 ors the 0xFFFF from 0x80047848 into 0x00FF0000)
; and t7 is 0xFF000000.  `at` is never written anywhere in
; 0x80047688..0x80047DBC, so it is free scratch.
.org    0x80047A6C
j       f14_glyph_ot_guard
and     v1,v1,t7                ; displaced 0x80047A70 (delay slot)


; 116 unreferenced zero bytes between two data tables; nothing in the executable
; computes an address inside them.
.org    0x800FE08C
f14_glyph_ot_guard:
lw      v0,0(t3)                ; current OT head
and     at,a0,t1                ; this node, 24-bit
and     v0,v0,t1                ; head, 24-bit
beq     at,v0,f14_glyph_ot_skip ; already the head -> inserting again self-links
nop

or      v1,v1,v0
sw      v1,0(a0)
lw      v0,0(t3)
and     v1,a0,t1
and     v0,v0,t7
or      v0,v0,v1
sw      v0,0(t3)

f14_glyph_ot_skip:
j       0x80047A94
nop


; The CONTINUE screen's four ending lamps.  Each is one Shift-JIS character
; naming the partner whose route was cleared -- the first kana of アキラ,
; チャーリー, ユミ and レイコ -- with ＊ for a route still open.  A five-entry
; pointer table at 0x800F8358 selects between them and 0x80073574 draws the
; chosen one through the small font's Shift-JIS path, ten pixels apart.
;
; That path cannot reach our own font, and the small font's 160 Chinese cells
; (the name-entry keyboard's) happen to hold 玲 and 明 but neither 查 nor 由, so
; three of the four could be localised and the fourth could not.  Use initials
; instead: they are plain ASCII, which this renderer has always drawn, and they
; keep all four lamps consistent with each other.
;
;   Ｍ 明   Ｃ 查理   Ｙ 由美   Ｌ 玲子
;
; Fullwidth, not ASCII.  This renderer takes one two-byte character per lamp --
; every entry it has ever held is fullwidth, and the lamps are spaced ten pixels
; apart to suit that.  Halfwidth 'M',0 gets read as a single two-byte code
; instead and draws a stray bar or a blank box.  ＮＯ and ＹＥＳ a few entries
; earlier in the same table are stored the same way.
.org    0x80106EA8
.byte   0x82,0x6C,0,0           ; Ｍ
.byte   0x82,0x62,0,0           ; Ｃ
.byte   0x82,0x78,0,0           ; Ｙ
.byte   0x82,0x6B,0,0           ; Ｌ


.close
