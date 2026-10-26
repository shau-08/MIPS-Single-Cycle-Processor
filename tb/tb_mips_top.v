`timescale 1ns/1ps

module tb_mips_top;

reg clk;
reg reset;

mips_top uut(
    .clk(clk),
    .reset(reset)
);

// Clock
always #5 clk = ~clk;

integer i;

initial begin
    clk = 0;
    reset = 1;

    // Initialize register file
    for(i = 0; i < 32; i = i + 1)
        uut.DP.RF.reg_ptr[i] = 32'd0;

    // Initial values
    uut.DP.RF.reg_ptr[1] = 32'd5;
    uut.DP.RF.reg_ptr[2] = 32'd7;

    // Initialize Data Memory
    for(i = 0; i < 256; i = i + 1)
        uut.DP.DM.data_mem[i] = 32'd0;

    #20;
    reset = 0;

    #300;

    $display("----------------------------");
    $display("R1  = %d", uut.DP.RF.reg_ptr[1]);
    $display("R2  = %d", uut.DP.RF.reg_ptr[2]);
    $display("R3  = %d", uut.DP.RF.reg_ptr[3]);
    $display("R4  = %d", uut.DP.RF.reg_ptr[4]);
    $display("R5  = %d", uut.DP.RF.reg_ptr[5]);
    $display("R6  = %d", uut.DP.RF.reg_ptr[6]);
    $display("MEM[0] = %d", uut.DP.DM.data_mem[0]);
    $display("----------------------------");

    $finish;
end

endmodule
