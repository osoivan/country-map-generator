from shiny import App, ui, render, reactive
import geopandas as gpd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.io.img_tiles import OSM
from matplotlib_scalebar.scalebar import ScaleBar
from pathlib import Path
import tempfile
from geopy.geocoders import Nominatim
from shapely.geometry import box

# Load GeoJSON
geojson_path = "world-administrative-boundaries.geojson"
gdf = gpd.read_file(geojson_path)
gdf = gdf[gdf['name'].notna()]
country_list = sorted(gdf['name'].unique())

# Inset and continent
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

# Map generation logic
def create_map(selected_country, selected_city, inset_pos="upper right", title="Study Area Map"):
    try:
        city_geom = None
        label_text = ""
        geometry = None
        continent = "World"

        if selected_city:
            geolocator = Nominatim(user_agent="country-map-generator")
            location = geolocator.geocode(selected_city)
            if location is None:
                raise ValueError(f"City '{selected_city}' not found.")
            lon, lat = location.longitude, location.latitude
            box_geom = box(lon - 1, lat - 1, lon + 1, lat + 1)
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
            raise ValueError("Either country or city must be provided.")

        if geometry is None:
            raise ValueError("No geometry found.")

        minx, miny, maxx, maxy = geometry.total_bounds
        lon_span, lat_span = maxx - minx, maxy - miny
        zoom_level = 7
        if lon_span > 40 or lat_span > 40:
            zoom_level = 4
        elif lon_span > 20 or lat_span > 20:
            zoom_level = 5

        continent_extent = continentcoord.get(continent, [-180, 180, -90, 90])
        fig = plt.figure(figsize=(12, 8), dpi=150)
        ax = plt.axes(projection=ccrs.PlateCarree())

        try:
            ax.add_image(OSM(), zoom_level)
        except:
            print("OSM background failed.")

        ax.set_extent([minx - 1, maxx + 1, miny - 1, maxy + 1])
        geometry.plot(ax=ax, edgecolor='red', facecolor='none', linewidth=2, transform=ccrs.PlateCarree())

        # Label
        if selected_city and city_geom is not None:
            pt = city_geom.geometry[0].centroid
            ax.plot(pt.x, pt.y, 'ro', markersize=10, transform=ccrs.PlateCarree())
            plt.text(pt.x, pt.y + 1, label_text, ha='center', fontsize=9, bbox=dict(facecolor='white', alpha=0.5),
                     transform=ccrs.PlateCarree())
        else:
            for geom in geometry:
                pt = geom.representative_point()
                plt.text(pt.x, pt.y, label_text, ha='center', fontsize=9, bbox=dict(facecolor='white', alpha=0.5),
                         transform=ccrs.PlateCarree())

        ax.add_feature(cfeature.BORDERS, linestyle=":", edgecolor="black")
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
        ax.gridlines(draw_labels=True, linewidth=0.5, color='gray', alpha=0.5)
        ax.add_artist(ScaleBar(1, units='km', location='lower left'))
        ax.annotate("N", xy=(0.1, 0.9), xytext=(0.1, 0.8),
                    arrowprops=dict(facecolor='black', width=5, headwidth=15),
                    ha='center', va='center', fontsize=12, xycoords=ax.transAxes)

        plt.title(title, fontsize=12, weight="bold")

        inset_ax = fig.add_axes(inset_positions[inset_pos], projection=ccrs.PlateCarree())
        inset_ax.set_extent(continent_extent)
        try:
            inset_ax.add_image(OSM(), 2)
        except:
            print("Inset map failed.")

        inset_ax.add_feature(cfeature.BORDERS, linestyle=":", edgecolor="black")
        inset_ax.add_feature(cfeature.COASTLINE, linewidth=0.5)

        if selected_city and city_geom is not None:
            city_geom.plot(ax=inset_ax, edgecolor='red', facecolor='none', linewidth=2, transform=ccrs.PlateCarree())
        else:
            geometry.plot(ax=inset_ax, edgecolor='red', facecolor='none', linewidth=2, transform=ccrs.PlateCarree())

        output_file = Path(tempfile.gettempdir()) / "map_preview.png"
        plt.savefig(output_file, bbox_inches="tight", dpi=150)
        plt.close()
        return output_file
    except Exception as e:
        print(f"Error: {e}")
        return Path("")

# UI
app_ui = ui.page_fluid(
    ui.div(ui.h2("Country Map Generator", class_="text-center fw-bold"), class_="mb-4"),
    ui.layout_columns(
        ui.card(
            ui.input_select("country", "Select a country:", choices=[""] + country_list, selected="Ecuador"),
            ui.input_text("city", "Or search a city/place (OSM):", placeholder=""),
            ui.input_radio_buttons("inset", "Inset map position:", choices=["upper right", "bottom right"], selected="upper right"),
            ui.input_text("title", "Map title:", value="Fig. 1 Study Area Map"),
            ui.input_action_button("update", "Generate Map", class_="btn btn-primary mt-2"),
            ui.hr(),
            ui.markdown("**Credits:** Dr. Cesar Ivan Alvarez"),
            ui.markdown("[LinkedIn Profile](https://www.linkedin.com/in/cesar-ivan-alvarez-0847253a/)"),
            ui.markdown("Email: cesar.alvarez@uni-a.de"),
            class_="p-3 border",
            width=4
        ),
        ui.card(
            ui.output_image("map_output"),
            ui.output_ui("message_output"),
            class_="p-3 border",
            width=8
        )
    )
)

# Server
def server(input, output, session):
    selected_country = reactive.Value("Ecuador")
    selected_city = reactive.Value("")
    selected_inset = reactive.Value("upper right")
    selected_title = reactive.Value("Fig. 1 Study Area Map")

    @reactive.effect
    @reactive.event(input.update)
    def _():
        selected_country.set(input.country())
        selected_city.set(input.city())
        selected_inset.set(input.inset())
        selected_title.set(input.title())

    @reactive.Calc
    def current_map():
        return create_map(
            selected_country(),
            selected_city(),
            inset_pos=selected_inset(),
            title=selected_title()
        )

    @output
    @render.image
    def map_output():
        path = current_map()
        if not path.exists():
            return None
        return {"src": str(path), "alt": "Generated map", "width": "100%"}

    @output
    @render.ui
    def message_output():
        path = current_map()
        if not path.exists():
            return ui.p("❌ Unable to generate map. Check inputs or try another place.", class_="text-danger fw-bold")
        return None

# App
app = App(app_ui, server)
