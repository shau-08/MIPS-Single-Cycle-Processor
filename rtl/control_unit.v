`timescale 1ns/1ps

module control_unit(
  input  [5:0] Op,
    input  [5:0] Funct,
    output reg MemtoReg,
    output reg MemWrite,
    output reg Branch,
    output reg [2:0] ALUControl,
    output reg ALUSrc,
    output reg RegDst,
    output reg RegWrite
);
  always@(*)begin
  
    MemtoReg  = 0;
    MemWrite  = 0;
    Branch    = 0;
    ALUSrc    = 0;
    RegDst    = 0;
    RegWrite  = 0;
    ALUControl = 3'b010;
    case (Op)
        6'b000000: begin
            RegWrite = 1;
          RegDst   = 1;
            case (Funct)
                6'b100000: ALUControl = 3'b010; 
                6'b100010: ALUControl = 3'b110; 
             6'b100100: ALUControl = 3'b000; 
         6'b100101: ALUControl = 3'b001; 
         6'b101010: ALUControl = 3'b111; // slt (ALU implemented it, decoder never selected it)
            default:   begin RegWrite = 0; ALUControl = 3'b010; end // unsupported funct = NOP
            endcase
        end
        6'b100011: begin
            RegWrite  = 1;
            ALUSrc    = 1;
            MemtoReg  = 1;
            ALUControl = 3'b010; 
        end
        6'b101011: begin
           MemWrite  = 1;
            ALUSrc    = 1;
            ALUControl = 3'b010; 
        end
        6'b000100: begin
            Branch    = 1;
            ALUControl = 3'b110; 
        end
        default: begin
            MemtoReg  = 0;
            MemWrite  = 0;
          Branch    = 0;
            ALUSrc    = 0;
            RegDst    = 0;
            RegWrite  = 0;
          ALUControl = 3'b010;
        end
    endcase
end
endmodule
