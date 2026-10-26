`timescale 1ns/1ps

module mips_top(
    input clk,
    input reset,

    output [31:0] debug_pc,
    output [31:0] debug_alu,
    output [31:0] debug_result
);

    //=========================
    // Control Signals
    //=========================
    wire MemtoReg;
    wire MemWrite;
    wire Branch;
    wire ALUSrc;
    wire RegDst;
    wire RegWrite;
    wire [2:0] ALUControl;

    //=========================
    // Datapath Outputs
    //=========================
    wire [5:0] Op;
    wire [5:0] Funct;
    wire Zero;

    //=========================
    // Debug Wires
    //=========================
    wire [31:0] DebugPC;
    wire [31:0] DebugALU;
    wire [31:0] DebugResult;

    //=========================
    // Control Unit
    //=========================
    control_unit CU(
        .Op(Op),
        .Funct(Funct),
        .MemtoReg(MemtoReg),
        .MemWrite(MemWrite),
        .Branch(Branch),
        .ALUControl(ALUControl),
        .ALUSrc(ALUSrc),
        .RegDst(RegDst),
        .RegWrite(RegWrite)
    );

    //=========================
    // Datapath
    //=========================
    datapath DP(
        .clk(clk),
        .reset(reset),

        .RegWrite(RegWrite),
        .MemWrite(MemWrite),
        .MemtoReg(MemtoReg),
        .Branch(Branch),
        .ALUSrc(ALUSrc),
        .RegDst(RegDst),
        .ALUControl(ALUControl),

        .Op(Op),
        .Funct(Funct),
        .Zero(Zero),

        .DebugPC(DebugPC),
        .DebugALU(DebugALU),
        .DebugResult(DebugResult)
    );

    //=========================
    // Debug Outputs
    //=========================
    assign debug_pc     = DebugPC;
    assign debug_alu    = DebugALU;
    assign debug_result = DebugResult;

endmodule
