# Blink the three LEDs in a counting pattern.
from sys import getrecursionlimit, setrecursionlimit

setrecursionlimit(getrecursionlimit() * 10000)

import numpy as np
from nmigen import *
from nmigen.lib.fifo import AsyncFIFO
from nmigen.hdl.rec import *

from nmigen.sim import Simulator, Delay, Settle

from brainfuck import Brainfuck_processor

class Sim_top(Elaboratable):
    def __init__(self, brainfuck_code_file, brainfuck_array_size=int(2**15)):
        self.brainfuck_array_size = brainfuck_array_size        
        self.brainfuck_code = []
        for c in brainfuck_code_file.read():
            if c in [">", "<", "+", "-", ".", ",", "[", "]"]:
                self.brainfuck_code.append(ord(c))
                print(c, end="")
        print("")

        self.so_data = Signal(8)
        self.so_valid = Signal()
        self.so_ready = Signal()

        self.si_data = Signal(8)
        self.si_valid = Signal()
        self.si_ready = Signal()

        self.CPU = None

    def elaborate(self, platform):
        m = Module()

        sync_n = ClockDomain("sync_n", clk_edge="neg")
        m.d.comb += [sync_n.clk.eq(ClockSignal("sync")),sync_n.rst.eq(ResetSignal("sync"))]
        m.domains.sync_n = sync_n
        
        m.submodules.instruction_file_r = instruction_file_r = Memory(width=8, depth=len(self.brainfuck_code), init=self.brainfuck_code).read_port()
        register_file_mem = Memory(width=8, depth=self.brainfuck_array_size)
        m.submodules.register_file_r = register_file_r = register_file_mem.read_port()
        m.submodules.register_file_w = register_file_w = register_file_mem.write_port()
        m.submodules.CPU = self.CPU = Brainfuck_processor(len(self.brainfuck_code), data_width=register_file_r.data.width, i_addr_width=instruction_file_r.addr.width, d_addr_width=register_file_r.addr.width, stack_depth=32)


        m.d.comb += [
            self.so_data.eq(self.CPU.output_stream.data),
            self.so_valid.eq(self.CPU.output_stream.valid),
            self.CPU.output_stream.ready.eq(self.so_ready),

            self.CPU.input_stream.data.eq(self.si_data),
            self.CPU.input_stream.valid.eq(self.si_valid),
            self.si_ready.eq(self.CPU.input_stream.ready),

            instruction_file_r.addr.eq(self.CPU.instruction_port.addr),
            self.CPU.instruction_port.r_data.eq(instruction_file_r.data),

            register_file_r.addr.eq(self.CPU.data_port.addr),
            self.CPU.data_port.r_data.eq(register_file_r.data),
            register_file_w.addr.eq(self.CPU.data_port.addr),
            register_file_w.data.eq(self.CPU.data_port.w_data),
            register_file_w.en.eq(self.CPU.data_port.w_en)
        ]
        
        return m


if __name__ == "__main__":
    with open("infinite_helloworld.bf", "r") as f:
        m = Module()
        m.submodules.DUT = DUT = Sim_top(f, brainfuck_array_size=64)

        sim = Simulator(m)

        def process():
            yield DUT.si_data.eq(ord("A"))
            yield DUT.si_valid.eq(0)
            yield DUT.so_ready.eq(0)
            for _ in range(3210):
                yield 
            yield DUT.si_valid.eq(1)
            yield DUT.so_ready.eq(1)
            yield

        sim.add_clock(0.02083e-6, domain="sync")
        sim.add_sync_process(process)
        with sim.write_vcd("bf_tb.vcd", "bf_tb.gtkw"):
            sim.run_until(500e-5, run_passive=True)
