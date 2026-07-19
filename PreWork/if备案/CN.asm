.psx
.create "SLPM_871.54", 0x8000F800
.close
.open "base_SLPM_871.54","SLPM_871.54", 0x8000F800


.org    0x8005B2E4
addiu   a3,$zero,0xC;宽度固定为12


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
.pool


.close