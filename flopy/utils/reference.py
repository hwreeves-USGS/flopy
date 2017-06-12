"""
Module spatial referencing for flopy model objects

"""
import sys
import os
import numpy as np
import warnings


class SpatialReference(object):
    """
    a class to locate a structured model grid in x-y space

    Parameters
    ----------

    delr : numpy ndarray
        the model discretization delr vector
        (An array of spacings along a row)
    delc : numpy ndarray
        the model discretization delc vector
        (An array of spacings along a column)
    lenuni : int
        the length units flag from the discretization package
        (default 2)
    xul : float
        the x coordinate of the upper left corner of the grid
        Enter either xul and yul or xll and yll.
    yul : float
        the y coordinate of the upper left corner of the grid
        Enter either xul and yul or xll and yll.
    xll : float
        the x coordinate of the lower left corner of the grid
        Enter either xul and yul or xll and yll.
    yll : float
        the y coordinate of the lower left corner of the grid
        Enter either xul and yul or xll and yll.
    rotation : float
        the counter-clockwise rotation (in degrees) of the grid

    proj4_str: str
        a PROJ4 string that identifies the grid in space. warning: case
        sensitive!

    units : string
        Units for the grid.  Must be either feet or meters

    epsg : int
        EPSG code that identifies the grid in space. Can be used in lieu of
        proj4. PROJ4 attribute will auto-populate if there is an internet
        connection(via get_proj4 method).
        See https://www.epsg-registry.org/ or spatialreference.org

    length_multiplier : float
        multiplier to convert model units to spatial reference units.
        delr and delc above will be multiplied by this value. (default=1.)

    Attributes
    ----------
    xedge : ndarray
        array of column edges

    yedge : ndarray
        array of row edges

    xgrid : ndarray
        numpy meshgrid of xedges

    ygrid : ndarray
        numpy meshgrid of yedges

    xcenter : ndarray
        array of column centers

    ycenter : ndarray
        array of row centers

    xcentergrid : ndarray
        numpy meshgrid of column centers

    ycentergrid : ndarray
        numpy meshgrid of row centers

    vertices : 1D array
        1D array of cell vertices for whole grid in C-style (row-major) order
        (same as np.ravel())


    Notes
    -----

    xul and yul can be explicitly (re)set after SpatialReference
    instantiation, but only before any of the other attributes and methods are
    accessed
        
    """

    xul, yul = None, None
    xll, yll = None, None
    rotation = 0.
    length_multiplier = 1.
    origin_loc = 'ul'  # or ll

    defaults = {"xul": None, "yul": None, "rotation": 0.,
                "proj4_str": None,
                "units": None, "lenuni": 2, "length_multiplier": None}

    lenuni_values = {'undefined': 0,
                     'feet': 1,
                     'meters': 2,
                     'centimeters': 3}
    lenuni_text = {v:k for k, v in lenuni_values.items()}

    def __init__(self, delr=np.array([]), delc=np.array([]), lenuni=2,
                 xul=None, yul=None, xll=None, yll=None, rotation=0.0,
                 proj4_str=None, epsg=None, units=None,
                 length_multiplier=None):

        for delrc in [delr, delc]:
            if isinstance(delrc, float) or isinstance(delrc, int):
                msg = ('delr and delcs must be an array or sequences equal in '
                       'length to the number of rows/columns.')
                raise TypeError(msg)

        self.delc = np.atleast_1d(np.array(delc))  # * length_multiplier
        self.delr = np.atleast_1d(np.array(delr))  # * length_multiplier

        if self.delr.sum() == 0 or self.delc.sum() == 0:
            if xll is None or yll is None:
                msg = ('Warning: no grid spacing or lower-left corner '
                       'supplied. Setting the offset with xul, yul requires '
                       'arguments for delr and delc. Origin will be set to '
                       'zero.')
                print(msg)
                xll, yll = 0, 0
                xul, yul = None, None

        self.lenuni = lenuni
        self._proj4_str = proj4_str

        self._epsg = epsg
        if epsg is not None:
            self._proj4_str = getproj4(self._epsg)


        self.supported_units = ["feet", "meters"]
        self._units = units
        self._length_multiplier = length_multiplier
        self._reset()
        self.set_spatialreference(xul, yul, xll, yll, rotation)

    @property
    def proj4_str(self):
        if self._proj4_str is not None and \
                        "epsg" in self._proj4_str.lower():
            if "init" not in self._proj4_str.lower():
                proj4_str = "+init=" + self._proj4_str
            else:
                proj4_str = self._proj4_str
            # set the epsg if proj4 specifies it
            tmp = [i for i in self._proj4_str.split() if 'epsg' in i.lower()]
            self._epsg = int(tmp[0].split(':')[1])
        else:
            proj4_str = self._proj4_str
        return proj4_str

    @property
    def epsg(self):
        #don't reset the proj4 string here
        #because proj4 attribute may already be populated
        #(with more details than getproj4 would return)
        #instead reset proj4 when epsg is set
        #(on init or setattr)
        return self._epsg

    def _parse_units_from_proj4(self):
        units = None
        try:
            # need this because preserve_units doesn't seem to be
            # working for complex proj4 strings.  So if an
            # epsg code was passed, we have no choice, but if a
            # proj4 string was passed, we can just parse it
            if "EPSG" in self.proj4_str.upper():
                import pyproj

                crs = pyproj.Proj(self.proj4_str,
                                  preseve_units=True,
                                  errcheck=True)
                proj_str = crs.srs
            else:
                proj_str = self.proj4_str
            # http://proj4.org/parameters.html#units
            # from proj4 source code
            # "us-ft", "0.304800609601219", "U.S. Surveyor's Foot",
            # "ft", "0.3048", "International Foot",
            if "units=m" in proj_str:
                units = "meters"
            elif "units=ft" in proj_str or \
                            "units=us-ft" in proj_str or \
                            "to_meters:0.3048" in proj_str:
                units = "feet"
            return units
        except:
            pass

    @property
    def units(self):
        if self._units is not None:
            units = self._units.lower()
        else:
            units = self._parse_units_from_proj4()
        if units is None:
            #print("warning: assuming SpatialReference units are meters")
            units = 'meters'
        assert units in self.supported_units
        return units

    @property
    def length_multiplier(self):
        """Attempt to identify multiplier for converting from
        model units to sr units, defaulting to 1."""
        lm = None
        if self._length_multiplier is not None:
            lm = self._length_multiplier
        else:
            if self.model_length_units == 'feet':
                if self.units == 'meters':
                    lm = 0.3048
                elif self.units == 'feet':
                    lm = 1.
            elif self.model_length_units == 'meters':
                if self.units == 'feet':
                    lm = 1/.3048
                elif self.units == 'meters':
                    lm = 1.
            elif self.model_length_units == 'centimeters':
                if self.units == 'meters':
                    lm = 1/100.
                elif self.units == 'feet':
                    lm = 1/30.48
            else: # model units unspecified; default to 1
                lm = 1.
        return lm

    @property
    def model_length_units(self):
        return self.lenuni_text[self.lenuni]

    @property
    def bounds(self):
        """Return bounding box in shapely order."""
        xmin, xmax, ymin, ymax = self.get_extent()
        return xmin, ymin, xmax, ymax

    @staticmethod
    def load(namefile=None, reffile='usgs.model.reference'):
        """Attempts to load spatial reference information from
        the following files (in order):
        1) usgs.model.reference
        2) NAM file (header comment)
        3) SpatialReference.default dictionary
        """
        reffile = os.path.join(os.path.split(namefile)[0], reffile)
        d = SpatialReference.read_usgs_model_reference_file(reffile)
        if d is not None:
            return d
        d = SpatialReference.attribs_from_namfile_header(namefile)
        if d is not None:
            return d
        else:
            return SpatialReference.defaults

    @staticmethod
    def attribs_from_namfile_header(namefile):
        # check for reference info in the nam file header
        d = SpatialReference.defaults.copy()
        if namefile is None:
            return None
        header = []
        with open(namefile, 'r') as f:
            for line in f:
                if not line.startswith('#'):
                    break
                header.extend(line.strip().replace('#', '').split(';'))

        for item in header:
            if "xul" in item.lower():
                try:
                    d['xul'] = float(item.split(':')[1])
                except:
                    pass
            elif "yul" in item.lower():
                try:
                    d['yul'] = float(item.split(':')[1])
                except:
                    pass
            elif "rotation" in item.lower():
                try:
                    d['rotation'] = float(item.split(':')[1])
                    if d['rotation'] != 0.0:
                        msg = ('rotation arg has recently changed. It was '
                               'previously treated as positive clockwise. It '
                               'now is positive counterclockwise.')
                        warnings.warn(msg)
                except:
                    pass
            elif "proj4_str" in item.lower():
                try:
                    d['proj4_str'] = ':'.join(item.split(':')[1:]).strip()
                except:
                    pass
            elif "start" in item.lower():
                try:
                    d['start_datetime'] = item.split(':')[1].strip()
                except:
                    pass
            # spatial reference length units
            elif "units" in item.lower():
                d['units'] = item.split(':')[1].strip()
            # model length units
            elif "lenuni" in item.lower():
                d['lenuni'] = int(item.split(':')[1].strip())
            # multiplier for converting from model length units to sr length units
            elif "length_multiplier" in item.lower():
                d['length_multiplier'] = float(item.split(':')[1].strip())
        return d

    @staticmethod
    def read_usgs_model_reference_file(reffile='usgs.model.reference'):
        # read spatial reference info from the usgs.model.reference file
        # https://water.usgs.gov/ogw/policy/gw-model/modelers-setup.html
        d = SpatialReference.defaults.copy()
        d.pop('proj4_str') # discard default to avoid confusion with epsg code if entered
        if os.path.exists(reffile):
            with open(reffile) as input:
                for line in input:
                    if line.strip()[0] != '#':
                        info = line.strip().split('#')[0].split()
                        if len(info) > 1:
                            d[info[0].lower()] = ' '.join(info[1:])
            d['xul'] = float(d['xul'])
            d['yul'] = float(d['yul'])
            d['rotation'] = float(d['rotation'])

            # convert the model.reference text to a lenuni value
            # (these are the model length units)
            if 'length_units' in d.keys():
                d['lenuni'] = SpatialReference.lenuni_values[d['length_units']]

            if 'start_date' in d.keys():
                start_datetime = d.pop('start_date')
                if 'start_time' in d.keys():
                    start_datetime += ' {}'.format(d.pop('start_time'))
                d['start_datetime'] = start_datetime
            if 'epsg' in d.keys():
                try:
                    d['epsg'] = int(d['epsg'])
                except Exception as e:
                    raise Exception(
                        "error reading epsg code from file:\n" + str(e))
            # this prioritizes epsg over proj4 if both are given
            # (otherwise 'proj4' entry will be dropped below)
            elif 'proj4' in d.keys():
                d['proj4_str'] = d['proj4']

            # drop any other items that aren't used in sr class
            d = {k:v for k, v in d.items() if k.lower() in SpatialReference.defaults.keys()
                 or k.lower() in {'epsg'}}
            return d
        else:
            return None

    def __setattr__(self, key, value):
        reset = True
        if key == "delr":
            super(SpatialReference, self). \
                __setattr__("delr", np.atleast_1d(np.array(value)))
        elif key == "delc":
            super(SpatialReference, self). \
                __setattr__("delc", np.atleast_1d(np.array(value)))
        elif key == "xul":
            super(SpatialReference, self). \
                __setattr__("xul", float(value))
        elif key == "yul":
            super(SpatialReference, self). \
                __setattr__("yul", float(value))
        elif key == "xll":
            super(SpatialReference, self). \
                __setattr__("xll", float(value))
        elif key == "yll":
            super(SpatialReference, self). \
                __setattr__("yll", float(value))
        elif key == "length_multiplier":
            super(SpatialReference, self). \
                __setattr__("length_multiplier", float(value))
            self.set_origin(xul=self.xul, yul=self.yul, xll=self.xll,
                            yll=self.yll)
        elif key == "rotation":
            if float(value) != 0.0:
                msg = ('rotation arg has recently changed. It was '
                       'previously treated as positive clockwise. It '
                       'now is positive counterclockwise.')
                warnings.warn(msg)
            super(SpatialReference, self). \
                __setattr__("rotation", float(value))
            self.set_origin(xul=self.xul, yul=self.yul, xll=self.xll,
                            yll=self.yll)
        elif key == "lenuni":
            super(SpatialReference, self). \
                __setattr__("lenuni", int(value))
        elif key == "units":
            value = value.lower()
            assert value in self.supported_units
            super(SpatialReference, self). \
                __setattr__("_units", value)
        elif key == "proj4_str":
            super(SpatialReference, self). \
                __setattr__("_proj4_str", value)
            # reset the units and epsg
            self._units = None
            self._epsg = None

        elif key == "epsg":
            super(SpatialReference, self). \
                __setattr__("_epsg", value)
            # reset the units and proj4
            self._units = None
            self._proj4_str = getproj4(self._epsg)
        else:
            super(SpatialReference, self).__setattr__(key, value)
            reset = False
        if reset:
            self._reset()

    def reset(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        return

    def _reset(self):
        self._xgrid = None
        self._ygrid = None
        self._ycentergrid = None
        self._xcentergrid = None
        self._vertices = None
        return

    @property
    def nrow(self):
        return self.delc.shape[0]

    @property
    def ncol(self):
        return self.delr.shape[0]

    def __eq__(self, other):
        if not isinstance(other, SpatialReference):
            return False
        if other.xul != self.xul:
            return False
        if other.yul != self.yul:
            return False
        if other.rotation != self.rotation:
            return False
        if other.proj4_str != self.proj4_str:
            return False
        return True

    @classmethod
    def from_namfile(cls, namefile):
        attribs = SpatialReference.attribs_from_namfile_header(namefile)
        try:
            attribs.pop("start_datetime")
        except:
            pass
        return SpatialReference(**attribs)

    @classmethod
    def from_gridspec(cls, gridspec_file, lenuni=0):
        f = open(gridspec_file, 'r')
        raw = f.readline().strip().split()
        nrow = int(raw[0])
        ncol = int(raw[1])
        raw = f.readline().strip().split()
        xul, yul, rot = float(raw[0]), float(raw[1]), float(raw[2])
        delr = []
        j = 0
        while j < ncol:
            raw = f.readline().strip().split()
            for r in raw:
                if '*' in r:
                    rraw = r.split('*')
                    for n in range(int(rraw[0])):
                        delr.append(float(rraw[1]))
                        j += 1
                else:
                    delr.append(float(r))
                    j += 1
        delc = []
        i = 0
        while i < nrow:
            raw = f.readline().strip().split()
            for r in raw:
                if '*' in r:
                    rraw = r.split('*')
                    for n in range(int(rraw[0])):
                        delc.append(float(rraw[1]))
                        i += 1
                else:
                    delc.append(float(r))
                    i += 1
        f.close()
        return cls(np.array(delr), np.array(delc),
                   lenuni, xul=xul, yul=yul, rotation=rot)

    @property
    def attribute_dict(self):
        return {"xul": self.xul, "yul": self.yul, "rotation": self.rotation,
                "proj4_str": self.proj4_str}

    def set_spatialreference(self, xul=None, yul=None, xll=None, yll=None,
                             rotation=0.0):
        """
            set spatial reference - can be called from model instance

        """
        if xul is not None and xll is not None:
            msg = ('Both xul and xll entered. Please enter either xul, yul or '
                   'xll, yll.')
            raise ValueError(msg)
        if yul is not None and yll is not None:
            msg = ('Both yul and yll entered. Please enter either xul, yul or '
                   'xll, yll.')
            raise ValueError(msg)
        if rotation != 0.0:
            msg = ('rotation arg has recently changed. It was '
                   'previously treated as positive clockwise. It '
                   'now is positive counterclockwise.')
            warnings.warn(msg)
        # set the origin priority based on the left corner specified
        # (the other left corner will be calculated).  If none are specified
        # then default to upper left
        if xul is None and yul is None and xll is None and yll is None:
            self.origin_loc = 'ul'
            xul = 0.
            yul = self.delc.sum()
        elif xll is not None:
            self.origin_loc = 'll'
        else:
            self.origin_loc = 'ul'

        self.rotation = rotation
        self.set_origin(xul, yul, xll, yll)
        return

    def __repr__(self):
        s = "xul:{0:<.10G}; yul:{1:<.10G}; rotation:{2:<G}; ". \
            format(self.xul, self.yul, self.rotation)
        s += "proj4_str:{0}; ".format(self.proj4_str)
        s += "units:{0}; ".format(self.units)
        s += "lenuni:{0}; ".format(self.lenuni)
        s += "length_multiplier:{}".format(self.length_multiplier)
        return s

    def set_origin(self, xul=None, yul=None, xll=None, yll=None):
        if self.origin_loc == 'll':
            # calculate coords for upper left corner
            self.xll = xll if xll is not None else 0.
            self.yll = yll if yll is not None else 0.
            self.xul = self.xll + (np.sin(self.theta) * self.yedge[0] *
                                   self.length_multiplier)
            self.yul = self.yll + (np.cos(self.theta) * self.yedge[0] *
                                   self.length_multiplier)

        if self.origin_loc == 'ul':
            # calculate coords for lower left corner
            self.xul = xul if xul is not None else 0.
            self.yul = yul if yul is not None else 0.
            self.xll = self.xul - (np.sin(self.theta) * self.yedge[0] *
                                   self.length_multiplier)
            self.yll = self.yul - (np.cos(self.theta) * self.yedge[0] *
                                   self.length_multiplier)
        self._reset()
        return

    @property
    def theta(self):
        return -self.rotation * np.pi / 180.

    @property
    def xedge(self):
        return self.get_xedge_array()

    @property
    def yedge(self):
        return self.get_yedge_array()

    @property
    def xgrid(self):
        if self._xgrid is None:
            self._set_xygrid()
        return self._xgrid

    @property
    def ygrid(self):
        if self._ygrid is None:
            self._set_xygrid()
        return self._ygrid

    @property
    def xcenter(self):
        return self.get_xcenter_array()

    @property
    def ycenter(self):
        return self.get_ycenter_array()

    @property
    def ycentergrid(self):
        if self._ycentergrid is None:
            self._set_xycentergrid()
        return self._ycentergrid

    @property
    def xcentergrid(self):
        if self._xcentergrid is None:
            self._set_xycentergrid()
        return self._xcentergrid

    def _set_xycentergrid(self):
        self._xcentergrid, self._ycentergrid = np.meshgrid(self.xcenter,
                                                           self.ycenter)
        self._xcentergrid, self._ycentergrid = self.transform(
            self._xcentergrid,
            self._ycentergrid)

    def _set_xygrid(self):
        self._xgrid, self._ygrid = np.meshgrid(self.xedge, self.yedge)
        self._xgrid, self._ygrid = self.transform(self._xgrid, self._ygrid)

    @staticmethod
    def rotate(x, y, theta, xorigin=0., yorigin=0.):
        """
        Given x and y array-like values calculate the rotation about an
        arbitrary origin and then return the rotated coordinates.  theta is in
        degrees.

        """
        # jwhite changed on Oct 11 2016 - rotation is now positive CCW
        # theta = -theta * np.pi / 180.
        theta = theta * np.pi / 180.

        xrot = xorigin + np.cos(theta) * (x - xorigin) - np.sin(theta) * \
                                                         (y - yorigin)
        yrot = yorigin + np.sin(theta) * (x - xorigin) + np.cos(theta) * \
                                                         (y - yorigin)
        return xrot, yrot

    def transform(self, x, y):
        """
        Given x and y array-like values, apply rotation, scale and offset,
        to convert them from model coordinates to real-world coordinates.
        """
        x, y = x.copy(), y.copy()
        # reset origin in case attributes were modified
        self.set_origin(xul=self.xul, yul=self.yul, xll=self.xll, yll=self.yll)
        x *= self.length_multiplier
        y *= self.length_multiplier
        x += self.xll
        y += self.yll
        x, y = SpatialReference.rotate(x, y, theta=self.rotation,
                                       xorigin=self.xll, yorigin=self.yll)
        return x, y

    def get_extent(self):
        """
        Get the extent of the rotated and offset grid

        Return (xmin, xmax, ymin, ymax)

        """
        x0 = self.xedge[0]
        x1 = self.xedge[-1]
        y0 = self.yedge[0]
        y1 = self.yedge[-1]

        # upper left point
        x0r, y0r = self.transform(x0, y0)

        # upper right point
        x1r, y1r = self.transform(x1, y0)

        # lower right point
        x2r, y2r = self.transform(x1, y1)

        # lower left point
        x3r, y3r = self.transform(x0, y1)

        xmin = min(x0r, x1r, x2r, x3r)
        xmax = max(x0r, x1r, x2r, x3r)
        ymin = min(y0r, y1r, y2r, y3r)
        ymax = max(y0r, y1r, y2r, y3r)

        return (xmin, xmax, ymin, ymax)

    def get_grid_lines(self):
        """
            Get the grid lines as a list

        """
        xmin = self.xedge[0]
        xmax = self.xedge[-1]
        ymin = self.yedge[-1]
        ymax = self.yedge[0]
        lines = []
        # Vertical lines
        for j in range(self.ncol + 1):
            x0 = self.xedge[j]
            x1 = x0
            y0 = ymin
            y1 = ymax
            x0r, y0r = self.transform(x0, y0)
            x1r, y1r = self.transform(x1, y1)
            lines.append([(x0r, y0r), (x1r, y1r)])

        # horizontal lines
        for i in range(self.nrow + 1):
            x0 = xmin
            x1 = xmax
            y0 = self.yedge[i]
            y1 = y0
            x0r, y0r = self.transform(x0, y0)
            x1r, y1r = self.transform(x1, y1)
            lines.append([(x0r, y0r), (x1r, y1r)])
        return lines

    def get_grid_line_collection(self, **kwargs):
        """
        Get a LineCollection of the grid

        """
        from matplotlib.collections import LineCollection

        lc = LineCollection(self.get_grid_lines(), **kwargs)
        return lc

    def get_xcenter_array(self):
        """
        Return a numpy one-dimensional float array that has the cell center x
        coordinate for every column in the grid in model space - not offset or rotated.

        """
        x = np.add.accumulate(self.delr) - 0.5 * self.delr
        return x

    def get_ycenter_array(self):
        """
        Return a numpy one-dimensional float array that has the cell center x
        coordinate for every row in the grid in model space - not offset of rotated.

        """
        Ly = np.add.reduce(self.delc)
        y = Ly - (np.add.accumulate(self.delc) - 0.5 *
                  self.delc)
        return y

    def get_xedge_array(self):
        """
        Return a numpy one-dimensional float array that has the cell edge x
        coordinates for every column in the grid in model space - not offset
        or rotated.  Array is of size (ncol + 1)

        """
        xedge = np.concatenate(([0.], np.add.accumulate(self.delr)))
        return xedge

    def get_yedge_array(self):
        """
        Return a numpy one-dimensional float array that has the cell edge y
        coordinates for every row in the grid in model space - not offset or
        rotated. Array is of size (nrow + 1)

        """
        length_y = np.add.reduce(self.delc)
        yedge = np.concatenate(([length_y], length_y -
                                np.add.accumulate(self.delc)))
        return yedge

    def write_gridSpec(self, filename):
        """ write a PEST-style grid specification file
        """
        f = open(filename, 'w')
        f.write(
            "{0:10d} {1:10d}\n".format(self.delc.shape[0], self.delr.shape[0]))
        f.write("{0:15.6E} {1:15.6E} {2:15.6E}\n".format(self.xul, self.yul,
                                                         self.rotation))

        for r in self.delr:
            f.write("{0:15.6E} ".format(r))
        f.write('\n')
        for c in self.delc:
            f.write("{0:15.6E} ".format(c))
        f.write('\n')
        return

    def write_shapefile(self, filename='grid.shp', epsg=None, prj=None):
        """Write a shapefile of the grid with just the row and column attributes"""
        from ..export.shapefile_utils import write_grid_shapefile2
        if epsg is None and prj is None:
            epsg = self.epsg
        write_grid_shapefile2(filename, self, array_dict={}, nan_val=-1.0e9,
                              epsg=epsg, prj=prj)

    def get_vertices(self, i, j):
        pts = []
        xgrid, ygrid = self.xgrid, self.ygrid
        pts.append([xgrid[i, j], ygrid[i, j]])
        pts.append([xgrid[i + 1, j], ygrid[i + 1, j]])
        pts.append([xgrid[i + 1, j + 1], ygrid[i + 1, j + 1]])
        pts.append([xgrid[i, j + 1], ygrid[i, j + 1]])
        pts.append([xgrid[i, j], ygrid[i, j]])
        return pts

    def get_rc(self, x, y):
        """Return the row and column of a point or sequence of points
        in real-world coordinates.

        Parameters
        ----------
        x : scalar or sequence of x coordinates
        y : scalar or sequence of y coordinates

        Returns
        -------
        r : row or sequence of rows (zero-based)
        c : column or sequence of columns (zero-based)
        """
        if np.isscalar(x):
            c = (np.abs(self.xcentergrid[0] - x)).argmin()
            r = (np.abs(self.ycentergrid[:, 0] - y)).argmin()
        else:
            xcp = np.array([self.xcentergrid[0]] * (len(x)))
            ycp = np.array([self.ycentergrid[:, 0]] * (len(x)))
            c = (np.abs(xcp.transpose() - x)).argmin(axis=0)
            r = (np.abs(ycp.transpose() - y)).argmin(axis=0)
        return r, c

    def get_grid_map_plotter(self):
        """
        Create a QuadMesh plotting object for this grid

        Returns
        -------
        quadmesh : matplotlib.collections.QuadMesh

        """
        from matplotlib.collections import QuadMesh
        verts = np.vstack((self.xgrid.flatten(), self.ygrid.flatten())).T
        qm = QuadMesh(self.ncol, self.nrow, verts)
        return qm

    def plot_array(self, a, ax=None):
        """
        Create a QuadMesh plot of the specified array using pcolormesh

        Parameters
        ----------
        a : np.ndarray

        Returns
        -------
        quadmesh : matplotlib.collections.QuadMesh

        """
        import matplotlib.pyplot as plt
        if ax is None:
            ax = plt.gca()
        qm = ax.pcolormesh(self.xgrid, self.ygrid, a)
        return qm

    def contour_array(self, ax, a, **kwargs):
        """
        Create a QuadMesh plot of the specified array using pcolormesh

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            ax to add the contours

        a : np.ndarray
            array to contour

        Returns
        -------
        contour_set : ContourSet

        """
        contour_set = ax.contour(self.xcentergrid, self.ycentergrid,
                                 a, **kwargs)
        return contour_set

    @property
    def vertices(self):
        """Returns a list of vertices for"""
        if self._vertices is None:
            self._set_vertices()
        return self._vertices

    def _set_vertices(self):
        """populate vertices for the whole grid"""
        jj, ii = np.meshgrid(range(self.ncol), range(self.nrow))
        jj, ii = jj.ravel(), ii.ravel()
        vrts = np.array(self.get_vertices(ii, jj)).transpose([2, 0, 1])
        self._vertices = [v.tolist() for v in vrts]  # conversion to lists

        """
        code above is 3x faster
        xgrid, ygrid = self.xgrid, self.ygrid
        ij = list(map(list, zip(xgrid[:-1, :-1].ravel(), ygrid[:-1, :-1].ravel())))
        i1j = map(list, zip(xgrid[1:, :-1].ravel(), ygrid[1:, :-1].ravel()))
        i1j1 = map(list, zip(xgrid[1:, 1:].ravel(), ygrid[1:, 1:].ravel()))
        ij1 = map(list, zip(xgrid[:-1, 1:].ravel(), ygrid[:-1, 1:].ravel()))
        self._vertices = np.array(map(list, zip(ij, i1j, i1j1, ij1, ij)))
        """

    def interpolate(self, a, xi, method='nearest'):
        """
        Use the griddata method to interpolate values from an array onto the
        points defined in xi.  For any values outside of the grid, use
        'nearest' to find a value for them.

        Parameters
        ----------
        a : numpy.ndarray
            array to interpolate from.  It must be of size nrow, ncol
        xi : numpy.ndarray
            array containing x and y point coordinates of size (npts, 2). xi
            also works with broadcasting so that if a is a 2d array, then
            xi can be passed in as (xgrid, ygrid).
        method : {'linear', 'nearest', 'cubic'}
            method to use for interpolation (default is 'nearest')

        Returns
        -------
        b : numpy.ndarray
            array of size (npts)

        """
        from scipy.interpolate import griddata

        # Create a 2d array of points for the grid centers
        points = np.empty((self.ncol * self.nrow, 2))
        points[:, 0] = self.xcentergrid.flatten()
        points[:, 1] = self.ycentergrid.flatten()

        # Use the griddata function to interpolate to the xi points
        b = griddata(points, a.flatten(), xi, method=method, fill_value=np.nan)

        # if method is linear or cubic, then replace nan's with a value
        # interpolated using nearest
        if method != 'nearest':
            bn = griddata(points, a.flatten(), xi, method='nearest')
            idx = np.isnan(b)
            b[idx] = bn[idx]

        return b


class SpatialReferenceUnstructured(SpatialReference):
    """
    a class to locate an unstructured model grid in x-y space

    Parameters
    ----------

    verts : ndarray
        2d array of x and y points.

    iverts : list of lists
        should be of len(ncells) with a list of vertex numbers for each cell

    ncpl : ndarray
        array containing the number of cells per layer.  ncpl.sum() must be
        equal to the total number of cells in the grid.

    layered : boolean
        flag to indicated that the grid is layered.  In this case, the vertices
        define the grid for single layer, and all layers use this same grid.
        In this case the ncpl value for each layer must equal len(iverts).
        If not layered, then verts and iverts are specified for all cells and
        all layers in the grid.  In this case, npcl.sum() must equal
        len(iverts).

    lenuni : int
        the length units flag from the discretization package

    proj4_str: str
        a PROJ4 string that identifies the grid in space. warning: case
        sensitive!

    units : string
        Units for the grid.  Must be either feet or meters

    epsg : int
        EPSG code that identifies the grid in space. Can be used in lieu of
        proj4. PROJ4 attribute will auto-populate if there is an internet
        connection(via get_proj4 method).
        See https://www.epsg-registry.org/ or spatialreference.org

    length_multiplier : float
        multiplier to convert model units to spatial reference units.
        delr and delc above will be multiplied by this value. (default=1.)

    Attributes
    ----------
    xcenter : ndarray
        array of x cell centers

    ycenter : ndarray
        array of y cell centers

    Notes
    -----

    """

    def __init__(self, xc, yc, verts, iverts, ncpl, layered=True, lenuni=1,
                 proj4_str="EPSG:4326", epsg=None, units=None,
                 length_multiplier=1.):
        self.xc = xc
        self.yc = yc
        self.verts = verts
        self.iverts = iverts
        self.ncpl = ncpl
        self.layered = layered
        self.lenuni = lenuni
        self._proj4_str = proj4_str
        self.epsg = epsg
        if epsg is not None:
            self._proj4_str = getproj4(epsg)
        self.supported_units = ["feet", "meters"]
        self._units = units
        self.length_multiplier = length_multiplier

        # set defaults
        self.xul = 0.
        self.yul = 0.
        self.rotation = 0.

        if self.layered:
            assert all([n == len(iverts) for n in ncpl])
            assert self.xc.shape[0] == self.ncpl[0]
            assert self.yc.shape[0] == self.ncpl[0]
        else:
            msg = ('Length of iverts must equal ncpl.sum '
                   '({} {})'.format(len(iverts), ncpl))
            assert len(iverts) == ncpl.sum(), msg
            assert self.xc.shape[0] == self.ncpl.sum()
            assert self.yc.shape[0] == self.ncpl.sum()
        return

    def write_shapefile(self, filename='grid.shp'):
        """
        Write shapefile of the grid

        Parameters
        ----------
        filename : string
            filename for shapefile

        Returns
        -------

        """
        raise NotImplementedError()
        return

    def write_gridSpec(self, filename):
        """
        Write a PEST-style grid specification file

        Parameters
        ----------
        filename : string
            filename for grid specification file

        Returns
        -------

        """
        raise NotImplementedError()
        return

    @classmethod
    def from_gridspec(cls, fname):
        """
        Create a new SpatialReferenceUnstructured grid from an PEST
        grid specification file

        Parameters
        ----------
        fname : string
            File name for grid specification file

        Returns
        -------
            sru : flopy.utils.reference.SpatialReferenceUnstructured

        """
        raise NotImplementedError()
        return

    @classmethod
    def from_argus_export(cls, fname, nlay=1):
        """
        Create a new SpatialReferenceUnstructured grid from an Argus One
        Trimesh file

        Parameters
        ----------
        fname : string
            File name

        nlay : int
            Number of layers to create

        Returns
        -------
            sru : flopy.utils.reference.SpatialReferenceUnstructured

        """
        from ..utils.geometry import get_polygon_centroid
        f = open(fname, 'r')
        line = f.readline()
        ll = line.split()
        ncells, nverts = ll[0:2]
        ncells = int(ncells)
        nverts = int(nverts)
        verts = np.empty((nverts, 2), dtype=np.float)
        xc = np.empty((ncells), dtype=np.float)
        yc = np.empty((ncells), dtype=np.float)

        # read the vertices
        f.readline()
        for ivert in range(nverts):
            line = f.readline()
            ll = line.split()
            c, iv, x, y = ll[0:4]
            verts[ivert, 0] = x
            verts[ivert, 1] = y

        # read the cell information and create iverts, xc, and yc
        iverts = []
        for icell in range(ncells):
            line = f.readline()
            ll = line.split()
            ivlist = []
            for ic in ll[2:5]:
                ivlist.append(int(ic) - 1)
            if ivlist[0] != ivlist[-1]:
                ivlist.append(ivlist[0])
            iverts.append(ivlist)
            xc[icell], yc[icell] = get_polygon_centroid(verts[ivlist, :])

        # close file and return spatial reference
        f.close()
        return cls(xc, yc, verts, iverts, np.array(nlay * [len(iverts)]))

    def __setattr__(self, key, value):
        super(SpatialReference, self).__setattr__(key, value)
        return

    def get_extent(self):
        """
        Get the extent of the grid

        Returns
        -------
        extent : tuple
            min and max grid coordinates

        """
        xmin = self.verts[:, 0].min()
        xmax = self.verts[:, 0].max()
        ymin = self.verts[:, 1].min()
        ymax = self.verts[:, 1].max()
        return (xmin, xmax, ymin, ymax)

    def get_xcenter_array(self):
        """
        Return a numpy one-dimensional float array that has the cell center x
        coordinate for every cell in the grid in model space - not offset or
        rotated.

        """
        return self.xc

    def get_ycenter_array(self):
        """
        Return a numpy one-dimensional float array that has the cell center x
        coordinate for every cell in the grid in model space - not offset of
        rotated.

        """
        return self.yc

    def plot_array(self, a, ax=None):
        """
        Create a QuadMesh plot of the specified array using patches

        Parameters
        ----------
        a : np.ndarray

        Returns
        -------
        quadmesh : matplotlib.collections.QuadMesh

        """
        from ..plot import plotutil
        if ax is None:
            ax = plt.gca()
        patch_collection = plotutil.plot_cvfd(self.verts, self.iverts, a=a,
                                              ax=ax)
        return patch_collection

    def get_grid_line_collection(self, **kwargs):
        """
        Get a patch collection of the grid

        """
        from ..plot import plotutil
        edgecolor = kwargs.pop('colors')
        pc = plotutil.cvfd_to_patch_collection(self.verts, self.iverts)
        pc.set(facecolor='none')
        pc.set(edgecolor=edgecolor)
        return pc

    def contour_array(self, ax, a, **kwargs):
        """
        Create a QuadMesh plot of the specified array using pcolormesh

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            ax to add the contours

        a : np.ndarray
            array to contour

        Returns
        -------
        contour_set : ContourSet

        """
        contour_set = ax.tricontour(self.xcenter, self.ycenter,
                                    a, **kwargs)
        return contour_set


class epsgRef:
    """Sets up a local database of projection file text referenced by epsg code.
    The database is located in the site packages folder in epsgref.py, which
    contains a dictionary, prj, of projection file text keyed by epsg value.
    """

    def __init__(self):
        sp = [f for f in sys.path if f.endswith('site-packages')][0]
        self.location = os.path.join(sp, 'epsgref.py')

    def _remove_pyc(self):
        try:  # get rid of pyc file
            os.remove(self.location + 'c')
        except:
            pass

    def make(self):
        if not os.path.exists(self.location):
            newfile = open(self.location, 'w')
            newfile.write('prj = {}\n')
            newfile.close()

    def reset(self, verbose=True):
        if os.path.exists(self.location):
            os.remove(self.location)
        self._remove_pyc()
        self.make()
        if verbose:
            print('Resetting {}'.format(self.location))

    def add(self, epsg, prj):
        """add an epsg code to epsgref.py"""
        with open(self.location, 'a') as epsgfile:
            epsgfile.write("prj[{:d}] = '{}'\n".format(epsg, prj))

    def remove(self, epsg):
        """removes an epsg entry from epsgref.py"""
        from epsgref import prj
        self.reset(verbose=False)
        if epsg in prj.keys():
            del prj[epsg]
        for epsg, prj in prj.items():
            self.add(epsg, prj)

    @staticmethod
    def show():
        import importlib
        import epsgref
        importlib.reload(epsgref)
        from epsgref import prj
        for k, v in prj.items():
            print('{}:\n{}\n'.format(k, v))


def getprj(epsg, addlocalreference=True, text='esriwkt'):
    """Gets projection file (.prj) text for given epsg code from spatialreference.org
    See: https://www.epsg-registry.org/

    Parameters
    ----------
    epsg : int
        epsg code for coordinate system
    addlocalreference : boolean
        adds the projection file text associated with epsg to a local
        database, epsgref.py, located in site-packages.

    Returns
    -------
    prj : str
        text for a projection (*.prj) file.
    """
    epsgfile = epsgRef()
    prj = None
    try:
        from epsgref import prj
        prj = prj.get(epsg)
    except:
        epsgfile.make()

    if prj is None:
        prj = get_spatialreference(epsg, text=text)
    if addlocalreference:
        epsgfile.add(epsg, prj)
    return prj


def get_spatialreference(epsg, text='esriwkt'):
    """Gets text for given epsg code and text format from spatialreference.org
    Fetches the reference text using the url:
        http://spatialreference.org/ref/epsg/<epsg code>/<text>/

    See: https://www.epsg-registry.org/

    Parameters
    ----------
    epsg : int
        epsg code for coordinate system
    text : str
        string added to url

    Returns
    -------
    url : str

    """
    from flopy.utils.flopy_io import get_url_text
    url = "http://spatialreference.org/ref/epsg/{0}/{1}/".format(epsg, text)
    text = get_url_text(url,
                        error_msg='No internet connection or epsg code {} '
                                  'not found on spatialreference.org.'.format(epsg))
    if text is None: # epsg code not listed on spatialreference.org may still work with pyproj
        return '+init=epsg:{}'.format(epsg)
    return text.replace("\n", "")


def getproj4(epsg):
    """Gets projection file (.prj) text for given epsg code from
    spatialreference.org. See: https://www.epsg-registry.org/

    Parameters
    ----------
    epsg : int
        epsg code for coordinate system

    Returns
    -------
    prj : str
        text for a projection (*.prj) file.
    """
    return get_spatialreference(epsg, text='proj4')