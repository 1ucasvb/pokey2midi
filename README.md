# POKEY2MIDI
POKEY2MIDI is a tool (using Python 3) to convert POKEY register dumps from Atari SAP files into MIDI music files.

The main motivation for writing this program was for me to transcribe Atari SAP music as MIDI to be later imported in other music composition programs.

As such, I needed a tool that was accurate, and which also separated potential instruments/voices and aligned MIDI notes to the musical bars.

---
# Features

POKEY2MIDI has many options you can toggle on or off to customize the output. These include:

* Can merge decaying notes as a single MIDI note.
* Maps POKEY channel volume either to note velocity (loudness of each note) or MIDI channel volume.
* Splits notes per channel of each POKEY, or even per poly per channel per POKEY.
* Trims initial silence so notes are aligned to MIDI bars.
* Map MIDI instruments to each poly setting, or just leave it unmapped.
* No pitch bend, because pitch bends suck!
* Boost loudness of notes.
* Save MIDIs with a specific max duration.
* Use a known song tempo to precisely align MIDI events to the bars, making the transcription more useful to use elsewhere. Doesn't affect playback perceptual speed.
* Also includes a simple (but usually effective) algorithm to detect the precise tempo of songs. Many possibilities are suggested, and one of them is usually right. It's often easy to tell which one, especially if used in conjunction with a [a tap-based bpm detector](https://www.google.com/search?hl=en&q=bpm+tap+online). However, this requires a modification of asapscan (see below).

Noise and special effects (highpass filters) are not yet handled, but will be included at some point. The idea is to map noises into percussion maps.

---
# Instructions

POKEY register dumps can be created from Atari SAP files by using `asapscan`, available on the ASAP project (http://asap.sourceforge.net).

Just run `asapscan` with the `-d` command, and save the contents into a text file. Like so:

    asapscan -s N -d song.sap > song.txt

Where `N` is the subsong number (starting from 0), if any. Otherwise, this setting can be omitted. The above should work on both Windows and Linux.

Once the text file is ready, just run POKEY2MIDI on it as per instructions.

---
# Advanced stuff

However, even though the normal `asapscan` will do fine, it is still limited as it is. You'll have to recompile it with a small modification to get more out of it. 

Note: the compilation of ASAP requires Cito (http://cito.sourceforge.net)

The original version of `asapscan` only outputs timestamps with 2 decimal digits of precision, which is insufficient for some purposes. For instance, finding exact song tempos (using `--findbpm`) to align notes properly (with `--bpm`) is impossible without more precision. The notes quickly drift out of alignment.

The relevant lines to change are found in `asapscan.c`:

    if (dump) {
    	printf("%6.2f: ", (double) frame * CYCLES_PER_FRAME / MAIN_CLOCK);
    	print_pokey(&asap->pokeys.basePokey);
    	if (asap->moduleInfo.channels == 2) {
    		printf("  |  ");
    		print_pokey(&asap->pokeys.extraPokey);
    	}
    	printf("\n");
    }

Change that `"%6.2f: "` in the first `printf` to `"%6.6f "`, which will now output 6 digits after the decimal:

    printf("%6.6f ", (double) frame * CYCLES_PER_FRAME / MAIN_CLOCK);

(Might as well get rid of that pesky colon!)

Compile this and you're good to go! Now you can use `--findbpm`. A pre-compiled version of this modified `asapscan` for Microsoft Windows is in the `bin` directory.

---
# Samples

Sample MIDI outputs are given in the `samples` directory, along with the dumps and original SAP files for comparison.

The samples were created using the `--useinst` and `--usevol` setting, which results in MIDIs resembling the originals more closely. Check them out and compare with the originals!

---
# Notes  

This is a work in progress, and some POKEY features are still not properly handled. In particular, I haven't yet figured a good and comprehensive way of dealing with the 0-4 (000 to 010) AUDC polynomial settings, which are used to produce various types of noise.

The white/pink-noise-like polys 1=001 and 4=100 are being ignored for now. Polys 0=000, 2=010 and 3=011 all produce tones at high enough frequencies, but are almost always used for low rumbling sound effects. I'm still figuring out what to do with these.

Some note frequencies are also not being mapped properly to anything useful, especially when songs use 16-bit or the 1.79 MHz clock. I opted to omit these for now until I figure what to do as well.

---

Some tags to help others looking for this program: pokey2mid, sap2mid, sap2midi, POKEY to MID, SAP to MIDI, SAP to MID
