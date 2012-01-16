'''
PhotoPops.py
'''

import Image
import ImageEnhance
import json
import os
import pika
import re
import serial
import shutil
from socketio import SocketIO
import subprocess
import sys
import time

# Initialization settings
photo_list = list()

# Connect to rabbitmq


# Load config values from etc/photopops.cfg

# Connect to Arduino
s = serial.Serial('/dev/ttyACM0');

# Node.js connection
sio = SocketIO()
sio.send("log_event", "PhotoPops.py started")
lastheartbeat = time.time()

def download_photo():
	''' Download photo from camera with gphoto2. Delete photo from camera immediately.  Return filename. '''
	print "Downloading photo...",
	global TMPDIR

	# Save file to tmp directory
	os.chdir(TMPDIR)

	# Photo already on camera, download it
	p = subprocess.Popen(['/usr/bin/gphoto2', '-R', '--get-file', '1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	res = p.communicate()

	# Check for errors before continuing
	m = re.search("(Error)",res[1])
	if m is not None:
		sio.send("log_event", "Camera errored out")
		return False

	# Pull photo filename from gphoto2 output
	m = re.search("(\w+_\d+.JPG)", res[0])
	if not m.group(0):
		sio.send("log_event", "Camera capture output invalid")
		return False
	else:
		fn = m.group(0)

	# Delete photo from camera
	p = subprocess.Popen(['/usr/bin/gphoto2', '-R', '--delete-file', '1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

	sio.send("log_event", "Photo %s captured" % fn)
	print "done."
	
	# Return filename of photo
	return fn

def initial_resize_photo(fn, eventname):
	''' Initial photo process.  
	Only save a single file that's 1080x1920 to display on TV.
	Greenscreen processing will happen later.
	'''
	global EV_ORIG_DIR
	global EV_PROC_DIR

	# Move original photo to event directory
	shutil.move("%s/%s" % (TMPDIR, fn), "%s/%s" % (EV_ORIG_DIR, fn))
	orig_fullpath = "%s/%s" % (EV_ORIG_DIR, fn)
	proc_fullpath = "%s/%s" % (EV_PROC_DIR, fn)

	# Rotate photo
	im = Image.open("%s/%s" % (EV_ORIG_DIR, fn))
	im = im.rotate(90, expand=True)
	im.save("%s/%s" % (EV_ORIG_DIR, fn), "JPEG", quality=90)

	# Open photo and watermark
	im = Image.open("%s/%s" % (EV_ORIG_DIR, fn))

	# Save original image to Processed directory.
	im.save("%s/%s" % (EV_PROC_DIR, fn), 'JPEG', quality=90)

	# Generate 1080x1920 for TV display
	thumb_tv = im.copy()
	thumb_tv.thumbnail((1080,1920), Image.NEAREST)
	thumb_tv.save("%s/1920-%s" % (EV_PROC_DIR, fn), 'JPEG', quality=90)

	sio.send("log_event", "Photo processed")
	sio.send("tv_photo_taken", "/opt/photopops/events/%s/original/1920-%s" % (eventname, fn))

while True:
	try:
		# Send heartbeat to socket.io every 15 seconds if there is no data in the Serial queue.
		if s.inWaiting() == 0:
			if time.time() - lastheartbeat >= 15:
				print "Sending heartbeat."
				sio.heartbeat()
				lastheartbeat = time.time()
			time.sleep(0.1)
		else:
			serialvalue = s.read()

			if serialvalue == "A":
				# Button pressed
				print "That was Easy."
				sio.send("log_event", "Easy Button pressed.")

				# Load event settings on every new button press iteration, so any changes will take effect.
				# Load JSON from etc/photopops.cfg
				# loadcfg()

				''' All of this moves to loadcfg()
				# Load configuration settings
				EVENTNAME = event.shortname
				TMPDIR = "/tmp/photopops"
				EV_DIR = "/opt/photopops/%s" % EVENTNAME
				EV_ORIG_DIR = "/opt/photopops/%s/original" % EVENTNAME
				EV_PROC_DIR = "/opt/photopops/%s/processed" % EVENTNAME
				USB_DIR = "/media/photopops"
				WATERMARK = "/opt/photopops/assets/logo-angled-600x250.png"

				# Make sure directories exist
				if not os.path.isdir(TMPDIR):
					os.mkdir(TMPDIR)
				if not os.path.isdir(EV_DIR):
					os.mkdir(EV_DIR)
				if not os.path.isdir(EV_ORIG_DIR):
					os.mkdir(EV_ORIG_DIR)
				if not os.path.isdir(EV_PROC_DIR):
					os.mkdir(EV_PROC_DIR)
				'''

				# TODO: Adjust delays in Arduino
				# TODO: Move timer values to photopops.cfg or camera.cfg
				# Notify TV display that button was pressed, via node.js
				sio.send("button_pressed", "")
				time.sleep(3.5)

				# Ready to take picture.  Send a "B" to trigger shutter
				s.write("B")

			if serialvalue == "C":
				# Photo was taken
				print "Photo captured"

				# Wait for camera to finish writing photo before downloading.
				time.sleep(2)

				fn = download_photo()
				if not fn:
					# Camera didn't capture or errored out.  Send 'D' to reset Arduino and go to next iteration.
					print "Camera error"
					s.write("D")
					continue

				# Process Photo.  Resize, add logo, contrast and curves
				initial_resize_photo(fn, EVENTNAME)

				# Copy original photo to USB stick
				# QUEUE EVENT: send to usbstick

				# Photo complete. Set Arduino to ready
				print "Photo %s complete." % fn

				photo_list.append(fn)

				# Keep photo up on screen for a few seconds
				# and ignore any button presses
				time.sleep(5)

				# Only write D to re-enable the button if the whole cycle is complete. Otherwise, send B to do it again.
				if len(photo_list) == event.number_up:
					print "Captured %s photos" % len(photo_list)
					print photo_list

					# QUEUE EVENT: send to printer
					if event.send_to_printer:
						print "Printing...",
						beanstalk.put('{"cmd":"print","files":%s}' % json.dumps(photo_list))
						sio.send("log_event", "Sending to printer")
						print "done."

					# TODO: Build composite photo and send to printer
					s.write("D")

					# Clear photo_list
					photo_list = list()
				else:
					# Still need more photos.  Run countdown again.

					# Notify TV display that button was pressed, via node.js
					sio.send("button_pressed", "")
					time.sleep(3.5)

					# Ready to take picture.  Send a "B" to trigger shutter
					s.write("B")
					print "sending B #%d" % len(photo_list)

	except KeyboardInterrupt:
		print "Closing PhotoPops."
		sio.send("log_event", "PhotoPops.py shutting down.")
		del sio
		sys.exit()
