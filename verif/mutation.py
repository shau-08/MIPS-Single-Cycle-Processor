#!/usr/bin/env python3
"""Mutation test: inject one RTL bug at a time into rtl/ and check the regression kills it.
Usage: python3 mutation.py [N_RANDOM] [SEED]      -> writes mutation_report.txt"""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.join(HERE, "..", "rtl")
N = sys.argv[1] if len(sys.argv) > 1 else "100"
SEED = sys.argv[2] if len(sys.argv) > 2 else "1"

# (name, file, old, new)
MUTANTS = [
    ("alu: AND -> OR",              "alu.v", "SrcA & SrcB", "SrcA | SrcB"),
    ("alu: OR -> AND",              "alu.v", "SrcA | SrcB", "SrcA & SrcB"),
    ("alu: ADD -> SUB",             "alu.v", "SrcA + SrcB", "SrcA - SrcB"),
    ("alu: SUB -> ADD",             "alu.v", "SrcA - SrcB", "SrcA + SrcB"),
    ("alu: signed slt -> unsigned", "alu.v", "($signed(SrcA)<$signed(SrcB))", "(SrcA<SrcB)"),
    ("alu: Zero polarity",          "alu.v", "(ALUResult == 32'd0)", "(ALUResult != 32'd0)"),
    ("ctrl: sw MemWrite dropped",   "control_unit.v", "MemWrite  = 1;", "MemWrite  = 0;"),
    ("ctrl: lw MemtoReg dropped",   "control_unit.v", "MemtoReg  = 1;", "MemtoReg  = 0;"),
    ("ctrl: R-type RegDst dropped", "control_unit.v", "RegDst   = 1;", "RegDst   = 0;"),
    ("ctrl: lw ALUSrc dropped",     "control_unit.v", "RegWrite  = 1;\n            ALUSrc    = 1;\n            MemtoReg",
                                                      "RegWrite  = 1;\n            ALUSrc    = 0;\n            MemtoReg"),
    ("ctrl: beq uses ADD",          "control_unit.v", "Branch    = 1;\n            ALUControl = 3'b110;",
                                                      "Branch    = 1;\n            ALUControl = 3'b010;"),
    ("ctrl: slt funct -> ADD",      "control_unit.v", "6'b101010: ALUControl = 3'b111;", "6'b101010: ALUControl = 3'b010;"),
    ("ctrl: bad funct writes reg",  "control_unit.v", "default:   begin RegWrite = 0;", "default:   begin RegWrite = 1;"),
    ("ctrl: bad opcode writes reg", "control_unit.v", "          Branch    = 0;\n            ALUSrc    = 0;\n            RegDst    = 0;\n            RegWrite  = 0;",
                                                      "          Branch    = 0;\n            ALUSrc    = 0;\n            RegDst    = 0;\n            RegWrite  = 1;"),
    ("rf: r0 write guard removed",  "register_file.v", "WE && A3 != 5'd0", "WE"),
    ("rf: r0 read forced-zero off", "register_file.v", "assign RD1 = (A1 == 5'd0) ? 32'd0 : reg_ptr[A1];", "assign RD1 = reg_ptr[A1];"),
    ("sext: zero-extend",           "sign_extend.v", "{{16{in_1[15]}},in_1}", "{16'b0,in_1}"),
    ("branch: missing <<2",         "shift_left2.v", "in_1 << 2", "in_1"),
    ("branch: taken when !Zero",    "datapath.v", "Branch & Zero", "Branch & ~Zero"),
    ("branch: base is PC not PC+4", "datapath.v", ".in_1(PCPlus4),\n        .in_2(ShiftImm)", ".in_1(PC),\n        .in_2(ShiftImm)"),
    ("dmem: write always enabled",  "data_memory.v", "if(WE)", "if(1'b1)"),
    ("dmem: word index off by one", "data_memory.v", "assign RD =  data_mem[A[9:2]];", "assign RD =  data_mem[A[9:2] + 8'd1];"),
    ("pc: reset ignored",           "pc.v", "if(reset)", "if(1'b0)"),
]

killed, rows = 0, []
for name, fn, old, new in MUTANTS:
    with tempfile.TemporaryDirectory() as td:
        rtl = os.path.join(td, "rtl"); shutil.copytree(RTL, rtl)
        p = os.path.join(rtl, fn); s = open(p).read()
        if old not in s:
            rows.append((name, "PATTERN-NOT-FOUND", "")); print(name, "PATTERN NOT FOUND"); continue
        open(p, "w").write(s.replace(old, new, 1))
        env = dict(os.environ, RTL_DIR=rtl, SIM_BUILD=os.path.join(td, "sb"), N_RANDOM=N, SEED=SEED,
                   COCOTB_RESULTS_FILE=os.path.join(td, "r.xml"))
        r = subprocess.run(["make", "-C", HERE], env=env, capture_output=True, text=True)
        out = r.stdout + r.stderr
        res = {}
        for ln in out.splitlines():
            if "programs=" in ln:
                res["line"] = ln.split("programs=")[1]
        dead = r.returncode != 0
        killed += dead
        rows.append((name, "KILLED" if dead else "SURVIVED", res.get("line", "")))
        print(f"{'KILLED  ' if dead else 'SURVIVED'} {name}   {res.get('line','')}", flush=True)

tot = len([r for r in rows if r[1] != "PATTERN-NOT-FOUND"])
msg = f"mutants killed: {killed}/{tot}"
print(msg)
with open(os.path.join(HERE, "mutation_report.txt"), "w") as f:
    f.write(f"N_RANDOM={N} SEED={SEED}\n")
    for n, st, d in rows:
        f.write(f"{st:9s} {n:32s} {d}\n")
    f.write(msg + "\n")
