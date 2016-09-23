import appdirs
from os.path import expanduser

# Increases the quality and the size. Possible values: 4, 8, 16, 20
level = 4

# Define the final output size and a file (with alpha) to composite over the output
# For example, an image of the Milky Way as seen from Earth
# that has an alpha cutout in the shape of the Earth from Himawari
resize_to = "3840x2160"
overlay_path = expanduser("~/Pictures/Himawari/himawari-overlay.png")

# Define a hourly offset or let the script calculate it depending on your timezone
# If auto_offset is True, then script will calculate your hour offset automatically depending on your location.
# If hour_offset is greater than 0, then script will use it.
# If both of the variables are set different than their default values below, then script will raise an error. Here,
# using the default values, script will put the realtime picture of Earth.
auto_offset = True
hour_offset = 0

# Path to the output directory
output_dir = appdirs.user_cache_dir(appname="himawaripy", appauthor=False)

# Deadline for the whole download process in minutes
dl_deadline = 6
