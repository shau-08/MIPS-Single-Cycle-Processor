`timescale 1ns/1ps
module mux2 #(parameter WIDTH = 32)
(
    input  [WIDTH-1:0] a,
    input  [WIDTH-1:0] b,
    input              c,
    output [WIDTH-1:0] d
);

assign d = c ? b : a;

endmodule
