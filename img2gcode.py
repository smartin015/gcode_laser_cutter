import os, sys
import Image
import math

class GCodeWriter():
  WHITE_THRESHOLD = 252

  def __init__(self, work_size_mm, work_dpmm, power, feedrate):
    self.work_size_mm = work_size_mm
    self.dpmm = work_dpmm
    self.gain = power
    self.speed = feedrate

    self.xys = (0,0,0)
    self.target_xys = (0,0,0)

    self.f = None

    self._reset_write_head()

  def pixel_value_to_laser_power(self, val):
    if (val > self.WHITE_THRESHOLD): # Off-white counts as white (save adjust time. TODO: Remove adjust time from gcode firmware?)
      val = 0xFF

    intensity = 0xFF - val # We want to burn the dark areas
    assert(intensity >= 0)

    # Convert "laser power" to "laser voltage"
    return self.laser_power_linearized(intensity * self.gain)

  @classmethod
  def laser_power_linearized(self, intensity):
    # For the given power value 0-255, maps to an equivalent linear light intensity value
    # The laser was shown experimentally to have the following intensity function: 
    # 
    #   I = LOG_MAX*(1 - 1/EXP(LOG_BASE * P)) 
    #
    # Therefore, for a linear response, we'd want P = -(1/LOG_BASE) * ln(1 - I/LOG_MAX)
    # See: https://docs.google.com/spreadsheets/d/1vKFd61gmMn_OFdiX_dY1F3XLnK-UjQsrEAWl16_9TJ0/edit?usp=sharing

    # These MUST be floating point values
    LOG_MAX = 272.0
    LOG_BASE = 0.011

    power = int( -(1/LOG_BASE) * math.log(1 - (intensity/LOG_MAX)) )
    assert(power >= 0 and power <= 255)
    return power

  def writeln(self, val):
    self.f.write(val + "\n")

  def _reset_write_head(self):
    self.xys = (0,0,0)
    self.target_xys = (0,0,0)

  def _write_begin(self, outfile):
    self.f = open(outfile, "w")
    self.writeln("M05")
    self.writeln("S0")
    self.writeln("G0 G90 G94 G17")
    self.writeln("G21")
    self.writeln("M03")
    self.writeln("G54")
    self.writeln("G1 F%d" % feedrate)
    self.writeln("G0 X0 Y0")

  def _write_end(self): 
    self.writeln("S0")
    self.writeln("M05")
    self.writeln("G0 X0 Y0")
    self.f.close()

  def _gcode_write(self, pos, val):
    intensity = self.pixel_value_to_laser_power(val)
    xys = (pos[0] / float(self.dpmm), pos[1] / float(self.dpmm), intensity)

    if xys[2] == self.xys[2]: # same intensity
      # If we're at zero intensity, just ignore this command entirely.
      if xys[2] == 0:
        return

      # If we hit the end of the line, write command to there with current intensity
      # and bump up a row
      if self.xys[1] != xys[1]:
        self.writeln("G1X%.2fS%d" % (xys[0], xys[2]))
        self.writeln("")
        self.writeln("G1Y%.2f" % xys[1])
        self.xys = xys

      # Else we're progressing forward under the same power, so ignore

    else: # Different intensity
      # Write our progress up to this point using the *old* intensity
      # Then use this intensity for the next write.
      
      if xys[1] != self.xys[1]: # Different Y locations, use Y as well
        self.writeln("")
        self.writeln("G1X%.2fY%.2fS%d" % (xys[0], xys[1], self.xys[2]))
      else:
        self.writeln("G1X%.2fS%d" % (xys[0], self.xys[2]))
      self.xys = xys

  def gcodify_image(self, infile, outfile):
    im = Image.open(infile)
    img_size = (self.work_size_mm[0] * self.dpmm, self.work_size_mm[1] * self.dpmm)
    im.thumbnail(img_size, Image.ANTIALIAS)
    grey_im = im.convert('L')
    img_size = grey_im.size
    print "Image size:", img_size

    self._reset_write_head()
    self._write_begin(outfile)
    for j in xrange(img_size[1]):
      for i in xrange(img_size[0]):
        if j % 2 == 1:
          curr = (img_size[0] - i - 1, j) # Reverse on the way back
        else: 
          curr = (i,j)
        img_px = (curr[0], img_size[1] - curr[1] - 1)
        self._gcode_write(curr, grey_im.getpixel(img_px))

    self._write_end()

if __name__ == "__main__":
  size = 128, 128 # 1 value is 1 mm (128mm ~= 5in)
  dpmm = 2
  power = 0.9
  feedrate = 2500

  writer = GCodeWriter(size, dpmm, power, feedrate)
  writer.gcodify_image(sys.argv[1], sys.argv[2])
