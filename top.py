# Blink the three LEDs in a counting pattern.

import numpy as np
from nmigen import *
from nmigen.lib.fifo import AsyncFIFO
from nmigen.hdl.rec import *

from luna.gateware.platform.orangecrab import OrangeCrabPlatformR0D2
from luna.full_devices   import USBSerialDevice

from brainfuck import Brainfuck_processor

class PWM(Elaboratable):
    def __init__(self, width):
        self.width = width
        self.pwm = Signal()
        self.dutyCycle = Signal(width, reset=0)
        self.counter = Signal(width, reset=0)

    def elaborate(self, platform):
        m = Module()
        m.d.sync += self.counter.eq(self.counter + 1)
        m.d.comb += self.pwm.eq(self.counter > self.dutyCycle)
        return m

class Top(Elaboratable):
    def __init__(self, brainfuck_code_file, brainfuck_array_size=128):
        self.brainfuck_array_size = brainfuck_array_size        
        self.brainfuck_code = []
        for c in brainfuck_code_file.read():
            if c in [">", "<", "+", "-", ".", ",", "[", "]"]:
                self.brainfuck_code.append(ord(c))
                print(c, end="")
        print("")

    def elaborate(self, platform):
        m = Module()
        
        m.submodules.car = platform.clock_domain_generator()

        sync_n = ClockDomain("sync_n", clk_edge="neg")
        m.d.comb += [sync_n.clk.eq(ClockSignal("sync")),sync_n.rst.eq(ResetSignal("sync"))]
        m.domains.sync_n = sync_n

        
        # Create our USB-to-serial converter.
        usb0 = platform.request(platform.default_usb_connection)
        m.submodules.usb_serial = usb_serial = \
                USBSerialDevice(bus=usb0, idVendor=0x16d0, idProduct=0x0f3b)
         
        m.submodules.usb_to_sys_fifo = usb_to_sys_fifo = AsyncFIFO(width=(usb_serial.rx.payload.width + 2), depth=2, r_domain="sync_n", w_domain="usb")
        m.submodules.sys_to_usb_fifo = sys_to_usb_fifo = AsyncFIFO(width=(usb_serial.tx.payload.width + 2), depth=2, r_domain="usb", w_domain="sync_n")
        
        m.d.comb += [ 
            usb_serial.tx.payload.eq(sys_to_usb_fifo.r_data[2:]),
            usb_serial.tx.valid  .eq(sys_to_usb_fifo.r_rdy),
            usb_serial.tx.first  .eq(sys_to_usb_fifo.r_data[0]),
            usb_serial.tx.last   .eq(sys_to_usb_fifo.r_data[1]),
            sys_to_usb_fifo.r_en .eq(usb_serial.tx.ready),

            usb_to_sys_fifo.w_data[2:].eq(usb_serial.rx.payload),
            usb_to_sys_fifo.w_en      .eq(usb_serial.rx.valid),
            usb_to_sys_fifo.w_data[0] .eq(usb_serial.rx.first),
            usb_to_sys_fifo.w_data[1] .eq(usb_serial.rx.last),
            usb_serial.rx.ready       .eq(usb_to_sys_fifo.w_rdy),
            # ... and always connect by default.
            usb_serial.connect     .eq(1)
        ]
        
        m.submodules.instruction_file_r = instruction_file_r = Memory(width=8, depth=len(self.brainfuck_code), init=self.brainfuck_code).read_port()
        register_file_mem = Memory(width=usb_serial.rx.payload.width, depth=self.brainfuck_array_size)
        m.submodules.register_file_r = register_file_r = register_file_mem.read_port()
        m.submodules.register_file_w = register_file_w = register_file_mem.write_port()
        m.submodules.CPU = CPU = Brainfuck_processor(len(self.brainfuck_code), data_width=register_file_r.data.width, i_addr_width=instruction_file_r.addr.width, d_addr_width=register_file_r.addr.width, stack_depth=32)

        m.d.comb += [
            sys_to_usb_fifo.w_data[0].eq(1),
            sys_to_usb_fifo.w_data[1].eq(1),
            sys_to_usb_fifo.w_data[2:].eq(CPU.output_stream.data),
            sys_to_usb_fifo.w_en.eq(CPU.output_stream.valid),
            CPU.output_stream.ready.eq(sys_to_usb_fifo.w_rdy),

            CPU.input_stream.data.eq(usb_to_sys_fifo.r_data[2:]),
            CPU.input_stream.valid.eq(usb_to_sys_fifo.r_rdy),
            usb_to_sys_fifo.r_en.eq(CPU.input_stream.ready),

            instruction_file_r.addr.eq(CPU.instruction_port.addr),
            CPU.instruction_port.r_data.eq(instruction_file_r.data),

            register_file_r.addr.eq(CPU.data_port.addr),
            CPU.data_port.r_data.eq(register_file_r.data),
            register_file_w.addr.eq(CPU.data_port.addr),
            register_file_w.data.eq(CPU.data_port.w_data),
            register_file_w.en.eq(CPU.data_port.w_en)
        ]
        

        rgb = platform.request('rgb_led', 0)
        red_led = rgb.r
        green_led = rgb.g
        blue_led = rgb.b
        
        m.submodules.pwm0 = pwm0 = PWM(8)
        m.submodules.pwm1 = pwm1 = PWM(8)
        m.submodules.pwm2 = pwm2 = PWM(8)
        
        m.d.comb += [
            pwm0.dutyCycle.eq(102),
            pwm1.dutyCycle.eq(101),
            pwm2.dutyCycle.eq(100),
            red_led.o.eq(Mux(instruction_file_r.addr[0], pwm0.pwm, 0)),
            green_led.o.eq(Mux(CPU.error, pwm1.pwm, 0)),
            blue_led.o.eq(Mux(CPU.error, pwm2.pwm, 0)),
        ]

        return m


if __name__ == "__main__":
    platform = OrangeCrabPlatformR0D2()
    with open("infinite_helloworld.bf", "r") as f:
        platform.build(Top(f), do_program=True)
