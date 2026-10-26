"""pyuvm (Python UVM) verification environment for the single-cycle MIPS core.

Structure (standard UVM roles):
    ProgItem        uvm_sequence_item   : one complete test program + data-memory image
    DirectedSeq     uvm_sequence        : hand-written corner-case programs
    RandomSeq       uvm_sequence        : constrained-random programs (cocotb-coverage CRV)
    Driver          uvm_driver          : back-door loads program/data, resets and clocks the DUT
    Monitor         uvm_monitor         : samples PC/instr/regs from the DUT every cycle
    Scoreboard      uvm_subscriber      : lock-step compare against the golden model (mips_model.py)
    Coverage        uvm_subscriber      : functional coverage (cocotb-coverage)
    MipsEnv         uvm_env             : wires everything together
"""
import os
import random

import cocotb
from cocotb.triggers import FallingEdge, Timer
from cocotb_coverage.coverage import CoverPoint, coverage_section, coverage_db
from cocotb_coverage.crv import Randomized
from pyuvm import (ConfigDB, uvm_analysis_port, uvm_driver, uvm_env, uvm_monitor,
                   uvm_sequence, uvm_sequence_item, uvm_sequencer, uvm_subscriber)

import mips_model as mm

# ----------------------------------------------------------------------------------
# Shared run-time state / results
# ----------------------------------------------------------------------------------
PTRS = [4, 16, 64, 128, 256, 512, 768, 1000]       # held in $1..$8 (never overwritten)
EDGE = [0x00000000, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0x00000001, 0xFFFFFFFE]


class RunState:
    dut = None
    running = False
    cycle = 0
    last_cycle = 0


class Results:
    programs = 0
    steps = 0
    mismatches = 0
    failed_programs = set()
    first_errors = []
    by_kind = {}
    directed_programs = 0
    random_programs = 0


def reset_results():
    Results.programs = Results.steps = Results.mismatches = 0
    Results.failed_programs = set()
    Results.first_errors = []
    Results.by_kind = {}
    Results.directed_programs = Results.random_programs = 0


# ----------------------------------------------------------------------------------
# Sequence item
# ----------------------------------------------------------------------------------
class ProgItem(uvm_sequence_item):
    def __init__(self, name="prog", imem=None, dmem=None, tag="rand"):
        super().__init__(name)
        self.imem = list(imem or [])
        self.dmem = list(dmem or [0] * mm.NWORDS)
        self.tag = tag
        self.nsteps = 0

    def finalize(self, cap=400):
        """Run the golden model to the halt instruction to learn how many cycles to clock."""
        m = mm.MipsModel(self.imem, self.dmem)
        n = 0
        while not m.at_halt() and n < cap:
            m.step()
            n += 1
        assert m.at_halt(), f"program {self.tag} does not reach HALT within {cap} steps"
        self.nsteps = n
        return self


# ----------------------------------------------------------------------------------
# Constrained-random instruction items (cocotb-coverage CRV: declarative constraints)
# ----------------------------------------------------------------------------------
class AluItem(Randomized):
    """R-type. rd in {$0} U [9..31] so pointer registers $1-$8 survive."""
    def __init__(self):
        super().__init__()
        self.kind = self.rs = self.rt = self.rd = None
        self.add_rand("kind", ["add", "sub", "and", "or", "slt"])
        self.add_rand("rs", list(range(32)))
        self.add_rand("rt", list(range(32)))
        self.add_rand("rd", [0] + list(range(9, 32)))

    def encode(self):
        return mm.enc_r(mm.R_FUNCT[self.kind], self.rs, self.rt, self.rd)


class MemItem(Randomized):
    """lw/sw. Constraint: effective address = ptr[base] + 4*off must stay in [0, 1020]."""
    def __init__(self):
        super().__init__()
        self.store = self.base = self.off = self.rt = None
        self.add_rand("store", [0, 1])
        self.add_rand("base", list(range(9)))                    # $0 or $1..$8
        self.add_rand("off", list(range(-16, 64)))               # word offset
        self.add_rand("rt", [0] + list(range(9, 32)))
        self.add_constraint(
            lambda base, off: 0 <= (0 if base == 0 else PTRS[base - 1]) + 4 * off <= 1020)

    def encode(self):
        op = mm.OP_SW if self.store else mm.OP_LW
        rt = self.rt if self.rt != 0 or not self.store else random.choice([0, 9, 10])
        return mm.enc_i(op, self.base, rt, 4 * self.off)


class BrItem(Randomized):
    """beq with forward offsets only (0..3 words) so every program terminates."""
    def __init__(self):
        super().__init__()
        self.rs = self.rt = self.off = self.same = None
        self.add_rand("rs", list(range(32)))
        self.add_rand("rt", list(range(32)))
        self.add_rand("off", [0, 1, 2, 3])
        self.add_rand("same", [0, 1])

    def encode(self):
        rt = self.rs if self.same else self.rt
        return mm.enc_i(mm.OP_BEQ, self.rs, rt, self.off)


class IllItem(Randomized):
    """Unsupported opcodes / functs. The spec says these are NOPs."""
    def __init__(self):
        super().__init__()
        self.op = self.funct = self.rs = self.rt = self.rd = self.imm = None
        self.add_rand("op", [0x00, 0x00, 0x00, 0x08, 0x0C, 0x0D, 0x0F, 0x0A, 0x02, 0x03, 0x05])
        self.add_rand("funct", [0x00, 0x02, 0x08, 0x18, 0x26, 0x27, 0x2B])
        self.add_rand("rs", list(range(32)))
        self.add_rand("rt", list(range(32)))
        self.add_rand("rd", list(range(1, 32)))
        self.add_rand("imm", [0, 1, 0x7FFF, 0x8000, 0xFFFF, 0x1234])

    def encode(self):
        if self.op == 0:
            return mm.enc_r(self.funct, self.rs, self.rt, self.rd)
        # keep unsupported J/branch opcodes harmless: they must be NOPs per spec
        return (self.op << 26) | (self.rs << 21) | (self.rt << 16) | self.imm


def rand_word(rng):
    return rng.choice(EDGE) if rng.random() < 0.35 else rng.getrandbits(32)


def prologue_and_data(rng):
    """16 lw's: $1-$8 <- pointers, $9-$16 <- edge-biased random data."""
    dmem = [rand_word(rng) for _ in range(mm.NWORDS)]
    dmem[0:8] = PTRS
    imem = [mm.enc_i(mm.OP_LW, 0, i + 1, 4 * i) for i in range(8)]
    imem += [mm.enc_i(mm.OP_LW, 0, 9 + i, 4 * (8 + i)) for i in range(8)]
    return imem, dmem


def random_program(rng, n_body):
    imem, dmem = prologue_and_data(rng)
    prev_rd = None
    for _ in range(n_body):
        r = rng.random()
        if r < 0.46:
            it = AluItem()
        elif r < 0.62:
            it = MemItem()
        elif r < 0.83:
            it = BrItem()
        else:
            it = IllItem()
        it.randomize()
        # steer a share of ALU/branch sources onto the previous destination -> RAW dependencies
        if prev_rd and isinstance(it, (AluItem, BrItem)) and rng.random() < 0.4:
            it.rs = prev_rd
        word = it.encode()
        imem.append(word)
        d = mm.decode(word)
        prev_rd = d["rd"] if d["kind"] in mm.R_FUNCT and d["rd"] else (
            d["rt"] if d["kind"] == "lw" and d["rt"] else None)
    imem += [mm.HALT] * 4
    return imem, dmem


# ----------------------------------------------------------------------------------
# Sequences
# ----------------------------------------------------------------------------------
class DirectedSeq(uvm_sequence):
    async def body(self):
        for item in directed_programs():
            await self.start_item(item)
            await self.finish_item(item)


class RandomSeq(uvm_sequence):
    def __init__(self, name="rand_seq", n=300, seed=1, max_body=60):
        super().__init__(name)
        self.n, self.seed, self.max_body = n, seed, max_body

    async def body(self):
        rng = random.Random(self.seed)
        random.seed(self.seed)                       # CRV solver uses the global RNG
        for i in range(self.n):
            imem, dmem = random_program(rng, rng.randint(15, self.max_body))
            item = ProgItem(f"rand{i}", imem, dmem, tag=f"rand{i}").finalize()
            await self.start_item(item)
            await self.finish_item(item)


def _hex(*ws):
    return [w & 0xFFFFFFFF for w in ws]


def directed_programs():
    H = [mm.HALT] * 4
    items = []
    z = [0] * mm.NWORDS

    # D1: the program that shipped with the repo (program.mem), regs preset like the old TB
    d = list(z)
    d[0], d[1] = 5, 7
    imem = [mm.enc_i(mm.OP_LW, 0, 1, 0), mm.enc_i(mm.OP_LW, 0, 2, 4)]
    imem += [0x00221820, 0x00412022, 0x00223824, 0x00224025, 0xAC030000, 0x8C090000]
    items.append(ProgItem("d_orig", imem + H, d, "d_repo_program"))

    # D2: slt corner cases (signed): -1<1, 1<-1, equal, MIN<MAX, MAX<MIN
    d = list(z)
    d[0:6] = _hex(0xFFFFFFFF, 1, 0x80000000, 0x7FFFFFFF, 5, 5)
    imem = [mm.enc_i(mm.OP_LW, 0, i + 1, 4 * i) for i in range(6)]
    for rs, rt, rd in [(1, 2, 9), (2, 1, 10), (5, 6, 11), (3, 4, 12), (4, 3, 13), (1, 1, 14)]:
        imem.append(mm.enc_r(mm.F_SLT, rs, rt, rd))
    items.append(ProgItem("d_slt", imem + H, d, "d_slt_corners"))

    # D3: writes to $0 must be discarded (ALU and lw)
    d = list(z)
    d[0] = 0x1234
    imem = [mm.enc_i(mm.OP_LW, 0, 1, 0), mm.enc_r(mm.F_ADD, 1, 1, 0),
            mm.enc_i(mm.OP_LW, 0, 0, 0), mm.enc_r(mm.F_ADD, 0, 0, 5)]
    items.append(ProgItem("d_r0", imem + H, d, "d_write_to_r0"))

    # D4: unsupported funct/opcodes are NOPs (regression for the 'silently ADD' bug)
    d = list(z)
    d[0], d[1] = 9, 3
    imem = [mm.enc_i(mm.OP_LW, 0, 1, 0), mm.enc_i(mm.OP_LW, 0, 2, 4),
            mm.enc_r(0x26, 1, 2, 3),           # xor  -> NOP
            mm.enc_r(0x00, 1, 2, 4),           # sll  -> NOP
            mm.enc_r(0x27, 1, 2, 5),           # nor  -> NOP
            mm.enc_i(0x08, 1, 6, 100),         # addi -> NOP
            mm.enc_i(0x0D, 1, 7, 0xFF)]        # ori  -> NOP
    items.append(ProgItem("d_illegal", imem + H, d, "d_illegal_are_nop"))

    # D5: beq taken (forward, skips an instr), not taken
    d = list(z)
    d[0], d[1] = 4, 4
    imem = [mm.enc_i(mm.OP_LW, 0, 1, 0), mm.enc_i(mm.OP_LW, 0, 2, 4),
            mm.enc_i(mm.OP_BEQ, 1, 2, 1), mm.enc_r(mm.F_ADD, 1, 2, 9),
            mm.enc_r(mm.F_SUB, 1, 2, 10), mm.enc_i(mm.OP_BEQ, 1, 0, 1),
            mm.enc_r(mm.F_OR, 1, 2, 11)]
    items.append(ProgItem("d_beq", imem + H, d, "d_beq_taken_not_taken"))

    # D6: backward loop: decrement counter in $1 until it equals $0 (3 iterations)
    d = list(z)
    d[0], d[1] = 3, 1
    imem = [mm.enc_i(mm.OP_LW, 0, 1, 0), mm.enc_i(mm.OP_LW, 0, 2, 4),
            mm.enc_r(mm.F_SUB, 1, 2, 1),               # L: r1 -= 1
            mm.enc_i(mm.OP_BEQ, 1, 0, 1),              # if r1==0 skip next
            mm.enc_i(mm.OP_BEQ, 0, 0, -3),             # else jump back to L
            mm.enc_r(mm.F_ADD, 1, 2, 5)]
    items.append(ProgItem("d_loop", imem + H, d, "d_backward_loop"))

    # D7: sw -> lw same address; sign-extended negative offset; address wrap at 1 KB
    d = list(z)
    d[0], d[1], d[2] = 0xCAFEBABE, 64, 1028
    imem = [mm.enc_i(mm.OP_LW, 0, 1, 0), mm.enc_i(mm.OP_LW, 0, 2, 4), mm.enc_i(mm.OP_LW, 0, 3, 8),
            mm.enc_i(mm.OP_SW, 2, 1, -4 & 0xFFFF),     # mem[60] = r1 (neg offset)
            mm.enc_i(mm.OP_LW, 0, 4, 60),              # r4 = mem[60]
            mm.enc_i(mm.OP_SW, 3, 1, 0),               # 1028 wraps to word 1
            mm.enc_i(mm.OP_LW, 0, 5, 4)]
    items.append(ProgItem("d_mem", imem + H, d, "d_mem_neg_wrap"))

    # D8: arithmetic corners: MAX+1, MIN-1, x-x, and/or with all-ones
    d = list(z)
    d[0:4] = _hex(0x7FFFFFFF, 1, 0x80000000, 0xFFFFFFFF)
    imem = [mm.enc_i(mm.OP_LW, 0, i + 1, 4 * i) for i in range(4)]
    imem += [mm.enc_r(mm.F_ADD, 1, 2, 9), mm.enc_r(mm.F_SUB, 3, 2, 10), mm.enc_r(mm.F_SUB, 1, 1, 11),
             mm.enc_r(mm.F_AND, 4, 1, 12), mm.enc_r(mm.F_OR, 4, 3, 13), mm.enc_r(mm.F_ADD, 4, 2, 14)]
    items.append(ProgItem("d_arith", imem + H, d, "d_arith_corners"))

    # D9-D11: coverage-closure for operand-corner crosses (zero/ones/min/max/other x same) per ALU op
    vals = [0x00000000, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0x12345678]
    for name, f in (("add", mm.F_ADD), ("sub", mm.F_SUB), ("slt", mm.F_SLT)):
        d = list(z)
        d[0:5] = vals
        imem = [mm.enc_i(mm.OP_LW, 0, 9 + i, 4 * i) for i in range(5)]       # $9..$13 = corners
        for i in range(5):
            for j in range(5):
                imem.append(mm.enc_r(f, 9 + i, 9 + j, 14 + ((5 * i + j) % 10)))
        items.append(ProgItem(f"d_corner_{name}", imem + H, d, f"d_corner_{name}"))

    # D12: beq NOT taken with a negative offset (random generator is forward-only to guarantee termination)
    d = list(z)
    d[0], d[1] = 1, 2
    imem = [mm.enc_i(mm.OP_LW, 0, 1, 0), mm.enc_i(mm.OP_LW, 0, 2, 4),
            mm.enc_i(mm.OP_BEQ, 1, 2, -2), mm.enc_r(mm.F_ADD, 1, 2, 9)]
    items.append(ProgItem("d_beq_back_nt", imem + H, d, "d_beq_backward_not_taken"))

    return [i.finalize() for i in items]


# ----------------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------------
class Driver(uvm_driver):
    def build_phase(self):
        self.ap = uvm_analysis_port("ap", self)
        self.dut = RunState.dut

    async def run_phase(self):
        dut = self.dut
        dut.reset.value = 1
        while True:
            item = await self.seq_item_port.get_next_item()
            await self.run_program(item)
            self.seq_item_port.item_done()

    async def run_program(self, item):
        dut = self.dut
        RunState.running = False
        dut.reset.value = 1
        await FallingEdge(dut.clk)               # >=1 posedge under reset -> PC = 0
        await FallingEdge(dut.clk)
        # Back-door load memories + register file at the last edge before reset release.
        # (Loaded here, not earlier, because the core keeps executing instr 0 while PC is held.)
        for i in range(mm.NWORDS):
            dut.DP.IM.memory[i].value = item.imem[i] if i < len(item.imem) else 0
            dut.DP.DM.data_mem[i].value = item.dmem[i]
        for i in range(32):
            dut.DP.RF.reg_ptr[i].value = 0
        self.ap.write(("start", item))
        dut.reset.value = 0
        RunState.cycle = 0
        RunState.last_cycle = item.nsteps
        RunState.running = True
        for _ in range(item.nsteps):
            await FallingEdge(dut.clk)
        await Timer(3, "ns")                      # let the monitor take the final sample
        RunState.running = False
        self.ap.write(("end", item))


# ----------------------------------------------------------------------------------
# Monitor
# ----------------------------------------------------------------------------------
def val(h):
    try:
        return int(h.value)
    except ValueError:                            # X/Z
        return None


class StepTxn:
    __slots__ = ("cycle", "last", "pc", "instr", "rd1", "rd2", "alu", "zero", "regs", "dmem")


class Monitor(uvm_monitor):
    def build_phase(self):
        self.ap = uvm_analysis_port("ap", self)
        self.dut = RunState.dut

    async def run_phase(self):
        dut = self.dut
        while True:
            await FallingEdge(dut.clk)
            await Timer(1, "ns")                  # combinational settle after the clock edge
            if not RunState.running:
                continue
            t = StepTxn()
            t.cycle = RunState.cycle
            t.last = (t.cycle == RunState.last_cycle)
            t.pc = val(dut.DP.PC)
            t.instr = val(dut.DP.Instr)
            t.rd1, t.rd2 = val(dut.DP.RD1), val(dut.DP.RD2)
            t.alu, t.zero = val(dut.DP.ALUResult), val(dut.DP.Zero)
            t.regs = [val(dut.DP.RF.reg_ptr[i]) for i in range(32)]
            t.dmem = [val(dut.DP.DM.data_mem[i]) for i in range(mm.NWORDS)] if t.last else None
            self.ap.write(t)
            RunState.cycle += 1


# ----------------------------------------------------------------------------------
# Scoreboard
# ----------------------------------------------------------------------------------
class Scoreboard(uvm_subscriber):
    def start_of_simulation_phase(self):
        self.model = None
        self.tag = None

    def _err(self, msg):
        Results.mismatches += 1
        Results.failed_programs.add(self.tag)
        if len(Results.first_errors) < 12:
            Results.first_errors.append(f"[{self.tag}] {msg}")

    def write(self, datum):
        if isinstance(datum, tuple):
            kind, item = datum
            if kind == "start":
                self.model = mm.MipsModel(item.imem, item.dmem)
                self.tag = item.tag
                Results.programs += 1
                if item.tag.startswith("d_"):
                    Results.directed_programs += 1
                else:
                    Results.random_programs += 1
            return
        t, m = datum, self.model
        Results.steps += 1
        if t.pc != m.pc:
            self._err(f"cyc{t.cycle}: PC dut={t.pc} model={m.pc}")
        for i in range(32):
            if t.regs[i] != m.regs[i]:
                self._err(f"cyc{t.cycle}: r{i} dut={t.regs[i]} model={m.regs[i]:#x}")
        if t.last:
            for i in range(mm.NWORDS):
                if t.dmem[i] != m.dmem[i]:
                    self._err(f"final: dmem[{i}] dut={t.dmem[i]} model={m.dmem[i]:#x}")
        else:
            m.step()


# ----------------------------------------------------------------------------------
# Functional coverage
# ----------------------------------------------------------------------------------
def _reg_bin(r):
    return "r0" if r == 0 else "r1_8" if r <= 8 else "r9_15" if r <= 15 else "r16_31"


def _corner(v):
    return {0: "zero", 0xFFFFFFFF: "ones", 0x80000000: "min", 0x7FFFFFFF: "max"}.get(v, "other")


def _sgn(v):
    return "zero" if v == 0 else "neg" if v & 0x80000000 else "pos"


def _word_bin(addr):
    w = (addr >> 2) & 0xFF
    return "w0_7" if w < 8 else "w8_63" if w < 64 else "w64_127" if w < 128 else "w128_255"


def _imm_sign(s):
    return "zero" if s == 0 else "neg" if s < 0 else "pos"


ALU_KINDS = ("add", "sub", "and", "or", "slt")
CORNERS = ("zero", "ones", "min", "max", "other")
RAW_BINS = ("none", "rs", "rt", "both")


@coverage_section(
    CoverPoint("mips.kind", xf=lambda e: e["kind"], bins=list(mm.KINDS)),
    CoverPoint("mips.rd_bin", xf=lambda e: e["rd_bin"] if e["kind"] in ALU_KINDS else None,
               bins=["r0", "r1_8", "r9_15", "r16_31"]),
    CoverPoint("mips.rs_bin", xf=lambda e: _reg_bin(e["rs"]) if e["kind"] != "illegal" else None,
               bins=["r0", "r1_8", "r9_15", "r16_31"]),
    CoverPoint("mips.rt_bin", xf=lambda e: _reg_bin(e["rt"]) if e["kind"] != "illegal" else None,
               bins=["r0", "r1_8", "r9_15", "r16_31"]),
    CoverPoint("mips.alu_result", xf=lambda e: _sgn(e["alu"]) if e["kind"] in ALU_KINDS else None,
               bins=["zero", "pos", "neg"]),
    CoverPoint("mips.kind_x_result",
               xf=lambda e: f'{e["kind"]}:{_sgn(e["alu"])}' if e["kind"] in ALU_KINDS else None,
               bins=[f"{k}:{r}" for k in ALU_KINDS for r in ("zero", "pos", "neg")
                     if not (k == "slt" and r == "neg")]),   # slt yields only 0/1: bin unreachable by construction
    CoverPoint("mips.addsub_operand_corners",
               xf=lambda e: f'{_corner(e["a"])}_{_corner(e["b"])}' if e["kind"] in ("add", "sub") else None,
               bins=[f"{x}_{y}" for x in CORNERS for y in CORNERS]),
    CoverPoint("mips.slt_operand_corners",
               xf=lambda e: f'{_corner(e["a"])}_{_corner(e["b"])}' if e["kind"] == "slt" else None,
               bins=[f"{x}_{y}" for x in CORNERS for y in CORNERS]),
    CoverPoint("mips.signed_overflow", xf=lambda e: ("yes" if e["ovf"] else "no")
               if e["kind"] in ("add", "sub") else None, bins=["no", "yes"]),
    CoverPoint("mips.slt_result", xf=lambda e: e["alu"] if e["kind"] == "slt" else None, bins=[0, 1]),
    CoverPoint("mips.beq_outcome", xf=lambda e: ("taken" if e["a"] == e["b"] else "not_taken")
               if e["kind"] == "beq" else None, bins=["taken", "not_taken"]),
    CoverPoint("mips.beq_offset", xf=lambda e: _imm_sign(e["simm"]) if e["kind"] == "beq" else None,
               bins=["neg", "zero", "pos"]),
    CoverPoint("mips.beq_outcome_x_offset",
               xf=lambda e: f'{"taken" if e["a"] == e["b"] else "not_taken"}:{_imm_sign(e["simm"])}'
               if e["kind"] == "beq" else None,
               bins=[f"{o}:{d}" for o in ("taken", "not_taken") for d in ("neg", "zero", "pos")]),
    CoverPoint("mips.mem_addr_x_op", xf=lambda e: f'{e["kind"]}:{_word_bin(e["alu"])}'
               if e["kind"] in ("lw", "sw") else None,
               bins=[f"{k}:{b}" for k in ("lw", "sw") for b in ("w0_7", "w8_63", "w64_127", "w128_255")]),
    CoverPoint("mips.mem_offset_sign", xf=lambda e: _imm_sign(e["simm"]) if e["kind"] in ("lw", "sw") else None,
               bins=["neg", "zero", "pos"]),
    CoverPoint("mips.raw_dependency", xf=lambda e: e["raw"], bins=list(RAW_BINS)),
    CoverPoint("mips.illegal_flavour", xf=lambda e: e["ill"] if e["kind"] == "illegal" else None,
               bins=["bad_funct", "bad_opcode"]),
)
def sample_cov(e):
    pass


class Coverage(uvm_subscriber):
    def start_of_simulation_phase(self):
        self.prev_dest = None

    def write(self, datum):
        if isinstance(datum, tuple):
            self.prev_dest = None
            return
        t = datum
        if t.last or None in (t.instr, t.rd1, t.rd2, t.alu):   # X on the DUT: scoreboard reports it
            return
        d = mm.decode(t.instr)
        k = d["kind"]
        rs_used = k in ("add", "sub", "and", "or", "slt", "lw", "sw", "beq")
        rt_used = k in ("add", "sub", "and", "or", "slt", "sw", "beq")
        raw_rs = bool(self.prev_dest and rs_used and d["rs"] == self.prev_dest)
        raw_rt = bool(self.prev_dest and rt_used and d["rt"] == self.prev_dest)
        raw = "both" if raw_rs and raw_rt else "rs" if raw_rs else "rt" if raw_rt else "none"
        a, b = t.rd1, t.rd2
        ovf = False
        if k == "add":
            ovf = mm.to_s32(a) + mm.to_s32(b) != mm.to_s32(t.alu)
        elif k == "sub":
            ovf = mm.to_s32(a) - mm.to_s32(b) != mm.to_s32(t.alu)
        sample_cov(dict(kind=k, rs=d["rs"], rt=d["rt"], rd=d["rd"], rd_bin=_reg_bin(d["rd"]),
                        a=a, b=b, alu=t.alu, simm=d["simm"], ovf=ovf, raw=raw,
                        ill="bad_opcode" if d["op"] != 0 else "bad_funct"))
        Results.by_kind[k] = Results.by_kind.get(k, 0) + 1
        self.prev_dest = (d["rd"] if k in ALU_KINDS else d["rt"] if k == "lw" else None) or None


# ----------------------------------------------------------------------------------
# Environment
# ----------------------------------------------------------------------------------
class MipsEnv(uvm_env):
    def build_phase(self):
        self.seqr = uvm_sequencer("seqr", self)
        self.driver = Driver("driver", self)
        self.monitor = Monitor("monitor", self)
        self.scoreboard = Scoreboard("scoreboard", self)
        self.coverage = Coverage("coverage", self)

    def connect_phase(self):
        self.driver.seq_item_port.connect(self.seqr.seq_item_export)
        for ap in (self.driver.ap, self.monitor.ap):
            ap.connect(self.scoreboard.analysis_export)
            ap.connect(self.coverage.analysis_export)
