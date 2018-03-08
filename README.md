# pokey2midi
POKEY2MIDI is a tool to convert POKEY register dumps from Atari SAP files into MIDI music files.

POKEY register dumps can be created from Atari SAP files by using `asapscan`, available on the ASAP project (http://asap.sourceforge.net). 

---
# Instructions  

However, `asapscan` is a bit useless as it is, and you'll have to recompile it with a small modification, as described below.

Note: the compilation of ASAP requires Cito (http://cito.sourceforge.net)

The original version of `asapscan` only outputs timestamps with 2 decimal digits of precision, which is insufficient for our purpose.

The relevant lines are found in `asapscan.c`:

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

**Don't forget to remove the colon!** I decided to use it as a way to distinguish the modified dumps.

Compile this and you're good to go!

---

Now, just run `asapscan` with the `-d` command, and save the contents into a text file. Like so:

    asapscan -s N -d song.sap > song.txt

Where `N` is the subsong number (starting from 0), if any. Otherwise, this setting can be omitted. The above should work on both Windows and Linux.

Once the text file is ready, just run POKEY2MIDI on it as per instructions.

The examples given in the `examples` directory were all created with the default settings.

---
# Notes  

This is a work in progress, and some POKEY features are still not properly handled. In particular, I haven't yet figured a good and comprehensive way of dealing with the 0-4 (000 to 010) AUDC polynomial settings, which are used to produce various types of noise.

Right now, I decided to disable it entirely and only deal with polys 5-7 (011 to 111), which are the pure tone and buzzing tone, used for the melody in the vast majority of songs. 

Some note frequencies are also not being mapped properly to anything useful, especially when songs use 16-bit or the 1.79 MHz clock. I opted to omit these for now.

---

Some tags to help others looking for this program: "pokey2mid", "sap2mid", "sap2midi", "POKEY to MID", "SAP to MIDI", "SAP to MID"
