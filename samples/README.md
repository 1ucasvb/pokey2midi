The small Python script `create_samples.py` automatically:

1. Runs `asapscan.exe` from the `bin` folder on every `.sap` file on the `sap` directory, then saves the bzip2-compressed dumps to the `dump` folder
2. Runs `pokey2midi.py` on each dump, and saves the `.mid` file to the `midi` directory

POKEY2MIDI is ran with the following settings: `--useinst`, `--usevol` (to best simulate the original POKEY sounds) and `--maxtime 300` so we don't create 15 minute-long MIDIs.

Since it uses `asapscan.exe`, it will only work on Windows. You can also compile your own version and configure its location from within the script.