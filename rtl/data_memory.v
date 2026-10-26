`timescale 1ns/1ps

module data_memory(
    input clk,
    input [31:0] A,
    input WE,
    input [31:0] WD,
    output [31:0] RD
);

 reg [31:0] data_mem [255:0];
 
 assign RD =  data_mem[A[9:2]];

 always@(posedge clk)
    begin
        if(WE)
            data_mem[A[9:2]] <= WD;
    end
    // TODO: Implement data_memory

endmodule
