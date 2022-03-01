#!/bin/env python3

import os
from ruamel.yaml import YAML
import getpass

print("This script will create a new instance of synapse")
while True:
	yn = input("Would you like to proceed? [yes/no/default=yes]  ")
	if yn == "yes":
		break
	elif yn == "no":
		exit(0)
	elif yn == "":
		break
	else:
		print("Please answer 'yes' or 'no'")
#######################################################################
print()
print("Pleas choose the server name for your instance.")
print()
print("The server_name cannot be changed later so it is important to")
print("configure this correctly before you start Synapse. It should be all")
print("lowercase and may contain an explicit port.")
print("Examples: matrix.org, localhost:8080")
print()

while True:
	servername = input()
	yn = input("Is '" + servername + "' correct? [yes/no/default=no]  ")
	if yn == "yes":
		break
	elif yn == "no":
		print("Pleas choose the server name for your instance.")
	elif yn == "":
		print("Pleas choose the server name for your instance.")
	else:
		print("Please answer 'yes' or 'no'")

######################################################################

portnr = 0
while True:
	port = input("On what port should this instance run? [1 - 65535]  ")
	try:
		portnr = int(port)
	except:
		print("Value '" + port + "' is not valid")
	else:
		if portnr not in range(1,65536):
			print("Value '" + port + "' is not valid")
		else:
			yn = input("Is port " + str(portnr) + " correct? [yes/no/default=no]  ")
			if yn == "yes":
				break
			else:
				pass

######################################################################

path = os.path.join(os.path.dirname(__file__), servername)
os.mkdir(path)

os.system("python -m synapse.app.homeserver --server-name " + servername + " --config-path " + servername + "/homeserver.yaml --generate-config --report-stats=no")

print()
######################################################################

media_store_path = os.path.join(path,'media_store')
while True:
	media_path = input("Where should we store media? [" + str(os.path.abspath(media_store_path)) + "]  ")
	if media_path == "":
		media_path = str(media_store_path)
	yn = input("Is " + media_path + " correct? [yes/no/default=no]")
	if yn == "yes":
		media_store_path = os.path.join(media_path)
		break
	else:
		pass
if not os.path.exists(media_store_path):
	os.makedirs(media_store_path)
#################################

yaml = YAML()
config = ''
with open(servername + "/homeserver.yaml", 'r') as file:
	config = yaml.load(file)

config['listeners'][0]['port'] = portnr
config['listeners'][0]['bind_addresses'].clear()
config['listeners'][0]['bind_addresses'].append('0.0.0.0')
config['media_store_path'] = media_store_path

with open(servername + "/homeserver.yaml", 'w') as file:
	yaml.dump(config,file)

yaml = YAML()
config = ''
with open(servername + "/" + servername + ".log.config", 'r') as file:
        config = yaml.load(file)

config['handlers']['file']['filename'] = "./homeserver.log"

with open(servername + "/" + servername + ".log.config", 'w') as file:
        yaml.dump(config,file)

######################################################################
# Create service
unit = """\
[Unit]
Description=Synapse Server $server$
After=network.target
StartLimitIntervalSec=0
[Service]
Type=simple
Restart=always
RestartSec=1
User=$user$
ExecStart=/bin/env bash $runscript$

[Install]
WantedBy=multi-user.target

"""

unit = unit.replace("$server$", servername)
unit = unit.replace("$user$", getpass.getuser())
unit = unit.replace("$runscript$", str(os.path.abspath(os.path.join(path, "run.sh"))))
with open(os.path.join(path, "synapse-" + servername + ".service"), 'w') as f:
	f.write(unit)

os.chmod(os.path.join(path, "synapse-" + servername + ".service"), 493)

runscript = """\
#!/bin/env bash

cd $dir$
source ../env/bin/activate

python -m synapse.app.homeserver --config-path homeserver.yaml

"""

runscript = runscript.replace("$dir$", os.path.abspath(path))
with open(os.path.join(path, "run.sh"), 'w') as f:
	f.write(runscript)

os.chmod(os.path.join(path, "run.sh"), 493)

print("thats it :) ")
print()
print("next steps:")
print("\tcheck your homeserver.yaml and prepare the following:")
print("\t-Database config")
print("\t-OIDC config")
print("\t-Turn Server config")
print()
