# POKEY2MIDI
POKEY2MIDI is a tool (using Python 3) to convert **POKEY register dumps** from Atari SAP files into MIDI music files. (It cannot convert SAP files directly into MIDI files.)

The main motivation for writing this program was for me to transcribe Atari SAP music as MIDI, to be later imported in other music composition programs. I wanted this to try my hand at orchestrating some Atari music. [You can hear some examples here](https://www.youtube.com/playlist?list=PLhN15Dz2BRan93isRGIoDycl-d8ux81Rq).

As such, I needed a tool that was accurate, and which also separated potential instruments/voices and aligned MIDI notes to the musical bars. This makes POKEY2MIDI's approach to transcribing MIDI files different than other "video game music" MIDI converters: slides are not translated to pitch bends, but as note retriggers.

---
# Features

POKEY2MIDI has many options you can toggle on or off to customize the output. These include:

* Can merge decaying notes as a single MIDI note. Volume information may also be ignored completely to extract only the note transitions.
* Maps POKEY channel volume either to note velocity (loudness of each note) or MIDI channel volume.
* Splits notes per channel of each POKEY, or even per poly per channel per POKEY. This allows you to easily pick apart the different "voices" and instrumentation used in the music.
* Trims initial silence so notes are aligned to MIDI bars.
* Maps MIDI instruments to each poly setting, or just leave it unmapped.
* No pitch bend, because pitch bends suck! It only makes it more difficult for transcribing.
* Boosts loudness of notes.
* Save MIDIs with a specific max duration.
* Use a known song tempo to precisely align MIDI events to the bars, making the transcription more useful to use elsewhere. Doesn't affect playback/perceptual speed, but it won't work for tracks that change tempo or use some irregular timing structure.
* Also includes a simple (but usually effective) algorithm to detect the precise tempo of songs. Many possibilities are suggested, and one of them is usually right. It's often easy to tell which one, especially if used in conjunction with a [tap-based bpm detector](https://www.google.com/search?hl=en&q=bpm+tap+online).

Noise and special effects (highpass filters) are not yet handled, but will be included at some point. The idea is to map noises into percussions eventually.

---
# Instructions

POKEY register dumps can be created from Atari SAP files by using `asapscan`, available on the ASAP project (http://asap.sourceforge.net).

Just run `asapscan` with the `-d` command, and save the contents into a text file. Like so:

    asapscan -s N -d song.sap > song.txt

Where `N` is the subsong number (starting from 0), if any. Otherwise, this setting can be omitted. The above should work on both Windows and Linux.

Once the text file is ready, just run POKEY2MIDI on it as per instructions (see "Command line parameters" below).

POKEY2MIDI also accepts bzip2-compressed text files, but that's not necessary. I just added that support so the repository wouldn't be large because of huge text dumps. :P

---
# Command line parameters

    usage: pokey2midi.py [-h] [--all] [--notrim] [--nosplit] [--nomerge]
                         [--usevol] [--useinst] [--short]
                         [--setinst n,n,n,n,n,n,n,n] [--boost factor]
                         [--maxtime time] [--bpm BPM] [--findbpm]
                         [--timebase TIMEBASE]
                         input_file [output_file]

    positional arguments:
      input_file            Input POKEY dump text file.
      output_file           MIDI output file. If not specified, will output to the
                            same path, with a '.mid' extension

    optional arguments:
      -h, --help            show this help message and exit
    
      --all                 Use all notes by always retriggering. Useful for when
                            notes are being missed. Overrides note merging.
      
      --notrim              Do not trim initial silence, which happens by default.
      
      --nosplit             Do not split different polynomial counter settings for
                            channels as separate instrument tracks, which happens
                            by default.
      
      --nomerge             Do not merge volume decays into a single MIDI note,
                            which happens by default. Ignored if --all is used.
      
      --usevol              Use MIDI channel volume instead of note velocity. This
                            is similar to how it happens in the actual chip.
      
      --pitchonly           Completely ignores note volume information, and considers
                            only pitch changes when triggering notes. This is similar
                            to --usevol, but the MIDI file will contain no channel
                            volume MIDI messages.
      
      --useinst             Assign predefined MIDI instruments to emulate the
                            original POKEY sound. Also use --setinst if you wish
                            to define different instruments yourself.
      
      --shortnotes          Assigns notes shorter than 1/k-th of a beat to separate
                            channels. Useful for cleaning up certain songs, but may
                            map certain notes to MIDI percussion (channel 10)
      
      --shortnames          Use shorter MIDI track names.
      
      --setinst n,n,n,n,n,n,n,n
                            Specify which General MIDI instruments to assign to
                            each of the 8 poly settings. No spaces, n from 0 to
                            127. The last three are the most important for melody
                            and default to: square wave=80, brass+lead=87, square
                            wave=80.
      
      --boost factor        Multiply note velocities by a factor. Useful if MIDI
                            is too quiet. Use a large number (> 16) to make all
                            notes have the same max loudness (useful for killing
                            off POKEY effects that don't translate well to MIDI).
      
      --maxtime time        By default, asapscan dumps 15 minutes (!) of POKEY
                            data. Use this to ignore stuff after some point.
      
      --bpm BPM             Assume a given tempo in beats per minute (bpm), as
                            precisely as you want. Default is 60. If the song's
                            bpm is known precisely, this option makes the MIDI
                            notes align with the beats, which makes using the MIDI
                            in other places much easier. Doesn't work if the song
                            has a dynamic tempo.
      
      --findbpm             Attempts to post-process the data to automatically
                            detect tempo/bpm by using a simple algorithm. The best
                            guesses are merely displayed after the conversion. Run
                            again with one of these guesses as a parameter with
                            --bpm to see if events aligned properly. Cannot be
                            used with --all, but might work better with --usevol.
      
      --timebase TIMEBASE   Force a given MIDI timebase, the number of ticks in a
                            beat (quarter note). Default is 480.
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
# Atari SAP Music Archive (ASMA) conversion to MIDI

With many thanks to [Konrad "Gades" Leśniak](https://gadesound.blogspot.com/), the Atari SAP Music Archive (up to November 16 2020) has been converted using POKEY2MIDI! Most of the tracks were converted with the proper BPM correction, so their notes should be aligned to the musical bars. This full archive can be downloaded here: https://atarionline.pl/pliki/gades_asma_38_mid2.zip

For more information and details on how this was achieved, see:
* [Original Atarionline.pl blog post](https://atarionline.pl/v01/index.php?subaction=showfull&id=1604707110&archive=&start_from=0&ucat=1&ct=nowinki)
* [Gades' blog post on the process](https://gadesound.blogspot.com/2020/11/sap-na-midi-najlepszy-sposob.html)

Note that these conversions have used the default parameters for POKEY2MIDI, which may not be exactly ideal for a specific SAP file, or not the kind of MIDI file you wanted. It seems subsongs were converted as well, but appear concatenated in the same file. I am unsure how this changes the BPM alignments, but hopefully, this archive will cover 90% of cases. :)

---

Some tags to help others looking for this program: pokey2mid, sap2mid, sap2midi, POKEY to MID, SAP to MIDI, SAP to MID
