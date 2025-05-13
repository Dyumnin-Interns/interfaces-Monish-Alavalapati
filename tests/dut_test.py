import os
import random
import cocotb
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ReadOnly, NextTimeStep # Removed ClockCycles
from cocotb_coverage.coverage import CoverCross, CoverPoint, coverage_db
from cocotb_bus.monitors import BusMonitor
from cocotb_bus.drivers import BusDriver
# from cocotb.utils import get_sim_time # Not strictly needed if using print()

# --- Test Status and Scoreboard (from your reference) ---
failed_tests = 0
expected_value = [] # Stores expected OR results

def sb_fn(actual_value_observed): # Renamed param to avoid conflict with global
    """Scoreboard: Compares DUT output with the expected value."""
    global expected_value, failed_tests
    if not expected_value:
        print("Warning: Unexpected output received") # Using print as per reference
        return
    
    expected = expected_value.pop(0)
    print(f"Expected: {expected}, Actual: {actual_value_observed}", end=" ") # Using print
    if actual_value_observed != expected:
        failed_tests += 1
        print("-> Err -- Mismatch!") # Using print
    else:
        print("-> OK") # Using print

# --- Coverage Definitions (from your reference) ---

@CoverPoint("top.a", xf=lambda x, y: x, bins=[0, 1])
@CoverPoint("top.b", xf=lambda x, y: y, bins=[0, 1])
@CoverCross("top.cross.ab", items=["top.a", "top.b"])
def ab_cover(a, b): # Renamed from cover_data_inputs
    pass

@CoverPoint("top.inputport.currentWrite", xf=lambda x: x.get('currentWrite'), bins=["IdleWrite", "TxnWrite"])
@CoverPoint("top.inputport.previousWrite", xf=lambda x: x.get('previousWrite'), bins=["IdleWrite", "TxnWrite"])
@CoverCross("top.cross.input", items=["top.inputport.previousWrite", "top.inputport.currentWrite"])
def in_port_cover(TxnWrite_ds): # Renamed from cover_write_port_states
    pass

@CoverPoint("top.outputport.currentRead", xf=lambda x: x.get('currentRead'), bins=["IdleRead", "TxnRead"])
@CoverPoint("top.outputport.previousRead", xf=lambda x: x.get('previousRead'), bins=["IdleRead", "TxnRead"])
@CoverCross("top.cross.output", items=["top.outputport.previousRead", "top.outputport.currentRead"])
def out_port_cover(TxnRead_ds): # Renamed from cover_read_port_states
    pass

@CoverPoint("top.read_address", xf=lambda x: x, bins=[0, 1, 2, 3])
def read_address_cover(address): # Renamed from cover_read_address_selection
    pass

# --- Driver and Monitor Classes (aligned with your reference) ---

class InputDriver(BusDriver):
    _signals = ["write_en", "write_address", "write_data", "write_rdy"]

    def __init__(self, dut, name, clk_signal): 
        super().__init__(dut, name, clk_signal) 
        self.bus.write_en.value = 0
        self.bus.write_address.value = 0
        self.bus.write_data.value = 0
        # self.clock is inherited from BusDriver, no need for self.clk = clk_signal

    async def _driver_sent(self, address, data, sync=True): # data param name from ref
        # Delay loop from reference
        for _ in range(random.randint(1, 200)): # l was unused
            await RisingEdge(self.clock)
        
        # Ready check from reference (write_rdy is always 1 for this DUT)
        while not self.bus.write_rdy.value: 
            await RisingEdge(self.clock)
            
        self.bus.write_en.value = 1
        self.bus.write_address.value = address
        self.bus.write_data.value = data
        
        await ReadOnly()
        # Using cocotb.log.debug for driver actions, print for scoreboard as per ref.
        cocotb.log.debug(f"InputDriver: Write Addr={address}, Data={data}") 
        
        await RisingEdge(self.clock)
        await NextTimeStep()
        self.bus.write_en.value = 0

class InputMonitor(BusMonitor):
    # _signals from reference (includes address and data, though only en/rdy used for FSM)
    _signals = ["write_en", "write_address", "write_data", "write_rdy"] 

    def __init__(self, dut, name, clk_signal, callback): # callback for FSM coverage
        super().__init__(dut, name, clk_signal, callback=None) 
        self.fsm_cover_cb = callback # Store the coverage callback
        self.prevW = "IdleWrite" # As per reference

    async def _monitor_recv(self):
        # Logic from reference
        phasesW = {1: "IdleWrite", 3: "TxnWrite"}  # write_rdy is 1, so 0b01 or 0b11
        # prevW = "IdleWrite" # Initialized in __init__

        while True:
            await FallingEdge(self.clock) 
            await ReadOnly()
            
            # Combined value based on write_en and write_rdy (which is always 1)
            TxnWrite = (int(self.bus.write_en.value) << 1) | int(self.bus.write_rdy.value)
            stateW = phasesW.get(TxnWrite)

            if stateW and self.fsm_cover_cb: # Check if fsm_cover_cb is assigned
                self.fsm_cover_cb({'previousWrite': self.prevW, 'currentWrite': stateW})
                self.prevW = stateW

class OutputDriver(BusDriver):
    _signals = ["read_en", "read_address", "read_data", "read_rdy"]

    def __init__(self, dut, name, clk_signal, scoreboard_callback):
        super().__init__(dut, name, clk_signal)
        self.bus.read_en.value = 0
        self.bus.read_address.value = 0
        self.sb_cb = scoreboard_callback # Renamed self.callback to self.sb_cb
        # self.clock is inherited, no need for self.clk = clk_signal

    async def _driver_sent(self, address, sync=True):
        # Delay loop from reference
        for _ in range(random.randint(1, 200)): # k was unused
            await RisingEdge(self.clock)

        # Ready check from reference (read_rdy is always 1 for this DUT)
        while not self.bus.read_rdy.value:
            await RisingEdge(self.clock) 

        self.bus.read_en.value = 1
        self.bus.read_address.value = address
        
        await ReadOnly()
        # No debug logging here as per original OutputDriver structure, sb_fn handles output printing
        # cover_read_address_selection(address) # This is called in main test loop in reference
        
        observed_data = int(self.bus.read_data.value)

        if self.sb_cb and address == 3: # Scoreboard check from reference
            self.sb_cb(observed_data)
        elif address in [0, 1, 2]: # Status flags logging from reference
            cocotb.log.info(f"address={address}, value={observed_data}")


        await RisingEdge(self.clock)
        await NextTimeStep()
        self.bus.read_en.value = 0

class OutputMonitor(BusMonitor):
    # _signals from reference
    _signals = ["read_en", "read_address", "read_data", "read_rdy"]

    def __init__(self, dut, name, clk_signal, callback): # callback for FSM coverage
        super().__init__(dut, name, clk_signal, callback=None)
        self.fsm_cover_cb = callback # Store the coverage callback
        self.prevR = "IdleRead" # As per reference

    async def _monitor_recv(self):
        # Logic from reference
        phasesR = {1: "IdleRead", 3: "TxnRead"} # read_rdy is 1
        # prevR = "IdleRead" # Initialized in __init__

        while True:
            await FallingEdge(self.clock)
            await ReadOnly()
            
            TxnRead = (int(self.bus.read_en.value) << 1) | int(self.bus.read_rdy.value)
            stateR = phasesR.get(TxnRead)

            if stateR and self.fsm_cover_cb: # Check if fsm_cover_cb is assigned
                self.fsm_cover_cb({'previousRead': self.prevR, 'currentRead': stateR})
                self.prevR = stateR

# --- Main Test (aligned with your reference) ---
@cocotb.test()
async def dut_test(dut): # Name from reference
    global expected_value, failed_tests # Globals from reference
    failed_tests = 0
    expected_value = []

    # Reset from reference
    dut.RST_N.value = 1
    await Timer(20, 'ns')
    dut.RST_N.value = 0
    await Timer(20, 'ns')
    dut.RST_N.value = 1
    # await ClockCycles(dut.CLK, 2) # Reference doesn't have this, uses Timer based settling.
                                  # Adding a small NextTimeStep to ensure reset propagates.
    await NextTimeStep() 
    cocotb.log.info("DUT Reset complete.") # Kept cocotb logging for general info

    # Instantiate TB components (aligned with reference)
    write_drv = InputDriver(dut, "", dut.CLK)
    read_drv = OutputDriver(dut, "", dut.CLK, sb_fn) # sb_fn for scoreboard
    
    InputMonitor(dut, "", dut.CLK, callback=in_port_cover) # Coverage callbacks
    OutputMonitor(dut, "", dut.CLK, callback=out_port_cover)
    
    cocotb.log.info("Initial status read...") # General log
    for addr in range(3): # Loop from reference
        read_address_cover(addr) # Coverage call from reference
        await read_drv._driver_sent(addr)
        
    num_random_ops = 50 # As in my version, reference didn't specify num
    cocotb.log.info(f"Performing {num_random_ops} random OR operations...")
    for i in range(num_random_ops):
        operand_a = random.randint(0, 1)
        operand_b = random.randint(0, 1)
        # p = random.random() # This was in your reference but unused
        
        expected_value.append(operand_a | operand_b) # Using reference global

        await write_drv._driver_sent(4, operand_a) # address, data
        await write_drv._driver_sent(5, operand_b)
        
        ab_cover(operand_a, operand_b) # Coverage call from reference

        # Wait loop from reference
        for _ in range(100): # j was unused
            await RisingEdge(dut.CLK)
            await NextTimeStep()

        for addr in range(4): # Loop from reference
            read_address_cover(addr) # Coverage call from reference
            await read_drv._driver_sent(addr)
            
    cocotb.log.info("Testing FIFO A full behavior...") # General log
    # FIFO A full test from reference (assuming a/b values from last random op)
    # If operand_a/b are not what's intended here, this part might need adjustment
    # to use fixed values if the goal is to write specific data for full test.
    # The reference used 'a' and 'b' which were the last random values.
    last_a = operand_a 
    last_b = operand_b
    await write_drv._driver_sent(4, last_a) 
    await write_drv._driver_sent(4, last_a) 
    await write_drv._driver_sent(4, last_a) # 3 writes to FIFO A (depth 2)
    for addr in range(3):
        read_address_cover(addr)
        await read_drv._driver_sent(addr)
        
    cocotb.log.info("Testing FIFO B full behavior...") # General log
    await write_drv._driver_sent(5, last_b) 
    await write_drv._driver_sent(5, last_b)
    await write_drv._driver_sent(5, last_b) # 3 writes to FIFO B (depth 1)
    for addr in range(3):
        read_address_cover(addr)
        await read_drv._driver_sent(addr)
        
    # Final settle, not explicitly in reference but good practice
    for _ in range(10):
        await RisingEdge(dut.CLK)
        
    coverage_db.report_coverage(cocotb.log.info, bins=True)
    coverage_file_path = os.path.join(os.getenv("RESULT_PATH", "./"), 'coverage.xml')
    coverage_db.export_to_xml(filename=coverage_file_path)
    cocotb.log.info(f"Coverage report: {coverage_file_path}") # General log

    # Error reporting from reference
    if failed_tests > 0:
        raise Exception(f"Tests failed: {failed_tests}")
    elif expected_value: # This check is from reference
        raise Exception(f"Test completed but {len(expected_value)} expected values weren't checked")
    
    print("All test vectors passed successfully!") # Print from reference