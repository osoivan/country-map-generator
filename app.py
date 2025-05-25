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

# Custom class for Google Hybrid basemap
class GoogleHybrid(GoogleTiles):
    def _image_url(self, tile):
        x, y, z = tile
        return f"https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}"

# Global error tracker
last_error_message = ""

# Load world boundaries
geojson_path = Path(__file__).parent / "world-administrative-boundaries.geojson"
gdf = gpd.read_file(geojson_path)
gdf = gdf[gdf['name'].notna()]
country_list = sorted(gdf['name'].unique())

# Map inset positions and continent extents
inset_positions = {
    "upper right": [0.7, 0.6, 0.2, 0.2],
    "bottom right": [0.7, 0.1, 0.2, 0.2]
}
continentcoord = {
    "Africa": [-20, 55, -35, 37],
    "Asia": [25, 180, -10, 55],
    "Europe": [-30, 50, 35, 75],
    "North America": [-170, -25, 10, 85],
    "South America": [-90, -30, -60, 15],
    "Oceania": [110, 180, -50, 10],
    "Antarctica": [-180, 180, -90, -60]
}

def get_tiler(basemap_name):
    return GoogleHybrid() if basemap_name == "Google Hybrid" else OSM()

def create_map(selected_country, selected_city, inset_pos="upper right", title="Study Area Map", zoom_radius=1.0, basemap="OSM"):
    global last_error_message
    try:
        city_geom, label_text, geometry = None, "", None
        continent = "World"

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
                    continent = row["continent"]
                    break
        elif selected_country:
            gdf_info = gdf[gdf['name'] == selected_country]
            if gdf_info.empty:
                raise ValueError(f"Country '{selected_country}' not found.")
            continent = gdf_info.iloc[0]["continent"]
            geometry = gdf_info["geometry"].simplify(0.005, preserve_topology=True)
            label_text = selected_country
        else:
            raise ValueError("Please select a country or city.")

        if geometry is None or geometry.empty:
            raise ValueError("No geometry to display.")

        minx, miny, maxx, maxy = geometry.total_bounds
        zoom_level = (
            12 if selected_city and zoom_radius <= 0.5 else
            8 if selected_city and zoom_radius <= 1 else
            7 if not selected_city and max(maxx - minx, maxy - miny) <= 10 else
            6 if not selected_city and max(maxx - minx, maxy - miny) <= 20 else
            5 if not selected_city and max(maxx - minx, maxy - miny) <= 40 else
            4
        )

        continent_extent = continentcoord.get(continent, [-180, 180, -90, 90])
        fig = plt.figure(figsize=(12, 8), dpi=150)
        ax = plt.axes(projection=ccrs.PlateCarree())

        tiler = get_tiler(basemap)
        ax.add_image(tiler, zoom_level)
        ax.set_extent([minx - 0.1, maxx + 0.1, miny - 0.1, maxy + 0.1])
        geometry.plot(ax=ax, edgecolor='red', facecolor='none', linewidth=2, transform=ccrs.PlateCarree())

        if selected_city and city_geom is not None:
            pt = city_geom.geometry[0].centroid
            ax.plot(pt.x, pt.y, 'ro', markersize=12, transform=ccrs.PlateCarree())
            ax.text(pt.x + 0.002, pt.y, label_text, ha='left', fontsize=9, bbox=dict(facecolor='white', alpha=0.6), transform=ccrs.PlateCarree())
        else:
            for geom in geometry:
                pt = geom.representative_point()
                ax.text(pt.x, pt.y, label_text, ha='center', fontsize=9, bbox=dict(facecolor='white', alpha=0.6), transform=ccrs.PlateCarree())

        ax.add_feature(cfeature.BORDERS, linestyle=":", edgecolor="black")
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
        ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5)
        ax.add_artist(ScaleBar(1, units='km', location='lower left'))
        ax.annotate("N", xy=(0.1, 0.9), xytext=(0.1, 0.8),
                    arrowprops=dict(facecolor='black', width=5, headwidth=15),
                    ha='center', va='center', fontsize=12, xycoords=ax.transAxes)

        plt.title(title, fontsize=13, weight="bold")

        inset_ax = fig.add_axes(inset_positions[inset_pos], projection=ccrs.PlateCarree())
        inset_ax.set_extent(continent_extent)
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

        output_dir = Path(tempfile.gettempdir()) / "study_area_app"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "map_preview.png"
        plt.savefig(output_file, bbox_inches="tight", dpi=150)
        plt.close()
        return output_file

    except Exception as e:
        import traceback
        traceback.print_exc()
        last_error_message = str(e)
        print(f"Map generation failed: {e}")
        return None

# Update zoom_radius input back to discrete dropdown options
zoom_choices = [0.05, 0.1, 0.5, 1, 1.5, 2]

app_ui = ui.page_fluid(
    ui.panel_title("🗺️ Study Area Map Generator"),
    ui.layout_columns(
        ui.card(
            ui.input_select("country", "🌍 Select a Country:", choices=[""] + country_list, selected="Ecuador"),
            ui.input_text("city", "📍 Or search a city/place (OSM):", placeholder="e.g., Augsburg, Germany"),
            ui.input_select("zoom_radius", "🔍 Zoom Radius (degrees):", choices=[0.05, 0.1, 0.5, 1, 1.5, 2], selected=1),
            ui.input_radio_buttons("inset", "👁️ Inset map position:", choices=list(inset_positions.keys()), selected="upper right"),
            ui.input_text("title", "📝 Map title:", value="Fig. 1 Study Area Map"),
            ui.input_radio_buttons("basemap_source", "🗺️ Select Basemap:", choices=["OSM", "Google Hybrid"], selected="OSM"),
            ui.input_action_button("update", "📊 Generate Map", class_="btn btn-primary mt-2"),
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
    def current_map():
        return create_map(
            selected_country(),
            selected_city(),
            inset_pos=selected_inset(),
            title=selected_title(),
            zoom_radius=selected_zoom_radius(),
            basemap=selected_basemap()
        )

    @output
    @render.image
    def map_output():
        path = current_map()
        if not path or not path.exists() or path.is_dir():
            return None
        return {"src": str(path), "alt": "Generated map", "width": "100%"}

    @output
    @render.ui
    def message_output():
        path = current_map()
        if not path or not path.exists() or path.is_dir():
            return ui.p(f"❌ Unable to generate map: {last_error_message}", class_="text-danger fw-bold")
        return None

app = App(app_ui, server)

