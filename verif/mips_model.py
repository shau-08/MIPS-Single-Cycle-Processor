"""Golden (reference) instruction-set model of the single-cycle MIPS core.

Spec implemented (the subset the RTL targets):
    R-type : add, sub, and, or, slt           (funct 0x20, 0x22, 0x24, 0x25, 0x2A)
    I-type : lw, sw, beq                      (op 0x23, 0x2B, 0x04)
    Anything else is a NOP (no register / memory / PC side effect other than PC+4).
    $0 is hard-wired to zero. Data memory is 256 words (1 KB) and the byte address is
    mirrored modulo 1 KB. beq target = PC + 4 + (sign_ext(imm) << 2).
    HALT is `beq $0,$0,-1` (branch-to-self), which lets a program park the core.
"""

NWORDS = 256
MASK = 0xFFFFFFFF

OP_R, OP_LW, OP_SW, OP_BEQ = 0x00, 0x23, 0x2B, 0x04
F_ADD, F_SUB, F_AND, F_OR, F_SLT = 0x20, 0x22, 0x24, 0x25, 0x2A
R_FUNCT = {"add": F_ADD, "sub": F_SUB, "and": F_AND, "or": F_OR, "slt": F_SLT}
_FUNCT_KIND = {v: k for k, v in R_FUNCT.items()}
KINDS = ["add", "sub", "and", "or", "slt", "lw", "sw", "beq", "illegal"]


def to_s32(v):
    v &= MASK
    return v - (1 << 32) if v & 0x80000000 else v


def sext16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def enc_r(funct, rs, rt, rd, shamt=0, op=0):
    return ((op & 0x3F) << 26) | (rs << 21) | (rt << 16) | (rd << 11) | (shamt << 6) | (funct & 0x3F)


def enc_i(op, rs, rt, imm):
    return ((op & 0x3F) << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


HALT = enc_i(OP_BEQ, 0, 0, -1)          # 0x1000FFFF


def decode(w):
    op, rs, rt, rd = (w >> 26) & 0x3F, (w >> 21) & 0x1F, (w >> 16) & 0x1F, (w >> 11) & 0x1F
    funct, simm = w & 0x3F, sext16(w)
    if op == OP_R:
        kind = _FUNCT_KIND.get(funct, "illegal")
    elif op == OP_LW:
        kind = "lw"
    elif op == OP_SW:
        kind = "sw"
    elif op == OP_BEQ:
        kind = "beq"
    else:
        kind = "illegal"
    return dict(kind=kind, op=op, rs=rs, rt=rt, rd=rd, funct=funct, simm=simm)


class MipsModel:
    def __init__(self, imem, dmem):
        self.imem = [w & MASK for w in imem] + [0] * (NWORDS - len(imem))
        self.dmem = [w & MASK for w in dmem]
        self.regs = [0] * 32
        self.pc = 0

    def at_halt(self):
        return self.imem[(self.pc >> 2) % NWORDS] == HALT

    def step(self):
        d = decode(self.imem[(self.pc >> 2) % NWORDS])
        k, r = d["kind"], self.regs
        a, b = r[d["rs"]], r[d["rt"]]
        npc = (self.pc + 4) & MASK
        if k in R_FUNCT:
            res = {"add": (a + b), "sub": (a - b), "and": (a & b), "or": (a | b),
                   "slt": int(to_s32(a) < to_s32(b))}[k] & MASK
            if d["rd"]:
                r[d["rd"]] = res
        elif k == "lw":
            if d["rt"]:
                r[d["rt"]] = self.dmem[(((a + d["simm"]) & MASK) >> 2) % NWORDS]
        elif k == "sw":
            self.dmem[(((a + d["simm"]) & MASK) >> 2) % NWORDS] = b
        elif k == "beq" and a == b:
            npc = (self.pc + 4 + (d["simm"] << 2)) & MASK
        self.pc = npc
