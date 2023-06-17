print('Start script')

# Imports
import machine
import sys
import array
from array import array
from machine import Pin
import time

# Ability to write to registers
from machine import mem32

# Special raspberry pi imports
from rp2 import PIO, StateMachine, asm_pio

# Set the PICO clock frequency    
fclk_pi = 192000000 # I.e., 16 * 12 MHz (12 MHz is the input clock)
machine.freq(fclk_pi)

# See section 2.5 DMA, in the document rp2040-datasheet.pdf
DMA_BASE = 0x50000000

# Special abort register
DMA_ABORT = DMA_BASE + 0x444

DMA_ABORT_DAC = 0x3
DMA_ABORT_ADC = 0xc

# The ADC will listen to DREQ_PIO0_RX0 for the DMA transfers
DREQ_ADC = 0x4

# Channel "0" DMA for the ADC
CH0_READ_ADDR   = DMA_BASE + 0x000
CH0_WRITE_ADDR  = DMA_BASE + 0x004
CH0_TRANS_COUNT = DMA_BASE + 0x008
CH0_CTRL_TRIG   = DMA_BASE + 0x00c
CH0_CHAIN_TO    = 1

# Channel "1" DMA for the ADC
CH1_READ_ADDR   = DMA_BASE + 0x040
CH1_WRITE_ADDR  = DMA_BASE + 0x044
CH1_TRANS_COUNT = DMA_BASE + 0x048
CH1_CTRL_TRIG   = DMA_BASE + 0x04c
CH1_CHAIN_TO    = 0

# PIO0, base and TXF0
PIO0_BASE      = 0x50200000

# RX fifo for PIO ADC program - use PIO0, 0, i.e., StateMachine(0).active() will be True
PIO_BASE_RXF0 = PIO0_BASE + 0x20

print("Stop State machines")
for ii in [0, 1, 2, 3, 5, 6, 7]:
    try:
        StateMachine(ii).active(0)
        print(str(ii) + " done")
    except:
        print(str(ii) + " trouble")
    
# Important to remove old programs
pio_0 = PIO(0)
pio_0.remove_program()

pio_1 = PIO(1)
pio_1.remove_program()

# Define the asm_pio state machine - pushes bytes to the pins
# 10 output pins, will pull 10 bits at a time for DMA (i.e., use 30 bits of a 32 bit integer)
@asm_pio(in_shiftdir=PIO.SHIFT_LEFT, autopush=True, push_thresh=30, sideset_init=(PIO.OUT_LOW))
def sideset_test():
    # Use the "sideset" to generate the ADC10080 clock signal
    nop()          .side(1)    
    in_(pins, 10)  .side(0)
    
    nop()          .side(1)
    in_(pins, 10)  .side(0)
    
    nop()          .side(1)
    in_(pins, 10)  .side(0)    
    
# The bit pattern generator - this will generate a 16 bit test pattern    
@asm_pio(sideset_init=(PIO.OUT_LOW))
def waveform_out():
    nop()  .side(1)
    nop()  .side(0)
    nop()  .side(1)
    nop()  .side(1)
    nop()  .side(0)
    nop()  .side(1)
    nop()  .side(1)
    nop()  .side(1)
    nop()  .side(0)
    nop()  .side(1)
    nop()  .side(0)
    nop()  .side(0)
    nop()  .side(0)
    nop()  .side(1)
    nop()  .side(0)
    nop()  .side(0)
    
@micropython.viper
def check_register(addr):
    
    ret = mem32[addr]
    
    return ret    

# Quick stop of the DMA
@micropython.viper
def stopDMA_adc():
    
    mem32[DMA_ABORT] = DMA_ABORT_ADC
    
    while int(mem32[DMA_ABORT]) != 0:
        time.sleep_us(0.05)
    
    mem32[CH0_CTRL_TRIG] = mem32[CH0_CTRL_TRIG] & 0xFFFFFFFE
    mem32[CH1_CTRL_TRIG] = mem32[CH1_CTRL_TRIG] & 0xFFFFFFFE

# Arrays that will store the starting addresses of the waveforms
p_ar_adc = array('I', [0])

# Special procedure to stop the DMA - i.e., once DMA 0 reaches the end, halt the DMA
@micropython.viper
def stopDMA_chain():
    
    
    IRQ_QUIET = 0x1 #do not generate an interrupt
    TREQ_SEL = int(DREQ_ADC) #wait for which DREQ_ for the transfer request signal?
    CHAIN_TO = 0 # 0 for Stop when done, 1 for chain to channel 1   #start channel 1 when done
    RING_SEL = 0
    RING_SIZE = 0   #no wrapping
    INCR_WRITE = 1  #for write to array
    INCR_READ = 0   #for read from array
    DATA_SIZE = 2   #32-bit word transfer
    HIGH_PRIORITY = 1
    EN = 1
    CTRL0 = (IRQ_QUIET<<21) | (TREQ_SEL<<15) | (CHAIN_TO<<11) | (RING_SEL<<10) | (RING_SIZE<<9) | (INCR_WRITE<<5) | (INCR_READ<<4) | (DATA_SIZE<<2) | (HIGH_PRIORITY<<1) | (EN<<0)
    # Set control register
    mem32[CH0_CTRL_TRIG] = CTRL0


# Start the DMA - get data from the pins through the PIO, write to the array
@micropython.viper
def startDMA_adc(ar, nword):
    
    stopDMA_adc()
    
    # Start of the array
    p = ptr32(ar)
    
    # Channel 0 DMA
    # Read from PIO1 Rx FIFO
    mem32[CH0_READ_ADDR] = PIO_BASE_RXF0
    
    # Write the data to the array
    mem32[CH0_WRITE_ADDR] = p
    
    # Number of transfers
    mem32[CH0_TRANS_COUNT] = nword
    
    IRQ_QUIET = 0x1 #do not generate an interrupt
    TREQ_SEL = int(DREQ_ADC) #wait for which DREQ_ for the transfer request signal?
    CHAIN_TO = int(CH0_CHAIN_TO) # 0 for Stop when done, 1 for chain to channel 1   #start channel 1 when done
    RING_SEL = 0
    RING_SIZE = 0   #no wrapping
    INCR_WRITE = 1  #for write to array
    INCR_READ = 0   #for read from array
    DATA_SIZE = 2   #32-bit word transfer
    HIGH_PRIORITY = 1
    EN = 1
    CTRL0 = (IRQ_QUIET<<21) | (TREQ_SEL<<15) | (CHAIN_TO<<11) | (RING_SEL<<10) | (RING_SIZE<<9) | (INCR_WRITE<<5) | (INCR_READ<<4) | (DATA_SIZE<<2) | (HIGH_PRIORITY<<1) | (EN<<0)
    # Set control register
    mem32[CH0_CTRL_TRIG] = CTRL0

    # Put the start of the memory into p_ar
    p_ar_adc[0] = p
    mem32[CH1_READ_ADDR] = ptr(p_ar_adc)
    # Put the start of the waveform back to the CH0 read address
    mem32[CH1_WRITE_ADDR] = CH0_WRITE_ADDR
    mem32[CH1_TRANS_COUNT] = 1
    IRQ_QUIET = 0x1 #do not generate an interrupt
    TREQ_SEL = 0x3f #no pacing
    CHAIN_TO = int(CH1_CHAIN_TO)    #start channel 0 when done
    RING_SEL = 0
    RING_SIZE = 0   #no wrapping
    INCR_WRITE= 0  #single write
    INCR_READ = 0   #single read
    DATA_SIZE = 2   #32-bit word transfer
    HIGH_PRIORITY = 1
    EN = 1
    CTRL1 = (IRQ_QUIET<<21) | (TREQ_SEL<<15) | (CHAIN_TO<<11) | (RING_SEL<<10) | (RING_SIZE<<9) | (INCR_WRITE<<5) | (INCR_READ<<4) | (DATA_SIZE<<2) | (HIGH_PRIORITY<<1) | (EN<<0)
    
    # Set control registers
    mem32[CH1_CTRL_TRIG] = CTRL1
    
# Number of array elements for the ADC
NUM_ARRAY_ADC = 256
wave_ADC = array("I", [0] * (NUM_ARRAY_ADC))

# Use GP0 as the base pin for the input stream, use PIO0, i.e., state machine(0)
sm_test = StateMachine(0, sideset_test, freq = 192000000, sideset_base = Pin(11), in_base = Pin(0))

# The bit pattern generator
sm_wave = StateMachine(1, waveform_out, freq = 32000000, sideset_base = Pin(10))
sm_wave.active(1)

print("Start ADC")
sm_test.active(1)
startDMA_adc(wave_ADC, NUM_ARRAY_ADC)

# Let the startup conditions settle out
time.sleep(0.1)
stopDMA_chain()
