import glob
import os
import subprocess
import bz2

# .sap files in the sap directory
saps = glob.glob(os.path.join("sap","*.sap"))

# Path for asapscan executable
asapscan_path = os.path.join("..","bin","asapscan-highprecision")

# Python 3 command/path
python3 = "python"

# Path to pokey2midi.py
pokey2midi_path = os.path.join("..","pokey2midi.py")
# Options to use
pokey2midi_options = ["--useinst", "--usevol", "--maxtime", "300"]

# Which subsongs to extract from each file. Defaults to [0]
subsongs = {
	"Draconus": [0],
	"Global_War": [0],
	"His_Dark_Majesty_Ingame": [3],
	"Maxi_2": [0,1],
	"Pion": [0,1],
	"Yoomp": [0]
}

print("Generating samples...")

for sap in saps:
	name = os.path.splitext(os.path.basename(sap))[0]
	if name in subsongs:
		subs = subsongs[name]
	else:
		subs = [0]
	print("> Converting %s, subsongs: %s " % (name, ", ".join([str(s) for s in subs])) )
	
	for s in subs:
		dump_path = os.path.join("dump",name+"_(subsong %d).txt.bz2" % s)
		midi_path = os.path.join("midi",name+"_(subsong %d).mid" % s)
		
		if not os.path.isfile(dump_path):
			print("Dumping subsong %d" % s )
			data = subprocess.run([asapscan_path,'-s',"%d"%s,'-d',sap],stdout=subprocess.PIPE).stdout
			with open(dump_path,"wb") as zdump:
				zdump.write(bz2.compress(data))
		else:
			print("Subsong %d already dumped" % s )
		
		print("Converting subsong %d... " % s)
		
		log = subprocess.run(
			[python3, pokey2midi_path] + pokey2midi_options + [dump_path, midi_path],
			stdout=subprocess.PIPE
		)
		
		print("OK")
		
	print("Done.")




