#!/usr/bin/env python3

import argparse
from datetime import timedelta, datetime
import io
import itertools as it
import json
from lxml import html
import multiprocessing as mp
import multiprocessing.dummy as mp_dummy
import os
import os.path as path
import sys
from time import strptime, strftime, mktime
import urllib.request
from glob import iglob, glob
import threading
import time
from logging import warnings

import appdirs
from PIL import Image, ImageDraw, ImageFilter
from dateutil.tz import tzlocal

from .utils import set_background, get_desktop_environment


# Semantic Versioning: Major, Minor, Patch
HIMAWARIPY_VERSION = (2, 0, 0)
counter = None
HEIGHT = 11000
WIDTH = 11000
BASE_URL = "http://rammb.cira.colostate.edu/ramsdis/online"

# The image is yuuge
warnings.simplefilter('ignore', Image.DecompressionBombWarning)


def calculate_time_offset(latest_date, auto, preferred_offset):
    if auto:
        preferred_offset = int(datetime.now(tzlocal()).strftime("%z")[0:3])
        print("Detected offset: UTC{:+03d}:00".format(preferred_offset))
        if 11 >= preferred_offset > 10:
            preferred_offset = 10
            print("Offset is greater than +10, +10 will be used...")
        elif 12 >= preferred_offset > 11:
            preferred_offset = -12
            print("Offset is greater than +10, -12 will be used...")

    himawari_offset = 10  # UTC+10:00 is the time zone that himawari is over
    offset = int(preferred_offset - himawari_offset)

    offset_tmp = datetime.fromtimestamp(mktime(latest_date)) + timedelta(hours=offset)
    offset_time = offset_tmp.timetuple()

    return offset_time


def download_chunk(args):
    global counter

    x, y, latest, level = args
    url_format = "http://himawari8.nict.go.jp/img/D531106/{}d/{}/{}_{}_{}.png"
    url = url_format.format(level, WIDTH, strftime("%Y/%m/%d/%H%M%S", latest), x, y)

    tiledata = download(url)

    with counter.get_lock():
        counter.value += 1
        if counter.value == level * level:
            print("Downloading tiles: completed.")
        else:
            print("Downloading tiles: {}/{} completed...".format(counter.value, level * level))
    return x, y, tiledata


def parse_args():
    parser = argparse.ArgumentParser(description="set (near-realtime) picture of Earth as your desktop background",
                                     epilog="http://labs.boramalper.org/himawaripy")

    parser.add_argument("--version", action="version", version="%(prog)s {}.{}.{}".format(*HIMAWARIPY_VERSION))

    group = parser.add_mutually_exclusive_group()

    group.add_argument("--auto-offset", action="store_true", dest="auto_offset", default=False,
                       help="determine offset automatically")
    group.add_argument("-o", "--offset", type=int, dest="offset", default=10,
                       help="UTC time offset in hours, must be less than or equal to +10")

    parser.add_argument("-l", "--level", type=int, choices=[4, 8, 16, 20], dest="level", default=4,
                        help="increases the quality (and the size) of each tile. possible values are 4, 8, 16, 20")
    parser.add_argument("-d", "--deadline", type=int, dest="deadline", default=6,
                        help="deadline in minutes to download all the tiles, set 0 to cancel")
    parser.add_argument("--save-battery", action="store_true", dest="save_battery", default=False,
                        help="stop refreshing on battery")
    parser.add_argument("--output-dir", type=str, dest="output_dir",
                        help="directory to save the temporary background image",
                        default=appdirs.user_cache_dir(appname="himawaripy", appauthor=False))
    parser.add_argument("--composite-over", type=str, dest="composite_over",
                        help="image to composite the background image over",
                        default=None)

    args = parser.parse_args()

    if not -12 <= args.offset <= 10:
        sys.exit("OFFSET has to be between -12 and +10!\n")

    if not args.deadline >= 0:
        sys.exit("DEADLINE has to be greater than (or equal to if you want to disable) zero!\n")

    return args


def is_discharging():
    if not sys.platform.startswith("linux"):  # I hope this will not end up like Windows 95/98 checks one day...
        sys.exit("Battery saving feature works only on linux!\n")

    if len(glob("/sys/class/power_supply/BAT*")) > 1:
        print("Multiple batteries detected, using BAT0.")

    with open("/sys/class/power_supply/BAT0/status") as f:
        status = f.readline().strip()

        return status == "Discharging"


def download(url):
    exception = None

    for i in range(1, 4):  # retry max 3 times
        try:
            with urllib.request.urlopen(url) as response:
                return response.read()
        except Exception as e:
            exception = e
            print("[{}/3] Retrying to download '{}'...".format(i, url))
            time.sleep(1)
            pass

    if exception:
        raise exception
    else:
        sys.exit("Could not download '{}'!\n".format(url))


def find_closest_recent_time(html_tree, requested_time):
    requested_time_string = strftime("%Y-%m-%d %H:%M", requested_time)
    requested_time = datetime(*requested_time[:6])

    ideal_match = html_tree.xpath("//form[@id='select_images']/table/tr/td[contains(., '{}')]/text()".format(requested_time_string))
    if ideal_match:
        return ideal_match[0]

    recent_times = html_tree.xpath("//form[@id='select_images']/table/tr/td[1]/text()")

    closest_match = None
    closest_match_diff = None
    closest_match_diff_prev = None

    for recent_time_string in recent_times:
        recent_time = datetime.strptime(recent_time_string, "%Y-%m-%d %H:%M")

        if closest_match is None:
            closest_match = recent_time_string
            if recent_time > requested_time:
                closest_match_diff = recent_time - requested_time
            else:
                closest_match_diff = requested_time - recent_time
            continue

        closest_match_diff_prev = closest_match_diff
        if recent_time > requested_time:
            closest_match_diff = recent_time - requested_time
        else:
            closest_match_diff = requested_time - recent_time

        if closest_match_diff == closest_match_diff_prev:
            # print("Difference is the same, picking latter... {} == {}".format(closest_match_diff, closest_match_diff_prev))
            return closest_match

        elif closest_match_diff < closest_match_diff_prev:
            # print("Getting closer... {} < {}".format(closest_match_diff, closest_match_diff_prev))
            closest_match = recent_time_string

        else:
            # print("Getting farther, stopping... {} !< {}".format(closest_match_diff, closest_match_diff_prev))
            return closest_match

def thread_main(args):
    global counter
    counter = mp.Value("i", 0)

    print("Updating...")
    latest_html = download("{}/archive_hi_res.asp?data_folder=himawari-8/full_disk_ahi_natural_color&width=800&height=800".format(BASE_URL))
    html_tree = html.fromstring(latest_html)

    latest_time = html_tree.xpath("//form[@id='select_images']/table/tr[2]/td[1]/text()")[0]
    latest = strptime(latest_time, "%Y-%m-%d %H:%M")

    print("Latest version: {} GMT.".format(strftime("%Y/%m/%d %H:%M", latest)))
    requested_time = calculate_time_offset(latest, args.auto_offset, args.offset)
    if args.auto_offset or args.offset != 10:
        print("Offset version: {} GMT.".format(strftime("%Y/%m/%d %H:%M", requested_time)))

    closest_match = find_closest_recent_time(html_tree, requested_time)
    print("Found closest match: {} GMT.".format(closest_match))

    download_url = html_tree.xpath("//form[@id='select_images']/table/tr/td[contains(., '{}')]/following-sibling::td[5]/a".format(closest_match))
    if not download_url:
        sys.exit("Unable to find download URL")
    download_url = "{}/{}".format(BASE_URL, download_url[0].get("href"))
    print("Download URL: {}".format(download_url))

    if args.composite_over is not None:
        print("Opening image to composite over...")
        try:
            composite_img = Image.open(args.composite_over)
        except Exception as e:
            sys.exit("Unable to open --composite-over image!\n")

    himawari_width = WIDTH
    himawari_height = HEIGHT
    print("Downloading image...")
    himawari_img = Image.open(io.BytesIO(download(download_url)))
    output_img = himawari_img

    if args.composite_over is not None:
        print("Compositing over input image")
        composite_width, composite_height = composite_img.size
        resize_ratio = min(composite_width / himawari_width, composite_height / himawari_height)

        himawari_img = himawari_img.resize((round(himawari_width * resize_ratio), round(himawari_height * resize_ratio)),
            Image.ANTIALIAS)

        radius_img = min(himawari_width, himawari_height) * resize_ratio / 2
        himawari_center_img = Image.new("RGB", (composite_width, composite_height), "black")
        himawari_center_img.paste(himawari_img, (round(composite_width / 2 - radius_img), round(composite_height / 2 - radius_img)))

        radius = min(himawari_width, himawari_height) * resize_ratio * 0.988 / 2
        left = round(composite_width / 2 - radius)
        right = round(composite_width / 2 + radius)
        top = round(composite_height / 2 - radius)
        bottom = round(composite_height / 2 + radius)

        mask_img = Image.new("L", (composite_width, composite_height), "black")
        draw = ImageDraw.Draw(mask_img)
        draw.ellipse((left, top, right, bottom), fill='white')
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=2))

        composite_img.paste(himawari_center_img, (0, 0), mask_img)

        output_img = composite_img

    for file in iglob(path.join(args.output_dir, "himawari-*.png")):
        os.remove(file)

    output_file = path.join(args.output_dir, strftime("himawari-%Y%m%dT%H%M%S.png", requested_time))
    print("Saving to '%s'..." % (output_file,))
    os.makedirs(path.dirname(output_file), exist_ok=True)
    output_img.save(output_file, "PNG")

    if not set_background(output_file):
        sys.exit("Your desktop environment '{}' is not supported!\n".format(get_desktop_environment()))


def main():
    args = parse_args()

    print("himawaripy {}.{}.{}".format(*HIMAWARIPY_VERSION))

    if args.save_battery and is_discharging():
        sys.exit("Discharging!\n")

    main_thread = threading.Thread(target=thread_main, args=(args,), name="himawaripy-main-thread", daemon=True)
    main_thread.start()
    main_thread.join(args.deadline * 60 if args.deadline else None)

    if args.deadline and main_thread.is_alive():
        sys.exit("Timeout!\n")

    print()
    sys.exit(0)


if __name__ == "__main__":
    main()
