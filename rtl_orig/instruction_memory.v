`timescale 1ns/1ps

module instruction_memory(
        input [31:0]PC,

        output [31:0]Instr     
);
        reg [31:0] memory [255:0];
    initial begin
    $readmemh("program.mem",memory);
    end
    assign Instr =memory[PC[31:2]];

endmodule
