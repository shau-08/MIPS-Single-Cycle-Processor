`timescale 1ns/1ps

module datapath(
    input clk,
    input reset,

    // Control signals from control_unit
    input RegWrite,
    input MemWrite,
    input MemtoReg,
    input Branch,
    input ALUSrc,
    input RegDst,
    input [2:0] ALUControl,

    // To control_unit
    output [5:0] Op,
    output [5:0] Funct,
    output Zero,

    // Debug Outputs
    output [31:0] DebugPC,
    output [31:0] DebugALU,
    output [31:0] DebugResult
);

    //========================
    // Internal wires
    //========================
    wire [31:0] PC;
    wire [31:0] PCNext;
    wire [31:0] PCPlus4;

    wire [31:0] Instr;

    wire [4:0] WriteReg;

    wire [31:0] RD1;
    wire [31:0] RD2;

    wire [31:0] SignImm;
    wire [31:0] ShiftImm;

    wire [31:0] SrcB;

    wire [31:0] ALUResult;

    wire [31:0] ReadData;

    wire [31:0] Result;

    wire [31:0] BranchAddr;

    wire PCSrc;

    //========================
    // Outputs to controller
    //========================
    assign Op    = Instr[31:26];
    assign Funct = Instr[5:0];

    assign PCSrc = Branch & Zero;

    //========================
    // Program Counter
    //========================
    pc PC_REG(
        .PCNext(PCNext),
        .clk(clk),
        .reset(reset),
        .PC(PC)
    );

    //========================
    // Instruction Memory
    //========================
    instruction_memory IM(
        .PC(PC),
        .Instr(Instr)
    );

    //========================
    // PC + 4
    //========================
    adder ADD_PC(
        .in_1(PC),
        .in_2(32'd4),
        .out(PCPlus4)
    );

    //========================
    // Register Destination MUX
    //========================
    mux2 #(5) REGDSTMUX(
        .a(Instr[20:16]),
        .b(Instr[15:11]),
        .c(RegDst),
        .d(WriteReg)
    );

    //========================
    // Register File
    //========================
    register_file RF(
        .A1(Instr[25:21]),
        .A2(Instr[20:16]),
        .A3(WriteReg),
        .clk(clk),
        .WE(RegWrite),
        .RD1(RD1),
        .RD2(RD2),
        .WD3(Result)
    );

    //========================
    // Sign Extend
    //========================
    sign_extend SE(
        .in_1(Instr[15:0]),
        .out(SignImm)
    );

    //========================
    // ALU Source MUX
    //========================
    mux2 #(32) ALUSRCMUX(
        .a(RD2),
        .b(SignImm),
        .c(ALUSrc),
        .d(SrcB)
    );

    //========================
    // ALU
    //========================
    alu ALU(
        .SrcA(RD1),
        .SrcB(SrcB),
        .ALUControl(ALUControl),
        .Zero(Zero),
        .ALUResult(ALUResult)
    );

    //========================
    // Data Memory
    //========================
    data_memory DM(
        .clk(clk),
        .A(ALUResult),
        .WE(MemWrite),
        .WD(RD2),
        .RD(ReadData)
    );

    //========================
    // Write Back MUX
    //========================
    mux2 #(32) MEMTOREGMUX(
        .a(ALUResult),
        .b(ReadData),
        .c(MemtoReg),
        .d(Result)
    );

    //========================
    // Branch Address
    //========================
    shift_left2 SL2(
        .in_1(SignImm),
        .out(ShiftImm)
    );

    adder BRANCHADD(
        .in_1(PCPlus4),
        .in_2(ShiftImm),
        .out(BranchAddr)
    );

    //========================
    // Next PC MUX
    //========================
    mux2 #(32) PCMUX(
        .a(PCPlus4),
        .b(BranchAddr),
        .c(PCSrc),
        .d(PCNext)
    );

    //========================
    // Debug Outputs
    //========================
    assign DebugPC     = PC;
    assign DebugALU    = ALUResult;
    assign DebugResult = Result;

endmodule
