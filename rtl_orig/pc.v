`timescale 1ns/1ps

module pc(
    input [31:0]PCNext,
    input clk,
    input reset,

    output reg [31:0]PC
);
always@(posedge clk)
begin
if(reset)
    PC<=32'b0;
else
    PC<=PCNext;
end
endmodule

   
