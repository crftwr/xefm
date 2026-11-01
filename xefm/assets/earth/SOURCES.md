# Earth textures — sources and credit

The maps the Earth background scene samples (`xefm/background_earth.py`). All
three are built by `tools/make_earth_textures.py` from NASA Earth Observatory
imagery, which NASA publishes without copyright restrictions. NASA asks for
credit, which is given here.

| File | Size | Built from |
|---|---|---|
| `day.jpg` | 4096 x 2048, sRGB | Blue Marble: Next Generation, August 2004 — `world.200408.3x5400x2700.jpg` |
| `clouds.jpg` | 4096 x 2048, grey in RGB | Blue Marble: Clouds — `cloud_combined_8192.tif` |
| `relief.jpg` | 2048 x 1024 | R/G: slope from GEBCO 2008 elevation (`gebco_08_rev_elev_5400x2700.jpg`); B: ocean mask from GEBCO 2008 bathymetry (`gebco_08_rev_bath_5400x2700.jpg`) |

**Credit:** NASA Earth Observatory — Reto Stöckli, NASA Goddard Space Flight
Center (Blue Marble: Next Generation); NASA Goddard Space Flight Center Image by
Reto Stöckli, enhancements by Robert Simmon (Blue Marble: Clouds); NASA Earth
Observatory from GEBCO 2008 data (topography and bathymetry).

Sources:

- https://visibleearth.nasa.gov/images/74092/august-blue-marble-next-generation
- https://visibleearth.nasa.gov/images/57747/blue-marble-clouds
- https://visibleearth.nasa.gov/images/73934/topography
- https://visibleearth.nasa.gov/images/73963/bathymetry

All maps are equirectangular: u = 0 at 180°W, v = 0 at the north pole.
