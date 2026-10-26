import os
import cocotb
from cocotb.clock import Clock
from pyuvm import ConfigDB, uvm_root, uvm_test

import mips_env as E

N_RANDOM = int(os.getenv("N_RANDOM", "300"))
SEED = int(os.getenv("SEED", "1"))
RUN_DIRECTED = os.getenv("RUN_DIRECTED", "1") == "1"


class MipsTest(uvm_test):
    def build_phase(self):
        self.env = E.MipsEnv("env", self)

    async def run_phase(self):
        self.raise_objection()
        if RUN_DIRECTED:
            await E.DirectedSeq("directed").start(self.env.seqr)
        if N_RANDOM:
            await E.RandomSeq("random", n=N_RANDOM, seed=SEED).start(self.env.seqr)
        self.drop_objection()


@cocotb.test()
async def regression(dut):
    E.reset_results()
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    E.RunState.dut = dut
    await uvm_root().run_test("MipsTest")
    R = E.Results
    dut._log.info(f"programs={R.programs} (directed={R.directed_programs}, random={R.random_programs}) "
                  f"cycles_compared={R.steps} mismatches={R.mismatches} "
                  f"failing_programs={len(R.failed_programs)}")
    for e in R.first_errors:
        dut._log.error(e)
    from cocotb_coverage.coverage import coverage_db
    coverage_db.export_to_yaml(filename="coverage.yml")
    coverage_db.report_coverage(dut._log.info, bins=False)
    with open("results.txt", "w") as f:
        f.write(f"programs {R.programs}\ndirected {R.directed_programs}\nrandom {R.random_programs}\n"
                f"cycles {R.steps}\nmismatches {R.mismatches}\nfailing_programs {len(R.failed_programs)}\n")
        f.write("exec_by_kind " + " ".join(f"{k}={v}" for k, v in sorted(R.by_kind.items())) + "\n")
    assert R.mismatches == 0, f"{R.mismatches} mismatches in {len(R.failed_programs)} programs"
