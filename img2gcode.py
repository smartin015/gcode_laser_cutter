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

    self.target_xys = (0,0,0)

    self.f = None

    self._reset_write_head()

  def pixel_value_to_laser_power(self, val):
    if (val > self.WHITE_THRESHOLD): # Off-white counts as white (saves adjust time. TODO: Remove adjust time from gcode firmware?)
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
    self.target_xys = (0,0,0)

  def _write_begin(self, outfile):
    self.f = open(outfile, "w")
    self.writeln("M05")
    self.writeln("G0 G90 G94 G17")
    self.writeln("G21")
    self.writeln("S0")
    self.writeln("M03")
    self.writeln("G54")
    self.writeln("G1 F%d" % feedrate)
    self.writeln("G0 X0 Y0")

  def _write_end(self): 
    self.writeln("S0")
    self.writeln("M05")
    self.writeln("G0 X0 Y0")
    self.f.close()

  def _write_xys(self, pos, s):
    self.writeln("G1X%.2fY%.2fS%d" % (pos[0], pos[1], s))

  def _gcode_write_line(self, start, end, pixels):
    # Write a line from start to end xy coordinates, evenly spacing out pixels
    # where pixels[0] occurs at start and pixels[-1] occurs at end.
    # A "pixel" is defined as the midpoint of the line segment where the laser has a specific value
    
    # Line optimization: if the entire line is white pixels, disregard
    if reduce(lambda x, y: x and y, map(lambda z: z > self.WHITE_THRESHOLD, pixels)):
      print "White line, skipping"
      return

    pixels = [self.pixel_value_to_laser_power(v) for v in pixels]

    start = (start[0] / float(self.dpmm), start[1] / float(self.dpmm))
    end = (end[0] / float(self.dpmm), end[1] / float(self.dpmm))

    DIST = math.sqrt((end[0]-start[0])**2 + (end[1]-start[1])**2)
    STEP_SIZE = DIST / (len(pixels) - 1) # Account for fencepost
    UNIT_VEC = ((end[0]-start[0]) / DIST, (end[1]-start[1]) / DIST)
    STEP_VEC = (UNIT_VEC[0] * STEP_SIZE, UNIT_VEC[1] * STEP_SIZE)
    
    # Left-shift by half-pixel so we burn across the pixel at the midpoint.
    curr = (start[0] - STEP_VEC[0]/2.0, start[1] - STEP_VEC[1]/2.0)
    self._write_xys(curr, 0) # Head to start with laser off
    for power in pixels:
      curr = (curr[0] + STEP_VEC[0], curr[1] + STEP_VEC[1])
      self._write_xys(curr, power)

    # Ensure we wrote the line correctly
    eps = 0.001
    print "Curr", curr, "End", end, "STEP_VEC", STEP_VEC
    assert(curr[0] - (end[0] + STEP_VEC[0] / 2.0) < eps)
    assert(curr[1] - (end[1] + STEP_VEC[1] / 2.0) < eps)

  def gcodify_image(self, infile, outfile):
    im = Image.open(infile)
    img_size = (self.work_size_mm[0] * self.dpmm, self.work_size_mm[1] * self.dpmm)
    im.thumbnail(img_size, Image.ANTIALIAS)
    grey_im = im.convert('L')
    img_size = grey_im.size
    print "Image size:", img_size

    self._reset_write_head()
    self._write_begin(outfile)
    self.gcodify_horizontal(grey_im)
    self.gcodify_vertical(grey_im)
    self.gcodify_diagonal_bltr(grey_im)
    self.gcodify_diagonal_tlbr(grey_im)
    self._write_end()

  def _laserpx(self, img, x, y):
    return img.getpixel((x, (img.size[1] - 1) - y))

  def gcodify_horizontal(self, img):
    for j in xrange(img.size[1]):
      left = (0, j)
      right = (img.size[0]-1, j)
      if j % 2 == 0:
        pixels = [self._laserpx(img, i, j) for i in xrange(img.size[0])]
        self._gcode_write_line(left, right, pixels)
      else:
        pixels = [self._laserpx(img, img.size[0] - 1 - i, j) for i in xrange(img.size[0])]
        self._gcode_write_line(right, left, pixels)


  def gcodify_vertical(self, img):
    for i in xrange(img.size[0]):
      bot = (i, 0)
      top = (i, img.size[1]-1)
      if i % 2 == 0:
        pixels = [self._laserpx(img, i, j) for j in xrange(img.size[1])]
        self._gcode_write_line(bot, top, pixels)
      else:
        pixels = [self._laserpx(img, i, img.size[1] - 1 - j) for j in xrange(img.size[1])]
        self._gcode_write_line(top, bot, pixels)

  def gcodify_diagonal_bltr(self, img):
    # Bottom left to top right
    (l, h) = img.size

    bl_xs = ([0] * (h - 1)) + range(0, l)
    bl_ys = range(h - 1, 0, -1) + [0] * l
    bls = zip(bl_xs, bl_ys)
    
    tr_xs = range(0, l) + ([l-1] * (h-1))
    tr_ys = [h-1]*(l-1) + range(h-1, -1, -1)
    trs = zip(tr_xs, tr_ys)

    for (i, (bl, tr)) in enumerate(zip(bls, trs)):
      num_pixels = tr[0]-bl[0]+1

      if i % 2 == 0:
        pixels = [self._laserpx(img, bl[0]+d, bl[1]+d) for d in xrange(0, num_pixels)]
        self._gcode_write_line(bl, tr, pixels)
      else:
        pixels = [self._laserpx(img, tr[0]-d, tr[1]-d) for d in xrange(0, num_pixels)]
        self._gcode_write_line(tr, bl, pixels)

  def gcodify_diagonal_tlbr(self, img):
    # Top left to bottom right
    (l, h) = img.size

    tl_xs = ([0] * (h - 1)) + range(0, l)
    tl_ys = range(0, h) + [h-1] * (l - 1)
    tls = zip(tl_xs, tl_ys)
    
    br_xs = range(0, l) + ([l-1] * (h-1))
    br_ys = ([0]*(l-1)) + range(0, h)
    brs = zip(br_xs, br_ys)

    for (i, (tl, br)) in enumerate(zip(tls, brs)):
      num_pixels = br[0]-tl[0]+1

      if i % 2 == 0:
        pixels = [self._laserpx(img, tl[0]+d, tl[1]-d) for d in xrange(0, num_pixels)]
        self._gcode_write_line(tl, br, pixels)
      else:
        pixels = [self._laserpx(img, br[0]-d, br[1]+d) for d in xrange(0, num_pixels)]
        self._gcode_write_line(br, tl, pixels)
    

if __name__ == "__main__":
  size = 8, 8 # 1 value is 1 mm (128mm ~= 5in)
  dpmm = 8
  power = 0.7
  feedrate = 400

  assert(size[0] % 2 == 0 and size[1] % 2 == 0)
  writer = GCodeWriter(size, dpmm, power, feedrate)
  writer.gcodify_image(sys.argv[1], sys.argv[2])
