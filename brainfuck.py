import numpy as np
from nmigen import *
from nmigen.lib.fifo import AsyncFIFO
from nmigen.hdl.rec import *

class RVStreamLayout(Layout):
    def __init__(self, width):
        super().__init__([
            ("data", unsigned(width)),
            ("valid", 1),
            ("ready", 1),
        ])
class RVStream(Record):
    def __init__(self, width):
        super().__init__(RVStreamLayout(width))

class MemoryInterfaceLayout(Layout):
    def __init__(self, data_width, addr_width, read_only):
        super().__init__([
            ("w_data", unsigned(data_width)),
            ("r_data", unsigned(data_width)),
            ("addr", unsigned(addr_width)),
            ("w_en", 1)] if not read_only else [
            ("r_data", unsigned(data_width)),
            ("addr", unsigned(addr_width))
        ])
class MemoryInterface(Record):
    def __init__(self, data_width, addr_width, read_only=False):
        super().__init__(MemoryInterfaceLayout(data_width, addr_width, read_only))

class Brainfuck_processor(Elaboratable):
    def __init__(self, number_of_instructions, data_width=8, i_addr_width=10, d_addr_width=10, stack_depth=16):
        self.number_of_instructions = number_of_instructions
        self.stack_depth=stack_depth
        self.input_stream  = RVStream(data_width)
        self.output_stream = RVStream(data_width)
        self.data_port = MemoryInterface(data_width, d_addr_width)
        self.instruction_port = MemoryInterface(8, i_addr_width, read_only=True)
        self.error = Signal()

    def elaborate(self, platform):
        m = Module()
        
        i_addr_width = self.instruction_port.addr.width
        stack_width = i_addr_width + int(np.ceil(np.log2(self.stack_depth)))
        stack_mem = Memory(width=stack_width, depth=self.stack_depth, init=[0 for _ in range(self.stack_depth)])
        m.submodules.stack_rdport = stack_rdport = stack_mem.read_port()
        m.submodules.stack_wrport = stack_wrport = stack_mem.write_port()
        stack = MemoryInterface(stack_width, stack_rdport.addr.width)
        m.d.comb += [stack_rdport.addr.eq(stack.addr),
                     stack_wrport.addr.eq(stack.addr),
                     stack_wrport.en  .eq(stack.w_en),
                     stack_wrport.data.eq(stack.w_data),
                     stack.r_data     .eq(stack_rdport.data)
                    ]

        m.d.comb += self.output_stream.data.eq(self.data_port.r_data)
         
        sync_n = ClockDomain("sync_n", clk_edge="neg")
        m.d.comb += [sync_n.clk.eq(ClockSignal("sync")),sync_n.rst.eq(ResetSignal("sync"))]
        m.domains.sync_n = sync_n
 

        with m.FSM() as fsm:
            with m.State("FETCH"):
                with m.Switch(self.instruction_port.r_data):
                    for instruction in [">", "<", "+", "-", ".", ",", "[", "]"]:
                        with m.Case(ord(instruction)):
                            m.next = instruction
                    with m.Default():
                        m.next = "ERROR"
                m.d.sync_n += [self.data_port.w_en.eq(0), stack.w_en.eq(0)]
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(0)]

            with m.State(">"):
                m.next = "FETCH"
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(0)] #Move instruction ptr
                m.d.sync_n += [self.instruction_port.addr.eq(self.instruction_port.addr + 1),
                               self.data_port.addr.eq(self.data_port.addr + 1) #Increment data ptr
                            ]

            with m.State("<"):
                m.next = "FETCH" 
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(0)]
                m.d.sync_n += [self.data_port.addr.eq(self.data_port.addr - 1), #Decrement data ptr
                               self.instruction_port.addr.eq(self.instruction_port.addr + 1)
                            ]

            with m.State("+"):
                m.next = "FETCH"
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(0)]
                m.d.sync_n += [self.data_port.w_data.eq(self.data_port.r_data + 1), #As the FETCH state comes inbetween operations, we can writeback directly
                             self.data_port.w_en.eq(1),
                             self.instruction_port.addr.eq(self.instruction_port.addr + 1)
                             ]

            with m.State("-"):
                m.next = "FETCH"  
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(0)]
                m.d.sync_n += [self.data_port.w_data.eq(self.data_port.r_data - 1), #As the FETCH state comes inbetween operations, we can writeback directly
                             self.instruction_port.addr.eq(self.instruction_port.addr + 1),
                             self.data_port.w_en.eq(1)]

            with m.State("."):
                m.d.comb += [self.output_stream.valid.eq(1), self.input_stream.ready.eq(0), self.error.eq(0)]
                with m.If(self.output_stream.ready):
                    m.d.sync_n += self.instruction_port.addr.eq(self.instruction_port.addr + 1)
                    m.next = "FETCH"
                with m.Else(): 
                    m.next = "."

            with m.State(","):
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(1), self.error.eq(0)]
                with m.If(self.input_stream.valid): 
                    m.d.sync_n += [self.instruction_port.addr.eq(self.instruction_port.addr + 1),
                                   self.data_port.w_data.eq(self.input_stream.data),
                                   self.data_port.w_en.eq(1)]
                    m.next = "FETCH"
                with m.Else():
                    m.next = ","

            with m.State("["):
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(0)]
                with m.If(self.instruction_port.r_data == ord("[")):
                    with m.If(self.data_port.r_data == 0):
                        m.next = "["
                        m.d.sync_n += [stack.w_data[:i_addr_width].eq(self.instruction_port.addr),
                                     stack.w_data[i_addr_width:].eq(stack.addr),
                                     stack.w_en.eq(1),
                                     stack.addr.eq(stack.addr + 1),
                                     self.instruction_port.addr.eq(self.instruction_port.addr + 1)]
                    with m.Else():
                        m.next = "FETCH"
                        m.d.sync_n += [self.instruction_port.addr.eq(self.instruction_port.addr + 1),
                                       stack.w_en.eq(0)]
                with m.Elif(self.instruction_port.r_data == ord("]")):
                    with m.If(stack.addr == (stack.r_data[i_addr_width:] + 1)):
                        m.next = "FETCH"
                    with m.Else():
                        m.next = "["
                    m.d.sync_n += [self.instruction_port.addr.eq(self.instruction_port.addr + 1),
                                   stack.w_en.eq(0),
                                   stack.addr.eq(stack.addr - 1)]
                with m.Else():
                    m.next = "["
                    m.d.sync_n += [self.instruction_port.addr.eq(self.instruction_port.addr + 1), stack.w_en.eq(0)]
                    
            with m.State("]"):
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(0)]
                with m.If(self.data_port.r_data != 0):
                    m.next = "]2"  
                    m.d.sync_n += stack.addr.eq(stack.addr - 1)
                with m.Else():
                    m.next = "FETCH"
                    m.d.sync_n += self.instruction_port.addr.eq(self.instruction_port.addr + 1) 
        
            with m.State("]2"):
                m.next = "]3" 
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(0)]
                m.d.sync_n += stack.addr.eq(stack.r_data[i_addr_width:])

            with m.State("]3"):
                m.next = "FETCH"
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(0)]
                m.d.sync_n += self.instruction_port.addr.eq(stack.r_data[:i_addr_width] + 1)
            with m.State("ERROR"):
                m.d.comb += [self.output_stream.valid.eq(0), self.input_stream.ready.eq(0), self.error.eq(1)]
                m.next = "ERROR"

        return m
