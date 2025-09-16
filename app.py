from shiny import App, ui, render, reactive
import geopandas as gpd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.io.img_tiles import OSM, GoogleTiles
from matplotlib_scalebar.scalebar import ScaleBar
from pathlib import Path
import tempfile
from geopy.geocoders import Nominatim
from shapely.geometry import box

from mpl_toolkits.axes_grid1.inset_locator import inset_axes
from cartopy.mpl.geoaxes import GeoAxes
import math
import datetime

# ---------------------- Basemap: Google Hybrid ----------------------
class GoogleHybrid(GoogleTiles):
    def _image_url(self, tile):
        x, y, z = tile
        return f"https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}"

# ---------------------- Globals ----------------------
last_error_message = ""

# Load world boundaries
geojson_path = Path(__file__).parent / "world-administrative-boundaries.geojson"
gdf = gpd.read_file(geojson_path)
gdf = gdf[gdf['name'].notna()]
country_list = sorted(gdf['name'].unique())

# Inset positions and regional extents
inset_positions = {
    "upper right": [0.7, 0.6, 0.2, 0.2],
    "bottom right": [0.7, 0.1, 0.2, 0.2]
}

regioncoord = {
    # Americas
    "South America": [-90, -30, -60, 15],
    "Central America": [-100, -60, 5, 25],
    "Caribbean": [-100, -60, 5, 25],
    "Northern America": [-170, -40, -30, 85],
    # Africa
    "Northern Africa": [-20, 55, 0, 38],
    "Western Africa": [-20, 40, 0, 38],
    "Middle Africa": [-20, 55, 0, 38],
    "Eastern Africa": [0, 55, -20, 30],
    "Southern Africa": [-20, 55, -35, 15],
    # Asia (macro regions)
    "Western Asia": [30, 85, 15, 55],
    "Central Asia": [30, 85, 15, 55],
    "Southern Asia": [60, 150, -10, 50],
    "Eastern Asia": [60, 150, -10, 50],
    "South-Eastern Asia": [60, 150, -10, 50],
    # Europe
    "Northern Europe": [-30, 60, 35, 75],
    "Eastern Europe": [10, 35, 35, 55],
    "Southern Europe": [-30, 60, 35, 75],
    "Western Europe": [-20, 20, 35, 70],
    # Oceania
    "Australia and New Zealand": [110, -120, -50, 25],
    "Melanesia": [110, -120, -50, 25],
    "Micronesia": [110, -120, -50, 25],
    "Polynesia": [110, -120, -50, 25],
    # Antarctica
    "Antarctica": [-180, 180, -90, -60]
}

def get_tiler(basemap_name):
    return GoogleHybrid() if basemap_name == "Google Hybrid" else OSM()

# ---------------------- Enforce minimum bbox ----------------------
def enforce_min_extent(minx, miny, maxx, maxy, min_deg=1.0):
    """
    Ensure the bounding box is at least min_deg × min_deg (degrees).
    Used for country mode to avoid over-zoomed, pixelated basemap.
    """
    width = maxx - minx
    height = maxy - miny
    if width < min_deg:
        pad = (min_deg - width) / 2.0
        minx -= pad; maxx += pad
    if height < min_deg:
        pad = (min_deg - height) / 2.0
        miny -= pad; maxy += pad
    # Clamp to valid lon/lat ranges
    minx = max(minx, -180.0); maxx = min(maxx, 180.0)
    miny = max(miny, -90.0);  maxy = min(maxy,  90.0)
    return minx, miny, maxx, maxy

# ---------------------- Choose tile zoom level ----------------------
def choose_tile_zoom(span_deg, is_city, hi_res=False):
    """
    Return a suitable tile zoom (integer 0–19) for the given span in degrees.
    hi_res=True bumps the level slightly for downloads.
    """
    if is_city:
        if span_deg <= 0.25:   z = 10
        elif span_deg <= 0.5:  z = 10
        elif span_deg <= 1.0:  z = 10
        elif span_deg <= 2.0:  z = 10
        else:                  z = 9
    else:
        if span_deg <= 1.0:    z = 10
        elif span_deg <= 2.0:  z = 10
        elif span_deg <= 5.0:  z = 8
        elif span_deg <= 10.0: z = 7
        elif span_deg <= 20.0: z = 6
        elif span_deg <= 40.0: z = 5
        else:                  z = 4

    if hi_res:
        z = min(z + 1, 19)  # nudge one level up for sharper downloads
    return z

# ---------------------- Map generation ----------------------
def create_map(
    selected_country,
    selected_city,
    inset_pos="upper right",
    title="Study Area Map",
    zoom_radius=1.0,
    basemap="OSM",
    dpi=150,
    out_path=None,
    hi_res=False
):
    """
    Build the map and save to file. Returns the output path.
    Set hi_res=True to request slightly higher tile zoom and 300+ dpi images.
    """
    global last_error_message
    try:
        city_geom, label_text, geometry = None, "", None
        region = "World"

        # --- City mode ---
        if selected_city:
            geolocator = Nominatim(user_agent="study-area-map-generator")
            location = geolocator.geocode(selected_city)
            if location is None:
                raise ValueError(f"City '{selected_city}' not found.")
            lon, lat = location.longitude, location.latitude
            box_geom = box(lon - zoom_radius, lat - zoom_radius, lon + zoom_radius, lat + zoom_radius)
            geometry = gpd.GeoSeries([box_geom], crs="EPSG:4326")
            label_text = selected_city
            city_geom = geometry

            for _, row in gdf.iterrows():
                if row.geometry.contains(box_geom.centroid):
                    region = row["region"]
                    break

        # --- Country mode ---
        elif selected_country:
            gdf_info = gdf[gdf['name'] == selected_country]
            if gdf_info.empty:
                raise ValueError(f"Country '{selected_country}' not found.")
            region = gdf_info.iloc[0]["region"]
            geometry = gdf_info["geometry"].simplify(0.001, preserve_topology=True)
            label_text = selected_country
        else:
            raise ValueError("Please select a country or city.")

        if geometry is None or geometry.empty:
            raise ValueError("No geometry to display.")

        minx, miny, maxx, maxy = geometry.total_bounds

        # Manual tweaks for antimeridian-spanning countries
        if selected_country == "United States of America":
            minx, maxx = -179, -50
        elif selected_country == "Russian Federation":
            minx, maxx = 20, 179
        elif selected_country == "New Zealand":
            minx, maxx = 165, 179

        # Enforce min 1°x1° only in country mode
        if not selected_city:
            minx, miny, maxx, maxy = enforce_min_extent(minx, miny, maxx, maxy, min_deg=1.0)

        # Span in degrees to choose tile zoom
        span_deg = max(maxx - minx, maxy - miny)
        tile_zoom = choose_tile_zoom(span_deg, is_city=bool(selected_city), hi_res=hi_res)

        # Region extent for inset
        region_extent = regioncoord.get(region, [-180, 180, -90, 90])
        if selected_country in ("Russian Federation", "Russia"):
            region_extent = [-30, 179, 10, 82]
        if selected_country == "New Zealand":
            region_extent = [110, 179, -50, 25]
        if selected_country == "Cyprus":
            region_extent = [20, 50, 25, 50]

        # Figure/DPI: bigger canvas for downloads
        figsize = (12, 8) if not hi_res else (16, 10)

        fig = plt.figure(figsize=figsize, dpi=dpi)
        ax = plt.axes(projection=ccrs.PlateCarree())
        tiler = get_tiler(basemap)
        ax.add_image(tiler, tile_zoom)

        # Small padding so borders are not flush
        ax.set_extent([minx - 0.1, maxx + 0.1, miny - 0.1, maxy + 0.1])

        # Main geometry
        geometry.plot(ax=ax, edgecolor='red', facecolor='none', linewidth=2, transform=ccrs.PlateCarree())

        # Labels
        if selected_city and city_geom is not None:
            pt = city_geom.geometry[0].centroid
            ax.plot(pt.x, pt.y, 'ro', markersize=12, transform=ccrs.PlateCarree())
            ax.text(pt.x + 0.002, pt.y, label_text, ha='left', fontsize=9,
                    bbox=dict(facecolor='white', alpha=0.6), transform=ccrs.PlateCarree())
        else:
            for geom in geometry:
                pt = geom.representative_point()
                ax.text(pt.x, pt.y, label_text, ha='center', fontsize=9,
                        bbox=dict(facecolor='white', alpha=0.6), transform=ccrs.PlateCarree())

        # Map features
        ax.add_feature(cfeature.BORDERS, linestyle=":", edgecolor="black")
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
        ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5)

        # Scale bar (latitude-aware)
        lat_center = (miny + maxy) / 2.0
        dx_m = 111320.0 * math.cos(math.radians(lat_center))
        scalebar = ScaleBar(dx_m, units="m", fixed_units="km", location="lower left")
        ax.add_artist(scalebar)

        # North arrow
        ax.annotate("N", xy=(0.1, 0.9), xytext=(0.1, 0.8),
                    arrowprops=dict(facecolor='black', width=5, headwidth=15),
                    ha='center', va='center', fontsize=12, xycoords=ax.transAxes)

        plt.title(title, fontsize=13, weight="bold")

        # Inset
        loc = "upper right" if inset_pos == "upper right" else "lower right"
        EURO_REGIONS = {"Northern Europe", "Eastern Europe", "Southern Europe", "Western Europe"}
        AFRICA_REGIONS = {"Northern Africa", "Western Africa", "Middle Africa", "Eastern Africa", "Southern Africa"}
        BIGGER_INSET_REGIONS = EURO_REGIONS | AFRICA_REGIONS
        size_pct = "35%" if region in BIGGER_INSET_REGIONS else "30%"

        inset_ax = inset_axes(
            ax,
            width=size_pct,
            height=size_pct,
            loc=loc,
            borderpad=0.6,
            axes_class=GeoAxes,
            axes_kwargs=dict(projection=ccrs.PlateCarree()),
        )

        inset_ax.set_extent(region_extent)
        inset_tiler = OSM()
        inset_ax.add_image(inset_tiler, 2)
        inset_ax.add_feature(cfeature.BORDERS, linestyle=":", edgecolor="black")
        inset_ax.add_feature(cfeature.COASTLINE, linewidth=0.5)

        gdf_country = gdf[gdf['name'] == selected_country]
        if not gdf_country.empty:
            gdf_country.plot(ax=inset_ax, edgecolor='red', facecolor='none', linewidth=2, transform=ccrs.PlateCarree())
        if selected_city and city_geom is not None:
            pt = city_geom.geometry[0].centroid
            inset_ax.plot(pt.x, pt.y, 'ro', markersize=10, transform=ccrs.PlateCarree())

        # Output path
        output_dir = Path(tempfile.gettempdir()) / "study_area_app"
        output_dir.mkdir(parents=True, exist_ok=True)

        if out_path is None:
            out_path = output_dir / "map_preview.png"

        plt.savefig(out_path, bbox_inches="tight", dpi=dpi)
        plt.close()
        return out_path

    except Exception as e:
        import traceback
        traceback.print_exc()
        last_error_message = str(e)
        print(f"Map generation failed: {e}")
        return None

# ---------------------- UI ----------------------
zoom_choices = [0.05, 0.1, 0.5, 1, 1.5, 2]

# Helper to append an info icon with a tooltip in English
def info_label(text, tooltip):
    return ui.TagList(
        ui.span(text),
        ui.span(" ⓘ", title=tooltip, style="cursor: help; margin-left:6px;")
    )

app_ui = ui.page_fluid(
    ui.panel_title("🗺️ Study Area Map Generator"),
    ui.layout_columns(
        ui.card(
            ui.input_select(
                "country",
                info_label("🌍 Select a Country",
                           "Choose a country. The map will auto-zoom to its extent (min 1°×1°)."),
                choices=[""] + country_list,
                selected="Ecuador"
            ),
            ui.input_text(
                "city",
                info_label("📍 Or search a city/place (OSM)",
                           "Type a city/place. The map will center a square around it using the chosen radius."),
                placeholder="e.g., Augsburg, Germany"
            ),
            ui.input_select(
                "zoom_radius",
                info_label("🔍 Zoom Radius (degrees)",
                           "For city mode: half-size of the bounding box around the search point."),
                choices=zoom_choices,
                selected=1
            ),
            ui.input_radio_buttons(
                "inset",
                info_label("👁️ Inset map position",
                           "Choose where to place the regional inset map on the figure."),
                choices=list(inset_positions.keys()),
                selected="upper right"
            ),
            ui.input_text(
                "title",
                info_label("📝 Map title",
                           "Text displayed as the figure title."),
                value="Fig. 1 Study Area Map"
            ),
            ui.input_radio_buttons(
                "basemap_source",
                info_label("🗺️ Select Basemap",
                           "Switch between OSM and Google Hybrid tiles."),
                choices=["OSM", "Google Hybrid"],
                selected="OSM"
            ),
            ui.input_action_button("update", "📊 Generate Map", class_="btn btn-primary mt-2"),
            ui.download_button("download_map", "⬇️ Download Map (Hi-Res)", class_="btn btn-success mt-2"),
            ui.hr(),
            ui.markdown("**💬 Credits:** Dr. Cesar Ivan Alvarez"),
            ui.markdown("[👥 LinkedIn Profile](https://www.linkedin.com/in/cesar-ivan-alvarez-0847253a/)"),
            ui.markdown("📧 Email: cesar.alvarez@uni-a.de"),
            class_="p-3 border shadow-sm bg-light",
            width=4
        ),
        ui.card(
            ui.output_image("map_output"),
            ui.output_ui("message_output"),
            class_="p-3 border shadow-sm bg-white",
            width=8
        )
    )
)

# ---------------------- Server ----------------------
def server(input, output, session):
    selected_country = reactive.Value("Ecuador")
    selected_city = reactive.Value("")
    selected_inset = reactive.Value("bottom right")
    selected_title = reactive.Value("Fig. 1 Study Area Map")
    selected_zoom_radius = reactive.Value(1.0)
    selected_basemap = reactive.Value("OSM")

    @reactive.effect
    @reactive.event(input.update)
    def _():
        selected_country.set(input.country())
        selected_city.set(input.city())
        selected_inset.set(input.inset())
        selected_title.set(input.title())
        selected_zoom_radius.set(float(input.zoom_radius()))
        selected_basemap.set(input.basemap_source())

    @reactive.Calc
    def preview_path():
        # Build a preview (screen-res)
        return create_map(
            selected_country(),
            selected_city(),
            inset_pos=selected_inset(),
            title=selected_title(),
            zoom_radius=selected_zoom_radius(),
            basemap=selected_basemap(),
            dpi=150,
            out_path=None,
            hi_res=False
        )

    @output
    @render.image
    def map_output():
        path = preview_path()
        if not path or not path.exists() or path.is_dir():
            return None
        return {"src": str(path), "alt": "Generated map", "width": "100%"}

    @output
    @render.ui
    def message_output():
        path = preview_path()
        if not path or not path.exists() or path.is_dir():
            return ui.p(f"❌ Unable to generate map: {last_error_message}", class_="text-danger fw-bold")
        return None

    # -------- Download handler (hi-res) --------
    @output
    @render.download(filename=lambda: f"study_area_map_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    def download_map():
        # Render a high-resolution image to a temp file and return its path
        out_dir = Path(tempfile.gettempdir()) / "study_area_app"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "map_hires.png"
        path = create_map(
            selected_country(),
            selected_city(),
            inset_pos=selected_inset(),
            title=selected_title(),
            zoom_radius=selected_zoom_radius(),
            basemap=selected_basemap(),
            dpi=300,            # high DPI
            out_path=out_file,  # explicit path
            hi_res=False         # bump tile zoom by +1 for crisper tiles
        )
        # Returning the file path is enough; Shiny will stream it to the browser.
        return str(path)

app = App(app_ui, server)
