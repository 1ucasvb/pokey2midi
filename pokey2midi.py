'''
	POKEY2MIDI v0.63
	by LucasVB (http://1ucasvb.com/)
	
	Description:
		This program converts POKEY data dumps from asapscan into MIDI files
		asapscan is part of the ASAP (Another Slight Atari Player) software package
	
	ASAP site: http://asap.sourceforge.net
	For usage, run: python pokey2midi -h
	
	-------
	
	TODO:
		Percussion maps
			Doesn't seem to be working on Sweet, considering the old MIDI
			Some weird poly 0? seems to be ignored
			Any song with Poly 2 & 3?
		Perhaps use helicopter/seashore instead?
		Verify 16-bit
	
		Handle poly periods properly, check emulator
		Verify highpass behavior
		
		Map noise poly to GM instruments
			Might need to fine-tune frequency range?
			What about percussions?
'''

import os
import math
import struct
import argparse

# Constants
VERSION				= "0.63"
NTSC				= 0
PAL					= 1
NOTES				= ['A','A#','B','C','C#','D','D#','E','F','F#','G','G#']
ENABLE_16BIT		= True
DEFAULT_TIMEBASE 	= 480
DEFAULT_TEMPO 		= 60
DEBUG				= False
POLY_INSTRUMENT		= [0,0,0,0,0,80,87,80] # TODO: find the rest

# Human-readable POKEY state and other goodies
class POKEY(object):
	def __init__(self, number, mode=None):
		if mode is None:
			self.mode = NTSC
		else:
			self.mode = mode
		# Per-channel data
		self.audf		= [0,0,0,0] # channel frequency data
		self.vol		= [0,0,0,0] # channel volumes
		self.volctrl	= [0,0,0,0] # volume-only mode (used for PCM digital audio)
		self.poly		= [0,0,0,0] # channel polynomial counter data
		self._state		= dict() # internal state
		self.number		= number # POKEY number
	
	# The availalbe clock frquencies in Hz
	@property
	def CLOCK_MHz(self): # Exact values
		return 1789789 if self.mode == NTSC else 1773447
	
	@property
	def CLOCK_64kHz(self): # TODO: verify these PAL values
		return 63921.0 if self.mode == NTSC else 63921.0
	
	@property
	def CLOCK_15kHz(self): # TODO: verify these PAL values
		return 15699.9 if self.mode == NTSC else 15699.0
	
	def write(self, data): # Write data to POKEY chip
		self.writeAUDF(1, data[0])
		self.writeAUDC(1, data[1])
		self.writeAUDF(2, data[2])
		self.writeAUDC(2, data[3])
		self.writeAUDF(3, data[4])
		self.writeAUDC(3, data[5])
		self.writeAUDF(4, data[6])
		self.writeAUDC(4, data[7])
		self.writeAUDCTL(data[8])
	
	def writeAUDC(self, ch, data):
		assert ch > 0
		self.vol[ch-1]		= data & 0b00001111 # 4-bit channel volume
		self.volctrl[ch-1]	= data >> 4 & 1     # Volume Control only (for writing PCM)
		self.poly[ch-1]		= data >> 5         # Poly
		# Note: Poly is meaningless if volctrl is on
		# Otherwise, they are:
		# 0=0b000	17 Bit poly - 5 Bit poly - N
		# 1=0b001	5 Bit poly - N - 2
		# 2=0b010	4 Bit poly - 5 Bit poly - N
		# 3=0b011	5 Bit poly - N - 2
		# 4=0b100	17 Bit poly - N
		# 5=0b101	Pure Tone - N - 2
		# 6=0b110	4 Bit poly - N
		# 7=0b111	Same as #5 (Not documented)
		
	def writeAUDF(self, ch, data):
		assert ch > 0
		self.audf[ch-1] = data
	
	def writeAUDCTL(self, data):
		self.use15khz		= data >> 0 & 1 # Use 15 kHz clock for all channels, instead of 64 kHz
		self.highpass2w4	= data >> 1 & 1 # Highpass channel 2 with 4
		self.highpass1w3	= data >> 2 & 1 # Highpass channel 1 with 3
		self.join4and3		= data >> 3 & 1 # Clock channel 4 with 3 (instead of 64 kHz) (16-bit)
		self.join2and1		= data >> 4 & 1 # Clock channel 2 with 1 (instead of 64 kHz) (16-bit)
		self.clock3mhz		= data >> 5 & 1 # Clock channel 3 with 1.79 MHz, instead of 64 kHz
		self.clock1mhz		= data >> 6 & 1 # Clock channel 1 with 1.79 MHz, instead of 64 kHz
		self.poly17as9		= data >> 7 & 1 # 9-bit poly instead of 17-bit poly
		
	@property
	def AUDCTLFeatures(self):
		audctl_features = set()
		if self.use15khz:
			audctl_features.add("15khz")
		if self.highpass2w4:
			audctl_features.add("highpass2w4")
		if self.highpass1w3:
			audctl_features.add("highpass1w3")
		if self.join4and3:
			audctl_features.add("join4and3")
		if self.join2and1:
			audctl_features.add("join2and1")
		if self.clock3mhz:
			audctl_features.add("clock3mhz")
		if self.clock1mhz:
			audctl_features.add("clock1mhz")
		if self.poly17as9:
			audctl_features.add("poly17as9")
		return audctl_features
	
	@property
	def clock(self): # current global clock, set by AUDCTL
		return self.CLOCK_15kHz if self.use15khz else self.CLOCK_64kHz
	
	# Get the effective frequency for a channel. From the references docs:
	#     The Normal formula for the output frequency is:
	#     Fout = Fin /2N
	#     where N = the binary number in the frequency register (AUDF), plus 1 (N=AUDF+1).
	#     The Modified formula should be used when Fin = 1.79 MHz and a more exact result is desired
	#     Fout = Fin /2(AUDF+M)
	#     where 
	#     M = 4 if 8 bit counter (AUDCTL bit 3 or 4 = 0), 
	#     M = 7 if 16 bit counter (AUDCTL bit 3 or 4 = 1)
	#
	#     The 1.79MHz (1.78979 MHz, to be exact) clock rate is required to obtain the full range of
	#     output frequencies. The formula for determining output frequency is a little different:
	#     F0 = F/(2*(AUDF + 7)). In this case, AUDF is the two-byte frequency register value.
	#     The second register of the pair is the low order byte, either AUDF2 or AUDF4.
	#     For example, to use 1049 as a divider with registers 1 and 2, we would POKE 4 in AUDF2
	#     and 25 in AUDF1.
	#
	#
	# TODO: We don't really get the frequency from fin/N directly, actually. What we get
	# is the frequency of the pure tone. Poly counters modify this to generate a timbre, so
	# we need to consider their timbre periods to get the proper frequency.
	def getFrequency(self, ch):
		assert ch > 0
		
		if self.volctrl[ch-1]: # DC mode means no note available, has to be transcribed by hand!
			return 0
		
		# TODO: For now only, we'll only handle non-distorted notes, which make the bulk of 
		# the melody for most songs.
		# The noise will have to be handled in a better way.
		if self.poly[ch-1] not in [5,6,7]:
			return 0
		
		# TODO: figure out if the clock modifies fout of ch 4 and 2 or just 3 and 1
		# It's unclear if Fin is technically considered 1.79 MHz for 4/2 getting clocked with 3/1
		# if 3/1 are at 1.79 MHz
		# Test this on an emulator to figure out
		
		clock = self.clock # Current clock to be used
		audf = self.audf[ch-1] # register value to be used (8-bit or 16-bit)
		m = 1 # modifier value on the divide by N expression
		
		# 16-bit handling
		if ENABLE_16BIT:
			# TODO: Test this out on emulator, verify this logic
			if ch == 1:
				if self.join2and1: # Channel 1 is disabled if in 16-bit mode
					return 0
				else: # If not joined with channel 2
					if self.clock1mhz: # We modify the clock, if necessary
						clock = self.CLOCK_MHz
						m = 7 # Modifier is 7
			if ch == 2:
				if self.join2and1: # Channel 2 is used for sound in 16-bit mode
					# Create 16-bit AUDF with 2 and 1
					audf = self.audf[1] * 256 + self.audf[0]
					# TODO: verify this on an emulator
					if self.clock1mhz: # If 1 is using the MHz clock, so will this
						clock = self.CLOCK_MHz
						m = 4
				else:
					pass
			# Do same for 3 and 4
			if ch == 3:
				if self.join4and3: # Channel 3 is disabled if in 16-bit mode
					return 0
				else: # If not joined with channel 4
					if self.clock3mhz: # We modify the clock, if necessary
						clock = self.CLOCK_MHz
						m = 7 # Modifier is 7
			if ch == 4:
				if self.join4and3: # Channel 4 is used for sound in 16-bit mode
					# Create 16-bit AUDF with 4 and 3
					audf = self.audf[3] * 256 + self.audf[2]
					if self.clock3mhz: # If 3 is using the MHz clock, so will this (again, verify?)
						clock = self.CLOCK_MHz
						m = 4
				else:
					pass
		
		# Compute final frequency divider (for a half wave)
		N = (audf + m)
		
		# This isn't enough to get us the proper frequency, because N is actually the desired
		# period of repetition of half a waveform we're playing, generated by the polynonomial
		# counters. As such, different poly combinations will result in longer or shorter periods.
		# We must account for this. The periods of the polys are:
		T_POLY4 = 15
		T_POLY5 = 31
		T_POLY9 = 511
		T_POLY17 = 131071
		T_PURE = 2
		
		# TODO: Actually figure out how to map these noises to something more useful (percussions or
		# seashore/helicopter/drum instruments, etc)
		# 17 and 9 polys are basically noise, no need to count it properly as they have no
		# discernible frequency. For now, we could assume some other period that maps most common
		# notes to the mid-range to be used later
		# T_POLY9 = 80
		# T_POLY17 = 80
		# But that's not really useful, is it?
		
		# The periods of the 8 polys, given by the specifications (slightly modified)
		periods = [
			T_POLY17 * T_POLY5,    # 0=0b000	17 Bit poly + 5 Bit poly = Noise
			T_POLY5,               # 1=0b001	5 Bit poly = Rumble
			T_POLY4 * T_POLY5,     # 2=0b010	4 Bit poly + 5 Bit poly = Rumble
			T_POLY5,               # 3=0b011	5 Bit poly = Rumble
			T_POLY17,              # 4=0b100	17 Bit poly = Soft noise
			T_PURE,                # 5=0b101	Pure Tone
			T_POLY4,               # 6=0b110	4 Bit poly - Buzzing
			T_PURE                 # 7=0b111	Same as #5 (Not documented)
		]
		
		# If AUDCTl is set to use a 9-bit poly instead of 17-bit, we change it
		if self.poly17as9:
			periods[0] = T_POLY9 * T_POLY5
			periods[4] = T_POLY9
		
		# TODO: Handle 0-4 which is basically noise. What to do about the 5-bit though?
		
		# Now, we multiply N by these periods to obtain the proper note corrected for timbre
		N *= periods[self.poly[ch-1]]
		
		# And return the final frequency
		return clock / N
	
	# Get the nearest (piano) note on a channel given its tone frequency
	# Frequencies are exponential, so the note number is logarithmic
	# f = 27.5 * 2^(n/12) Hz   <---> n = log2(f / 27.5)
	# Here, we defined n=0 -> A0, as in the piano. This is MIDI note 21
	def getNote(self, ch):
		assert ch > 0
		freq = self.getFrequency(ch)
		assert freq >= 0
		
		if freq <= 0: # Probably due to volctrl set or something else
			return [None,None,0] # No note
		
		# Since the frequency division method is imprecise, we must figure out the proper
		# note heuristically. The real note we want is the standard note closest in frequency.
		n = math.log(freq / 27.5, 2)*12 # fractional note number (as in piano keys)
		# Since the frequency is exponential and not linear we must try both sides, low and high,
		# to see which is closer
		lf, hf = 27.5*math.pow(2, math.floor(n)/12), 27.5*math.pow(2, math.ceil(n)/12)
		# We use whichever note number gets us closest to a standard frequency
		if abs(freq-lf) < abs(freq-hf):
			note = math.floor(n)
		else:
			note = math.ceil(n)
		
		if note < -21 or note > 234 and self.vol[ch-1] > 0:
			if DEBUG:
				print("\nWarning: Couldn't handle audible note '%d' of POKEY %d, channel %d" % (
					note, self.number, ch
				))
				errstate = dict()
				errstate['audf']		= list(self.audf)
				errstate['freqs']		= list([
												self.getFrequency(1), self.getFrequency(2),
												self.getFrequency(3), self.getFrequency(4)
											])
				errstate['vol']			= list(self.vol)
				errstate['volctrl']		= list(self.volctrl)
				errstate['poly']		= list(self.poly)
				errstate['use15khz']	= self.use15khz
				errstate['highpass2w4']	= self.highpass2w4
				errstate['highpass1w3']	= self.highpass1w3
				errstate['join4and3']	= self.join4and3
				errstate['join2and1']	= self.join2and1
				errstate['clock3mhz']	= self.clock3mhz
				errstate['clock1mhz']	= self.clock1mhz
				errstate['poly17as9']	= self.poly17as9
				print("POKEY state:", errstate)
			return [None, None, 0]
		
		# TODO: export human-readable note names?
		notename = NOTES[note % 12] + "%d" % ((note + 9) // 12) # human-readable name
		return (note, notename, freq) # (piano key, note name, frequency)
	
	# Get current POKEY state in a human-readable form
	@property
	def state(self):
		# Update current state
		self._state['audf']		= list(self.audf)
		self._state['note']		= list([
										self.getNote(1)[0], self.getNote(2)[0],
										self.getNote(3)[0], self.getNote(4)[0]
									])
		self._state['vol']			= list(self.vol)
		self._state['volctrl']		= list(self.volctrl)
		self._state['poly']			= list(self.poly)
		self._state['use15khz']		= self.use15khz
		self._state['highpass2w4']	= self.highpass2w4
		self._state['highpass1w3']	= self.highpass1w3
		self._state['join4and3']	= self.join4and3
		self._state['join2and1']	= self.join2and1
		self._state['clock3mhz']	= self.clock3mhz
		self._state['clock1mhz']	= self.clock1mhz
		self._state['poly17as9']	= self.poly17as9
		
		return self._state


# Basic MIDI writing class
class MIDI(object):
	def __init__(self, timebase=DEFAULT_TIMEBASE, tempo=DEFAULT_TEMPO):
		self.timebase = round(timebase/24)*24 # lock to multiples of 24, as is standard
		self.tempo = tempo
		self.tracks = []
		self.numNotes = [] # number of notes in each track
		
		self.timeOffset = 0 # time to subtract from every sound (note/ctrl) event, to remove silence
		self.scaleFactor = 1.0 # scale times by this factor, to adjust for a known tempo
		
		# Initialize conductor track, initially blank
		self.newTrack()
	
	# Writes variable length number, as per MIDI standard
	def variableLengthNumber(self, num):
		assert num >= 0
		lst = struct.pack("=B",num & 0x7f)
		while 1:
			num = num >> 7
			if num:
				lst = struct.pack("=B",(num & 0x7f) | 0x80) + lst
			else:
				return lst
	
	# Create a new MIDI track
	def newTrack(self):
		self.tracks.append(dict())
		self.numNotes.append(0)
		return len(self.tracks)-1
	
	# Add event to a MIDI track
	# time is given in seconds, data is a list with event name and data
	# ['Event name', data...]
	# We use a "Raw" event to write arbitrary data, instead of implementing all the useless events
	def addEvent(self, track, time, data):
		assert 0 <= track and track < len(self.tracks)
		ticks = self.timeToTicks(time)
		assert ticks >= 0
		if ticks not in self.tracks[track]:
			self.tracks[track][ticks] = []
		self.tracks[track][ticks].append( data )
	
	# Add meta track name
	def setTrackName(self, track, name):
		self.addEvent(track, 0, [
			'Raw', b"\xFF\x03" + self.variableLengthNumber(len(name.encode())) + name.encode()
		])
	
	# Add meta instrument name
	def setInstrumentName(self, track, name):
		self.addEvent(track, 0, [
			'Raw', b"\xFF\x04" + self.variableLengthNumber(len(name.encode())) + name.encode()
		])
	
	# Add a Note On event
	def noteOn(self, track, time, channel, key, velocity):
		velocity = min(127,max(0,int(velocity))) # Force 0-127 range
		time -= self.timeOffset # Remove offset, if any
		self.addEvent( track, time, [
			'On', channel, key, velocity
		])
		self.numNotes[track] += 1
	
	# Add a Note Off event
	def noteOff(self, track, time, channel, key):
		# Offs can be (and are usually) treated as On events with zero velocity
		self.noteOn(track, time, channel, key, 0)
	
	# Add a Controller Change event
	def ctrlChange(self, track, time, channel, ctrl, value):
		time -= self.timeOffset
		self.addEvent( track, time, [
			'Ctrl', channel, ctrl, value
		])
		
	# Add a Program (Instrument) Change event
	def progChange(self, track, time, channel, inst):
		time -= self.timeOffset
		self.addEvent( track, time, [
			'Prog', channel, inst
		])
	
	# Convert time in seconds to MIDI ticks
	def timeToTicks(self, time):
		return round( time * self.timebase * self.scaleFactor )
	
	# Save MIDI to a path
	def save(self, path):
		# Assemble conductor track, track 0, which must contain only meta events
		self.tracks[0] = dict()
		self.addEvent(0, 0, [
			'Raw', b"\xFF\x51\x03" + struct.pack(">L",int(60e6/self.tempo))[1:]
		])
		
		# Watermark
		self.setTrackName(
			0,
			"Converted with POKEY2MIDI v%s by LucasVB (http://1ucasvb.com/)" % VERSION
		) 
		
		# Only write non-empty tracks
		tracks = [self.tracks[0]] + [
			track for t, track in enumerate(self.tracks) if self.numNotes[t] > 0
		]
		
		# Write MIDI file to disk
		with open(path, "wb") as mf:
			mf.write(b"MThd") # header
			mf.write(struct.pack(">L", 6)) # header length
			mf.write(struct.pack(">H", 1)) # MIDI format 1 (multiple tracks, single sequence)
			mf.write(struct.pack(">H", len(tracks))) # num tracks + conductor track
			mf.write(struct.pack(">H", self.timebase)) # timebase
			for track in tracks:
				mf.write(b"MTrk") # track header
				mf.write(struct.pack(">L", 0)) # track length (will overwrite later, futher down)
				trkpos = mf.tell() # save pos for the beginning of track data, we'll use it later
				# // begin track data
				
				ltick = 0 # last tick
				ticks = sorted(track.keys())
				for tick in ticks:
					first = True # first event at this tick?
					for ev in track[tick]:
						if first: # If first event at this tick, we use delta and update ltime
							delta = tick - ltick
							first = False
						else: # Next events at this tick are simultaneous, so their deltas are zero
							delta = 0
						if ev[0] == "Raw":
							mf.write(self.variableLengthNumber(delta))
							mf.write(ev[1])
						if ev[0] == "On":
							mf.write(self.variableLengthNumber(delta))
							channel, key, velocity = ev[1:]
							mf.write(struct.pack("=B", 0x90 + channel))
							mf.write(struct.pack("=B", key))
							mf.write(struct.pack("=B", velocity))
						if ev[0] == "Ctrl":
							mf.write(self.variableLengthNumber(delta))
							channel, ctrl, val = ev[1:]
							mf.write(struct.pack("=B", 0xB0 + channel))
							mf.write(struct.pack("=B", ctrl))
							mf.write(struct.pack("=B", val))
						if ev[0] == "Prog":
							mf.write(self.variableLengthNumber(delta))
							channel, inst = ev[1:]
							mf.write(struct.pack("=B", 0xC0 + channel))
							mf.write(struct.pack("=B", inst))
					ltick = tick
					
				# // end generated track data
				mf.write(b"\x00\xFF\x2F\x00") # Obligatory End of Track marker
				# find total track size
				trklen = mf.tell() - trkpos # find total chunk size
				mf.seek(trkpos - 4) # go back to track length data
				mf.write(struct.pack(">L", trklen)) # overwrite proper length
				mf.seek(trkpos + trklen) # go back to end of data chunk


# Song management class
# This is the class that handles POKEY states as music, to later convert to MIDI
class Song(object):
	def __init__(self, converter):
		self.pokeys = []
		self.states = dict()
		self.music = dict()
		self.converter = converter
	
	@property
	def numPOKEY(self):
		return len(self.pokeys)
	
	# Initializes POKEYs
	def initPOKEY(self, n):
		self.pokeys = [POKEY(pn) for pn in range(n)]
		print( "%d POKEY found" % n )
	
	# Add a new POKEY state
	def addState(self, t, data):
		self.states[t] = data
	
	# Compile POKEY states into timed note information and so on
	def compile(self):
		music = dict()
		voices = set() # voices are different timbres at each channel and POKEY
		features = set() # AUDCTL features used
		earliest_sound = 1e6 # just some big number, simplifies logic
		total = len(self.states)
		lpc = None # last percentage
		print("Compiling song... ", end="")
		for n, t in enumerate(self.states):
			data = self.states[t]
			music[t] = []
			for pn, pokey in enumerate(self.pokeys):
				pokey.write(data[pn]) # write data to POKEY
				features = features | pokey.AUDCTLFeatures # add which AUDCTL features were used
				state = pokey.state.copy() # copy POKEY states dict
				# Append music data
				music[t].append({
					'poly': state['poly'],
					'note': state['note'],
					'vol': state['vol']
				})
				for ch in range(4):
					# add voice used
					voices.add( self.converter.voice(pn, ch, state['poly'][ch]) )
					# if this channel is producing sound
					if not state['volctrl'][ch] and \
						state['note'][ch] is not None \
						and state['vol'][ch] > 0:
							# and if this sound is earlier than the known earliest sound
							if t < earliest_sound:
								earliest_sound = t # update earliest known sound
			pc = int((n+1) / total * 100) # current percentage
			if (pc % 10) == 0 and pc != lpc: # print multiples of 10%
				print( "%d%% " % pc, end="" )
				lpc = pc
		
		print("Done!")
		voices = sorted(voices) # update voices from set to ordered list
		# Save results to memory
		self.music = music
		self.voices = voices
		self.times = list(sorted(music.keys()))
		self.earliestSound = earliest_sound
		# Display AUDCTL features used
		print( "AUDCTL features used:", ", ".join(list(features)) if len(features) else "None" )
		

# Main POKEY2MIDI program class, which handles everything
class Converter(object):
	
	def __init__(self):
		# Set default options
		
		# Always retrigger notes, regardless of changes
		self.AlwaysRetrigger = False
		# Merge decaying notes into a single MIDI note
		self.MergeDecays = True
		# Boost note velocity (increases loudness)
		self.BoostVelocity = 1.0
		# Split different polynomial counter settings for channels as separate instrument tracks
		self.SplitPolyAsTracks = True
		# Trim initial silence (first note plays immediately)
		self.TrimSilence = True
		# Force a specific tempo
		self.ForceTempo = None
		# Force a specific timebase
		self.ForceTimebase = None
		# Don't use note velocities for note loudness. Use the channel volume instead.
		# TODO: Fix potential issue with multiple tracks on same channel
		self.UseChannelVolume = False
		# Assign MIDI instruments to MIDI channels to emulate the original POKEY sound
		self.UseInstruments = True
	
	# Get a string tag for a given voice
	# A voice exist for each instrument for each channel for each POKEY
	# If We are not splitting different polynomial counters as instruments, the channels are the
	# voices
	def voice(self, pn, ch, poly):
		if self.SplitPolyAsTracks:
			return "%d %s %s" % (pn, ch, poly)
		else:
			return "%d %s" % (pn, ch)
	
	# Main conversion function
	def convert(self, file, output):
		
		if not os.path.isfile(file):
			print("File \"%s\" doesn't exist" % self.file)
			return
		self.file = file
		
		setup = False # If the basic information is setup or not, set to True after firt line read
		song = Song(self) #  The song object which will handle things
		
		# Read raw POKEY data into song
		print("Opening \"%s\"" % self.file)
		with open(self.file) as fin:
			print("Reading POKEY data... ", end="")
			for l in fin:
				l = l.replace('\n','').replace('\r','') # get rid of EOl characters
				
				if l == "NO RESPONSE": # Stop at end of POKEY data, if any (for finite songs)
					break
				
				if ":" in l: # default asapscan format detected
					print("\nERROR")
					print("POKEY2MIDI requires a slightly modified version of asapscan to work.")
					print("Please, see instructions at: https://github.com/1ucasvb/pokey2midi")
					exit()
				else:
					# Extract timestamp from the rest
					tokens = l.split(" ")
					t, data = float(tokens[0]), (" ".join(tokens[1:])).split("|")
				
				if not setup: # Setup metadata if we just parsed the first line
					numPOKEY = len(data)
					# Assume zeroed out registers initially
					last_data = [bytes.fromhex("00"*9)] * numPOKEY
					# Initialize pokeys
					song.initPOKEY(numPOKEY)
					setup = True
				
				# AUDF1 AUDC1 AUDF2 AUDC2 AUDF3 AUDC3 AUDF4 AUDC4 AUDCTL
				for n in range(numPOKEY): # convert to raw data
					data[n] = bytes.fromhex(data[n])
				
				# asapscan outputs one line per frame. In most cases, many lines are identical
				# Since duplicate lines are meaningless (only changes in POKEY state are useful
				# for detecting musical content), we ignore duplicate lines.
				
				# If POKEY data hasn't changed, we don't need to do anything
				if data == last_data: 
					continue
				
				last_data = data # Update previous state
				
				# Write song data (the state changes)
				song.addState( t, data )
		
		# Compile song data into notes
		song.compile()
		
		# Initialize MIDI
		midi = MIDI()
		
		# If we want to trim silences, we set the MIDI time offset to the earliest sound
		if self.TrimSilence:
			midi.timeOffset = song.earliestSound
			
		# If we want to force a known tempo, we change the MIDI tempo and the scale factor
		if self.ForceTempo is not None:
			midi.scaleFactor =  self.ForceTempo / 60.0
			midi.tempo = self.ForceTempo
		
		# If we want to force a timebase, we do it now
		if self.ForceTimebase is not None:
			midi.timebase = self.ForceTimebase
		
		# Each voice is a track
		for v in song.voices:
			mt = midi.newTrack()
			v = v.split(" ")
			midi.setTrackName( mt, "POKEY %s, Channel %s" % (v[0], int(v[1])+1) )
			# If each poly is in a separate track, we specify it on the instrument field
			if self.SplitPolyAsTracks:
				midi.setInstrumentName( mt, "Poly %s" % v[2] )
		
		# Current active notes for each channel
		active_note = [ [None]*4 for pn in range(song.numPOKEY) ]
		
		# We begin assembling the MIDI data
		print("Assembling MIDI file...")
		for nt, t in enumerate(song.times):
			for pn in range(song.numPOKEY):
				state = song.music[t][pn]
				for ch in range(4):
					
					voice = self.voice(pn, ch, state['poly'][ch])
					
					midi_track = song.voices.index(voice) + 1 # +1 due to conductor track
					midi_ch = pn*4 + ch
					
					if state['note'][ch] is None:
						midi_note = None
					else:
						# 21 is A0, which we're using at note 0 internally (as in the piano)
						midi_note = state['note'][ch] + 21
					
					# In MIDI jargon, "note velocity" = loudness
					
					# 4-bit volume given in the melody
					vol = state['vol'][ch]
					
					# Volume used in MIDI (note velocity), with boost and 0-127 range
					midi_vol = max(0,min(127,int(state['vol'][ch] / 15 * 127 * self.BoostVelocity)))
					
					# If we are using channel volumes for the volume data, as opposed to note
					# velocity, then we always play the loudest note, but control the effect with
					# the channel volume
					if self.UseChannelVolume: 
						ch_vol = midi_vol
						midi_vol = 127
					
					# If there's a note being played in the current channel of the current POKEY
					if active_note[pn][ch] is not None:
						kill = False
						
						if self.AlwaysRetrigger:
							# If AlwaysRetrigger is set, the previous note is always killed
							kill = True
						else:
							# Otherwise, we use different heuristics to merge notes
							
							# For volume changes
							if self.UseChannelVolume:
								# If we're using the channel volume, we update it if changed, 
								# instead of sending a new note. No need to kill.
								if active_note[pn][ch]['vol'] != vol and vol > 0:
									midi.ctrlChange(midi_track, t, midi_ch, 0x07, ch_vol)
							else:
								# Otherwise, we kill if the note is rising. This usually means
								# a re-trigger of the note in the actual music.
								# Decaying sounds are usually used for decaying envelopes, so
								# the natural decay of the MIDI note should work fine.
								# Of course, only if we have set MergeDecays to True
								if self.MergeDecays and active_note[pn][ch]['vol'] < vol: 
									kill = True
								# Note, however, that if a song uses a ramping up attack, this
								# just results in many quick notes rising up in volume, which
								# is usually fine.
							
							# For note changes
							# If new note is different, always cancel old note and retrigger
							if active_note[pn][ch]['note'] != midi_note:
								kill = True
							
							# Kill if timbre changed while keeping the note fixed
							# This is usually used for percussive effects
							# Disabled for now
							# TODO: verify when this happens to know exactly how to handle it
							# if active_note[pn][ch]['voice'] != voice:
								# kill = True
							
							# Always kill if current volume is zero
							if vol == 0:
								kill = True
						
						# Send the NoteOff for the current note if marked to kill it
						if kill:
							midi.noteOff(
								active_note[pn][ch]['track'],
								t,
								midi_ch,
								active_note[pn][ch]['note']
							)
							active_note[pn][ch] = None # Mark as free to be used
					
					# If no active note, a new current note exists and volume is non-zero, we have
					# a new note being played
					if active_note[pn][ch] is None and midi_note is not None and vol > 0:
						# If we are using the channel volume, we update it here before the note
						if self.UseChannelVolume:
							midi.ctrlChange(midi_track, t, midi_ch, 0x07, ch_vol)
						if self.UseInstruments:
							midi.progChange(
								midi_track, t, midi_ch,
								POLY_INSTRUMENT[state['poly'][ch]]
							)
							
							
						# Add Note On event
						midi.noteOn(midi_track, t, midi_ch, midi_note, midi_vol) 
						active_note[pn][ch] = {
							'note': midi_note,
							'vol': vol,
							'track': midi_track,
							'voice': voice
						} # Update active note
		
		# Once the track is done
		# Kill all leftover notes after a small offset
		offset = 1/50 # in seconds
		for pn in range(song.numPOKEY):
			for ch in range(4):
				voice = self.voice(pn, ch, state['poly'][ch])
				midi_track = song.voices.index(voice) + 1
				if active_note[pn][ch] is not None:
					midi.noteOff(
						active_note[pn][ch]['track'],
						t + offset,
						midi_ch,
						active_note[pn][ch]['note']
					)
		
		print("Saving MIDI file at \"%s\"" % output)
		midi.save(output)
		

# If running by itself, handle command line options
if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="POKEY2MIDI v%s by LucasVB (http://1ucasvb.com)\nConverts textual POKEY dumps from asapscan into MIDI files." % VERSION)
	parser.add_argument('-all', action='store_true', help="Use all notes by always retriggering. Useful for when notes are being missed. Overrides note merging.")
	parser.add_argument('-notrim', action='store_false', help="Do not trim initial silence, which happens by default.")
	parser.add_argument('-nosplit', action='store_false', help="Do not split different polynomial counter settings for channels as separate instrument tracks, which happens by default.")
	parser.add_argument('-nomerge', action='store_false', help="Do not merge volume decays into a single MIDI note, which happens by default. Ignored if -all is used.")
	parser.add_argument('-usevol', action='store_true', help="Use MIDI channel volume instead of note velocity. This is similar to how it happens in the actual chip.")
	parser.add_argument('-useinst', action='store_true', help="Assign MIDI instruments to emulate the original POKEY sound.")
	parser.add_argument('-boost', metavar='factor', nargs=1, type=float, help="Multiply note velocities by a factor. Useful if MIDI is too quiet. Use a large number (> 16) without -usevol to make all notes have the same max loudness.")
	parser.add_argument('-bpm', nargs=1, type=float, help="Assume a given tempo in beats per minute (BPM), as precisely as you want. Default is %d. If the song's BPM is known precisely, this option makes the MIDI notes align with the beats, which makes using the MIDI in other places much easier. Doesn't work if the song has a dynamic tempo." % DEFAULT_TEMPO)
	parser.add_argument('-timebase', nargs=1, type=int, help="Force a given MIDI timebase, the number of ticks in a beat (quarter note). Default is %d." % DEFAULT_TIMEBASE)
	parser.add_argument('input', metavar='input_file', type=str, nargs=1, help="Input POKEY dump text file.")
	parser.add_argument('output', metavar='output_file', type=str, nargs="?", help="MIDI output file. If not specified, will output to the same path, with a '.mid' extension")
	args = parser.parse_args()
	
	converter = Converter()
	
	converter.AlwaysRetrigger = args.all
	converter.MergeDecays = args.nomerge
	converter.TrimSilence = args.notrim
	converter.SplitPolyAsTracks = args.nosplit
	converter.UseChannelVolume = args.usevol
	converter.UseInstruments = args.useinst
	if args.boost is not None:
		converter.BoostVelocity = args.boost[0]
	if args.bpm is not None:
		converter.ForceTempo = args.bpm[0]
	if args.timebase is not None:
		converter.ForceTimebase = args.timebase[0]
	
	input = args.input[0]
	
	if args.output is not None:
		output = args.output[0]
	else:
		output = os.path.splitext(os.path.realpath(input))[0] + ".mid"
	
	converter.convert(input, output)

# EOF
