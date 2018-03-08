# pokey2midi
POKEY2MIDI is a tool to convert POKEY register dumps from Atari SAP files into MIDI music files.

POKEY register dumps can be created from Atari SAP files by using `asapscan`, available on the ASAP project (http://asap.sourceforge.net).

Just run `asapscan` with the `-d` command, and save the contents into a text file. Like so:

    asapscan -s N -d song.sap > song.txt

Where `N` is the subsong number (starting from 0), if any. Otherwise, this setting can be omitted. The above should work on both Windows and Linux.

Once the text file is ready, just run POKEY2MIDI on it as per instructions.

The examples given were all created with the default settings.

This is a work in progress, and some POKEY features are still not properly handled.

Some tags to help others looking for this program: "pokey2mid", "sap2mid", "sap2midi", "POKEY to MID", "SAP to MIDI", "SAP to MID"
