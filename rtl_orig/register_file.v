`timescale 1ns/1ps

module register_file(
    input [4:0] A1,
    input [4:0] A2,
    input [4:0] A3,
    input clk,
    input WE,
    output [31:0] RD1,
    output [31:0] RD2,
    input [31:0] WD3
);

reg [31:0] reg_ptr [31:0];


assign RD1 = (A1 == 5'd0) ? 32'd0 : reg_ptr[A1];
assign RD2 = (A2 == 5'd0) ? 32'd0 : reg_ptr[A2];


always @(posedge clk)
begin
    if (WE && A3 != 5'd0)
        reg_ptr[A3] <= WD3;
end

endmodule
