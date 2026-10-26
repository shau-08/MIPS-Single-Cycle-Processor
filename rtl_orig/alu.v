`timescale 1ns/1ps

module alu(
    input [31:0]SrcA,
    input [31:0]SrcB,
    input [2:0]ALUControl,

    output Zero,
    output reg [31:0]ALUResult
);
always @(*)
begin
case(ALUControl)
3'b000: ALUResult = SrcA & SrcB;
3'b001: ALUResult = SrcA | SrcB;
3'b010: ALUResult = SrcA + SrcB;
3'b110: ALUResult = SrcA - SrcB;
3'b111: ALUResult = ($signed(SrcA)<$signed(SrcB)) ? 32'd1 : 32'd0;
default: ALUResult = 32'd0;
endcase
end
assign Zero = (ALUResult == 32'd0);
endmodule
