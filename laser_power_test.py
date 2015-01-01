from img2gcode import GCodeWriter
import serial
from time import sleep

m = serial.Serial("/dev/ttyUSB0", 9600)
s = serial.Serial("/dev/ttyACM0", 115200)
sleep(2.0)

def gcode(val):
  print ">>", val
  s.write(val + "\n")
  #print s.readline()

def sense():
  m.write('a')
  val = m.readline()
  print "<<", val
  return int(val.strip())


gcode("S0")
gcode("M03")

results = []
for i in xrange(256):
  p = GCodeWriter.laser_power_linearized(i)
  gcode("S%d" % p)
  sleep(0.25)
  results.append(sense())

gcode("M05")
gcode("S0")

print "RESULTS:"
for r in results:
  print r

