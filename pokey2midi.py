'''
	POKEY2MIDI v0.84
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
		
		Option to ignore all volume information and merge notes maximally?
'''

import os
import re
import bz2
import math
import struct
import argparse
import mimetypes

# Constants
VERSION				= "0.84"
NTSC				= 0
PAL					= 1
NOTES				= ['A','A#','B','C','C#','D','D#','E','F','F#','G','G#']
DT_NTSC				= 262 * 114 / 1789772.5 # time between NTSC frames
DT_PAL				= 312 * 114 / 1773447.0 # time between PAL frames
NTSC_TAG			= "%.02f" % (2*DT_NTSC) # "0.03"
FPS_NTSC			= 59.94
FPS_PAL				= 50

# Settings
DEFAULT_TIMEBASE 	= 480
DEFAULT_TEMPO 		= 60
# Precision for the tempo detector during quantizing, higher is better
BPM_PRECISION		= 10/(DT_NTSC*DT_PAL)
BPM_THRESHOLD		= 20 # Minimum number of intervals to run tempo detector

# Debug contants
ENABLE_16BIT		= True # Enable 16bit?
DEBUG				= False # Internal debug
DEBUG_POLYS			= False # Also write non-tonal polys (0-4) notes as given by AUDF

# TODO: find the rest
# 0 = white noise, cymbal?
# 2 = low buzz when high freq, helicopter for low freq?
# 4 = pink noise, seashore?
# Use negative values for percussion map? (MIDI channel 9)
POLY_INSTRUMENT		= [0,87,0,87,0,80,87,80]

# Human-readable POKEY state and other goodies
class POKEY(object):
	def __init__(self, number, mode):
		self.mode = mode
		# Per-channel data
		self.audf			= [0,0,0,0] # channel frequency data
		self.vol			= [0,0,0,0] # channel volumes
		self.volctrl		= [0,0,0,0] # volume-only mode (used for PCM digital audio)
		self.poly			= [0,0,0,0] # channel polynomial counter data
		# AUDCTL flags
		self.use15khz		= False
		self.highpass2w4	= False
		self.highpass1w3	= False
		self.join4and3		= False
		self.join2and1		= False
		self.clock3mhz		= False
		self.clock1mhz		= False
		self.poly17as9		= False
		
		self._state		= dict() # internal state
		self.number		= number # POKEY number
	
		
	# The availalbe clock frquencies in Hz
	@property
	def CLOCK_MHz(self):
		return 1789772.5 if self.mode == NTSC else 1773447.0
	
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
		
		# Debug currently unhandled poly settings
		# Emulate frequencies so that the MIDI note number is the AUDF value for the channel
		if DEBUG_POLYS and self.poly[ch-1] not in [5,6,7]:
			return 27.5 * math.pow(2,(self.audf[ch-1] - 21)/12)
		
		# TODO: For now only, we'll only handle possibly tonal sounds.
		# The noisier ones will have to be handled in a better way.
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
		# notes to the mid-range to be used later?
		# But that's not really useful, is it?
		
		# The periods of the 8 polys, given by the specifications (slightly modified)
		# TODO: Use emulator and figure out the exact frequencies obtained
		# It may be that the lowest bit being set adds a factor of 2 everytime, with T_PURE = 1
		periods = [
			T_POLY17 * T_POLY5,    # 0=0b000	17 Bit poly + 5 Bit poly = White noise
			T_POLY5,               # 1=0b001	5 Bit poly = Low tone
			T_POLY4 * T_POLY5,     # 2=0b010	4 Bit poly + 5 Bit poly = Low buzz tone
			T_POLY5,               # 3=0b011	5 Bit poly = Low tone (same as #1)
			T_POLY17,              # 4=0b100	17 Bit poly = Soft noise
			T_PURE,                # 5=0b101	Pure Tone
			T_POLY4,               # 6=0b110	4 Bit poly - High buzz
			T_PURE                 # 7=0b111	Same as #5 (Not documented)
		]
		
		# If AUDCTL is set to use a 9-bit poly instead of 17-bit, we change it
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
	def initPOKEY(self, n, mode):
		self.pokeys = [POKEY(pn, mode) for pn in range(n)]
	
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
		print("Compiling song...")
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
				# print( "%d%% " % pc, end="" )
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
		# Time limit (do not convert past this point)
		self.TimeLimit = None
		# Split different polynomial counter settings for channels as separate instrument tracks
		self.SplitPolyAsTracks = True
		# Use short track names
		self.ShortTrackNames = False
		# Trim initial silence (first note plays immediately)
		self.TrimSilence = True
		# Force a specific tempo
		self.ForceTempo = None
		# Attempt to detect song tempo with a simple algorithm
		# Display the results aftewards
		self.DetectTempo = False
		# Force a specific timebase
		self.ForceTimebase = None
		# Don't use note velocities for note loudness. Use the channel volume instead.
		# TODO: Fix potential issue with multiple tracks on same channel
		self.UseChannelVolume = False
		# Assign MIDI instruments to MIDI channels to emulate the original POKEY sound
		self.UseInstruments = False
		# Custom instruments to use
		self.CustomInstruments = None
	
	# Get a string tag for a given voice
	# A voice exists for each instrument for each channel for each POKEY
	# If we are not splitting different polynomial counters as instruments, the channels are the
	# voices themselves
	def voice(self, pn, ch, poly):
		if self.SplitPolyAsTracks:
			return "%d %s %s" % (pn, ch+1, poly)
		else:
			return "%d %s" % (pn, ch+1)
	
	# Main conversion function
	def convert(self, file, output):
		
		if not os.path.isfile(file):
			print("File \"%s\" doesn't exist" % file)
			return
		self.file = file
		
		
		song = Song(self) # The song object which will handle things
		
		print("="*20 + "[ POKEY2MIDI v%s ]"%VERSION + "="*20)
		print("Opening \"%s\"" % self.file)
		
		# Detect MIME type
		mime = mimetypes.guess_type(self.file)
		if mime[0] != "text/plain" or mime[1] is not None and mime[1] != "bzip2":
			print("ERROR\nIncorrect input format.")
			exit()
		if mime[1] == "bzip2":
			handle = bz2.open(self.file, "rt")
		elif mime[1] == None:
			handle = open(self.file, "rt")
		
		with handle as fin:
			print("Reading POKEY data...")
			
			# Detect NTSC or PAL, skip to 3rd line where we can tell them apart
			for ln in range(3):
				l = fin.readline()
			
			if l[0][:-1] == NTSC_TAG:
				mode = NTSC
				dt = DT_NTSC # the correct time between frames for NTSC
			else:
				mode = PAL
				dt = DT_PAL # the correct time between frames for PAL
			
			# Reset reading pointer
			fin.seek(0)
			
			ln = 0 # line number
			for l in fin:
				l = re.sub(r"[\n\r\:]", "", l.strip()) # get rid of EOL characters and colon
				l = re.sub(r"\s+", " ", l) # get rid of extra spaces
				if l == "NO RESPONSE": # Stop at end of POKEY data, if any (for finite songs)
					break
				
				# Extract timestamp from the rest
				tokens = l.split(" ")
				try:
					if len(tokens) != 10 and len(tokens) != 20:
						raise
					data = (" ".join(tokens[1:])).split("|")
				except:
					print("ERROR\nIncorrect input format.")
					exit()
				
				if ln == 0: # Setup metadata if we just parsed the first line
					numPOKEY = len(data)
					# Assume zeroed out registers initially
					last_data = [bytes.fromhex("00"*9)] * numPOKEY
					print(
						("Mode: Mono" if numPOKEY == 1 else "Stereo") + ", " + \
						("NTSC (%.2f Hz)"%FPS_NTSC if mode == NTSC else "PAL (%.2f Hz)" % FPS_PAL)
					)
				
				# Compute timestamp by ourselves, for more precision
				t = ln*dt
				
				# Stop after a given time limit
				if self.TimeLimit is not None and t > self.TimeLimit:
					break
				
				# AUDF1 AUDC1 AUDF2 AUDC2 AUDF3 AUDC3 AUDF4 AUDC4 AUDCTL
				for n in range(numPOKEY): # convert to raw data
					data[n] = bytes.fromhex(data[n])
				
				ln += 1 # increase line number
				
				# asapscan outputs one line per frame. In many cases, lines are identical
				# Since duplicate lines are meaningless (only changes in POKEY state are useful
				# for detecting musical content), we ignore duplicate lines.
				
				# If POKEY data hasn't changed, we don't need to do anything
				if data == last_data: 
					continue
				
				last_data = data # Update previous state
				
				# Write song data (the state changes)
				song.addState( t, data )
		
		# Initialize POKEYs
		song.initPOKEY(numPOKEY, mode)
		
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
			# If each poly is in a separate track or not, we specify it
			if self.SplitPolyAsTracks:
				fmt = "%s: Ch %s Poly %s" if self.ShortTrackNames else "POKEY %s Channel %s Poly %s"
				midi.setTrackName( mt, fmt % (v[0], int(v[1])+1, v[2]) )
				midi.setInstrumentName( mt, "Poly %s" % v[2] )
			else:
				fmt = "%s: Ch %s" if self.ShortTrackNames else "POKEY %s Channel %s"
				midi.setTrackName( mt, fmt % (v[0], int(v[1])+1) )
			
		# Current active notes for each channel
		active_note = [ [None]*4 for pn in range(song.numPOKEY) ]
		
		# If we're detecting tempo, initialize beat counter
		if self.DetectTempo:
			beats = dict()
		
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
					midi_vol = max(0,min(127,int(vol / 15 * 127 * self.BoostVelocity)))
					
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
								# But ONLY if it's the same note!
								if active_note[pn][ch]['note'] == midi_note and \
									active_note[pn][ch]['vol'] != vol and \
									vol > 0:
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
								# print("Voice changed", pn, ch)
								# exit()
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
						else:
							# Otherwise, update the note state
							active_note[pn][ch] = {
								'note': midi_note,
								'vol': vol,
								'track': midi_track,
								'voice': voice
							}
					
					# If no active note, a new current note exists and volume is non-zero, we have
					# a new note being played
					if active_note[pn][ch] is None and midi_note is not None and vol > 0:
						# If we are using the channel volume, we update it here before the note
						if self.UseChannelVolume:
							midi.ctrlChange(midi_track, t, midi_ch, 0x07, ch_vol)
						if self.UseInstruments:
							if self.CustomInstruments:
								inst = self.CustomInstruments[state['poly'][ch]]
							else:
								inst = POLY_INSTRUMENT[state['poly'][ch]]
							midi.progChange(
								midi_track, t, midi_ch,
								inst
							)
						
						# If we are detecting tempo, we add the note-on times to per-voice beat
						# tracker, as long as the note is a low note (lower than Middle C)
						if self.DetectTempo and midi_note < 60: # 60 is Middle C
							if voice not in beats:
								beats[voice] = list()
							qt = round(t*BPM_PRECISION) # qt = quantized time
							beats[voice].append(qt)
						
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
		offset = dt # in seconds
		for pn in range(song.numPOKEY):
			for ch in range(4):
				voice = self.voice(pn, ch, state['poly'][ch])
				if voice not in song.voices:
					continue
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
		
		if self.DetectTempo:
			converter.detectTempo(beats, mode)
	
	# Tempo/bpm detection function
	# This is a VERY rudimentary algorithm, but it should work well enough for well-behaved songs
	def detectTempo(self, beats, mode):
		print("Attempting to detect song tempo...")
		
		if mode == NTSC:
			dt = DT_NTSC
			fps = FPS_NTSC
		else:
			dt = DT_PAL
			fps = FPS_PAL
		
		# We keep track of our best guesses on set
		guesses = set()
		
		for v in beats: # For each voice
			d = [] # we initialize a list of quantized time deltas (differences)
			
			# We populate the list with the spacings between consecutive notes on each voice
			for i in range(1,len(beats[v])):
				d.append(beats[v][i] - beats[v][i-1])
			
			# If the list is too short, we skip this voice
			if len(d) < BPM_THRESHOLD:
				continue
			
			d = list(sorted(d)) # We sort the found deltas
			
			# We'll find the central tendency by finding the median of these values
			# No need to average in the case of an even number of entries, we're not that precise
			d = d[len(d)//2]
			
			# We compute the bpm from the median interval between two notes for this voice
			bpm = 60 / (d / BPM_PRECISION)
			
			# If the bpm is potentially reasonable, we'll add it to our guesses
			if bpm >= 5 and bpm <= 650:
				guesses.add(bpm)
		
		
		# If there ARE guesses, let's work on them
		if len(guesses) > 0:
			suggestions = set() # list of reasonable suggestions
			fracs = [1,1/2,1/4,1/8,2,4,8,3/4,1/3,2/3,3,6,5/4,4/3] # list of reasonable fractions
			# We'll find all reasonable fractions of the potentially reasonable bpms found earlier
			for guess in guesses:
				for f in fracs:
					bpm = guess*f # suggested guess
					if bpm > 20 and bpm < 200: # is it "reasonable"? 
						qbpm = round(60 / (bpm * dt)) # quantize it to frames/beat
						suggestions.add(qbpm)
			
			# If there are reasonable suggestions
			if len(suggestions) > 0:
				# We display them
				print("Possible tempos (in bpm):")
				for c, s in enumerate(reversed(sorted(suggestions))):
					bpm = 60 / (dt * s)
					print("    %16.12f" % bpm, end="")
					if c % 4 == 3 or c == len(suggestions)-1:
						print("")
				print("Note: using high precision tempos with --bpm avoids notes drifting out of alignment.")
				return
		
		print("Couldn't guess any tempo. Sorry!")

# If running by itself, handle command line options
if __name__ == "__main__":
	parser = argparse.ArgumentParser(description="POKEY2MIDI v%s by LucasVB/1ucasvb (http://1ucasvb.com). Converts textual POKEY dumps from asapscan into MIDI files." % VERSION)
	parser.add_argument('--all', action='store_true', help="Use all notes by always retriggering. Useful for when notes are being missed. Overrides note merging.")
	parser.add_argument('--notrim', action='store_false', help="Do not trim initial silence, which happens by default.")
	parser.add_argument('--nosplit', action='store_false', help="Do not split different polynomial counter settings for channels as separate instrument tracks, which happens by default.")
	parser.add_argument('--nomerge', action='store_false', help="Do not merge volume decays into a single MIDI note, which happens by default. Ignored if --all is used.")
	parser.add_argument('--usevol', action='store_true', help="Use MIDI channel volume instead of note velocity. This is similar to how it happens in the actual chip.")
	parser.add_argument('--useinst', action='store_true', help="Assign predefined MIDI instruments to emulate the original POKEY sound. Also use --setinst if you wish to define different instruments yourself.")
	parser.add_argument('--short', action='store_true', help="Use shorter MIDI track names.")
	parser.add_argument('--setinst', metavar='n,n,n,n,n,n,n,n', nargs=1, type=str, help="Specify which General MIDI instruments to assign to each of the 8 poly settings. No spaces, n from 0 to 127. The last three are the most important for melody and default to: square wave=80, brass+lead=87, square wave=80.")
	parser.add_argument('--boost', metavar='factor', nargs=1, type=float, help="Multiply note velocities by a factor. Useful if MIDI is too quiet. Use a large number (> 16) to make all notes have the same max loudness (useful for killing off POKEY effects that don't translate well to MIDI).")
	parser.add_argument('--maxtime', metavar='time', nargs=1, type=float, help="By default, asapscan dumps 15 minutes (!) of POKEY data. Use this to ignore stuff after some point.")
	parser.add_argument('--bpm', nargs=1, type=float, help="Assume a given tempo in beats per minute (bpm), as precisely as you want. Default is %d. If the song's bpm is known precisely, this option makes the MIDI notes align with the beats, which makes using the MIDI in other places much easier. Doesn't work if the song has a dynamic tempo." % DEFAULT_TEMPO)
	parser.add_argument('--findbpm', action='store_true', help="Attempts to post-process the data to automatically detect tempo/bpm by using a simple algorithm. The best guesses are merely displayed after the conversion. Run again with one of these guesses as a parameter with --bpm to see if events aligned properly. Cannot be used with --all, but might work better with --usevol.")
	parser.add_argument('--timebase', nargs=1, type=int, help="Force a given MIDI timebase, the number of ticks in a beat (quarter note). Default is %d." % DEFAULT_TIMEBASE)
	parser.add_argument('input', metavar='input_file', type=str, nargs=1, help="Input POKEY dump text file.")
	parser.add_argument('output', metavar='output_file', type=str, nargs="?", help="MIDI output file. If not specified, will output to the same path, with a '.mid' extension")
	args = parser.parse_args()
	
	converter = Converter()
	
	converter.AlwaysRetrigger = args.all
	converter.MergeDecays = args.nomerge
	converter.TrimSilence = args.notrim
	converter.ShortTrackNames = args.short
	converter.SplitPolyAsTracks = args.nosplit
	converter.UseChannelVolume = args.usevol
	converter.UseInstruments = args.useinst
	converter.DetectTempo = args.findbpm
	if args.boost is not None:
		converter.BoostVelocity = args.boost[0]
	if args.maxtime is not None:
		converter.TimeLimit = args.maxtime[0]
	if args.bpm is not None:
		converter.ForceTempo = args.bpm[0]
	if args.timebase is not None:
		converter.ForceTimebase = args.timebase[0]
	if args.useinst and args.setinst is not None:
		insts = [min(127,max(0,int(i) if len(i) else 0)) for i in args.setinst[0].split(',')]
		insts += [0]*(8-len(insts))
		converter.CustomInstruments = insts
	
	input = args.input[0]
	
	if args.output is not None:
		output = args.output
	else:
		output = os.path.splitext(os.path.realpath(input))[0] + ".mid"
	
	if converter.DetectTempo and converter.AlwaysRetrigger:
		print("Warning: --findbpm detection is incompatible with --all. No tempo will be detected.")
		converter.DetectTempo = False
	
	converter.convert(input, output)

# EOF
