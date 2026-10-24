// BeamBench toolchain spike bracket.
// Units: millimetres. Single part, simple functional bracket.
bracket_width = 40;
bracket_depth = 25;
bracket_height = 30;
wall = 4;
hole_d = 5;
hole_spacing = 20;

module bracket() {
  difference() {
    union() {
      cube([bracket_width, bracket_depth, wall]);
      translate([0, 0, 0]) cube([wall, bracket_depth, bracket_height]);
    }
    // mounting holes in base
    for (x = [(bracket_width-hole_spacing)/2, (bracket_width+hole_spacing)/2]) {
      translate([x, bracket_depth/2, -1])
        cylinder(h=wall+2, d=hole_d, $fn=32);
    }
  }
}

bracket();
