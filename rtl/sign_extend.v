`timescale 1ns/1ps

module sign_extend(
    input [15:0] in_1,
    output [31:0] out
);

    assign out = {{16{in_1[15]}},in_1};
        
    // TODO: Implement sign_extend

endmodule
