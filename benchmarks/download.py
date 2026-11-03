"""
benchmarks/download.py

Downloads one file of any type from a URL and saves it to a local path.
Usage: python benchmarks/download.py --url URL --output_path PATH
"""

import argparse
import os
import shutil
import urllib.request

# Seconds to wait for the server to respond before giving up
TIMEOUT_SECONDS = 60

# Some servers reject Python's default User-Agent
USER_AGENT = "DocIngestEngine/1.0"


def download_file(url: str, output_path: str) -> None:
	"""
	Input: url - the file to download; output_path - where to save it.
	Output: none. Writes the file to output_path, creating its folder if needed.
	What it does: streams the response to disk, so a large file is never held in memory.
	A file that fails partway is removed, so output_path never holds a partial download.
	"""
	output_folder = os.path.dirname(output_path)
	if output_folder != "":
		os.makedirs(output_folder, exist_ok=True)

	request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

	try:
		with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
			with open(output_path, "wb") as output_file:
				shutil.copyfileobj(response, output_file)
	except Exception:
		if os.path.exists(output_path):
			os.remove(output_path)
		raise


def main() -> None:
	"""
	Input: --url and --output_path from the command line.
	Output: none. Downloads the file.
	"""
	argument_parser = argparse.ArgumentParser(description="Download one file from a URL.")
	argument_parser.add_argument("--url", required=True, help="The file to download")
	argument_parser.add_argument("--output_path", required=True, help="Where to save it")
	arguments = argument_parser.parse_args()

	download_file(arguments.url, arguments.output_path)
	print("Saved " + arguments.url + " to " + arguments.output_path)


if __name__ == "__main__":
	main()
