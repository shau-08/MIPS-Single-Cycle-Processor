# MIPS Single-Cycle Processor (Verilog) + pyuvm Verification

32-bit single-cycle MIPS subset: `add sub and or slt lw sw beq`. Unsupported opcodes/functs are NOPs;
`$0` is hard-wired to zero; data memory is 256 words (1 KB, address mirrored modulo 1 KB).

## Verification environment (`verif/`)
UVM-structured, written with **pyuvm + cocotb** on **Icarus Verilog** (no commercial simulator needed):

| UVM role | File / class |
|---|---|
| sequence item / sequences | `ProgItem`, `DirectedSeq`, `RandomSeq` (`mips_env.py`) |
| constrained-random | cocotb-coverage CRV (`AluItem`, `MemItem`, `BrItem`, `IllItem`) |
| driver / monitor | `Driver` (back-door program load, reset, clocking) / `Monitor` (PC, regs, memory each cycle) |
| scoreboard | lock-step compare vs. golden ISA model `mips_model.py` (PC + all 32 regs every cycle, memory at end) |
| functional coverage | 17 coverpoints / 120 bins incl. crosses (op x result, operand corners, beq outcome x offset, RAW hazards, ...) |

```
cd verif
make N_RANDOM=300 SEED=1                    # one run
python3 run_regression.py --seeds 8 --n 400 # parallel multi-seed regression + merged coverage
python3 mutation.py 100 1                   # inject 23 RTL bugs, check each is caught
make RTL_DIR=$PWD/../rtl_orig               # same regression on the original, unfixed RTL
```

## Results (measured; reports in `verif/`)
* **8 seeds x 412 programs = 3,296 programs, 157,126 compared cycles, 0 mismatches** on fixed RTL (`regression_summary.txt`).
* **Merged functional coverage: 120/120 bins (100%)**. Random alone reached 113/120 (94%); the holes
  (rare operand-corner pairs, not-taken backward `beq`) were closed with directed tests.
  One cross bin (`slt:neg`) is excluded as unreachable by construction (slt returns 0/1).
* **Mutation testing: 22/23 injected bugs killed.** The survivor (`$0` read-mask removed) is an
  equivalent mutant: with the `$0` write guard in place `reg_ptr[0]` can never be non-zero.
* Original RTL fails the same regression on every seed (26k-30k mismatches per seed; 286/308 programs failing in a 300-random run) (`regression_summary_orig.txt`).

## RTL defects found (and fixed in `rtl/`; originals kept in `rtl_orig/`)
1. **`slt` never decoded**: ALU implemented it but the control unit's funct decode had no `101010` case, so `slt` executed as `add`.
2. **Unsupported R-type funct codes executed as ADD** (decoder `default` kept `RegWrite=1`); now NOPs.
3. **Out-of-range data-memory index** (`A[31:2]` into a 256-word array) produced `X`; index now `A[9:2]`
   (1 KB mirror). Same truncation applied to instruction fetch (`PC[9:2]`) to clear a Verilator WIDTHTRUNC lint warning.

Defects 1-2 are relative to the spec above (the repo README had no spec text; the supported-op set was inferred from the control unit).
