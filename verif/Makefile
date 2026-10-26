# cocotb + pyuvm regression (Icarus Verilog).  Usage:
#   make                      # directed + 300 random programs on ../rtl
#   make N_RANDOM=1000 SEED=7
#   make RTL_DIR=$(pwd)/../rtl_orig   # same regression on the original (unfixed) RTL
SIM ?= icarus
TOPLEVEL_LANG = verilog
RTL_DIR ?= $(abspath ../rtl)
VERILOG_SOURCES = $(wildcard $(RTL_DIR)/*.v)
COCOTB_TOPLEVEL = mips_top
COCOTB_TEST_MODULES = test_mips
export PYTHONPATH := $(PWD):$(PYTHONPATH)
include $(shell cocotb-config --makefiles)/Makefile.sim
