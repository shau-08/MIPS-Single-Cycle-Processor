`timescale 1ns/1ps

module shift_left2(
    input [31:0] in_1,
    output [31:0] out
);

    assign out = in_1 << 2;// TODO: Implement shift_left2

endmodule
