1. Install node-red, nginx, 
2. Install git
	sudo apt update
	sudo apt install git

3. Add username and password to git global
	git config --global user.name "Stephen Fewings"
    git config --global user.email "sfewings@iinet.net.au"

4. Create SSH key and add to github
	mkdir ~/.ssh
    chmod 0700 ~/.ssh
    ssh-keygen -t rsa -C "sfewings@iinet.net.au"  
	//note use default name and passwode of none
	copy contents of id_rsa.pub to your github ssh public keys

6. Create a share/lib directory in the home directory (or anywhere. But be sure to expose through samba)
	mkdir -p ~/share/libs
	
5. clone paho_mqtt_c and paho.mqtt.cpp from github
	cd ~/share/libs
	git clone git@github.com:eclipse/paho.mqtt.c.git
	git clone https://github.com/eclipse/paho.mqtt.cpp.git
	
6. 	install c and c++ build environment
	See https://github.com/eclipse/paho.mqtt.c
	apt-get install build-essential gcc make cmake cmake-gui cmake-curses-gui
	apt-get install fakeroot fakeroot devscripts dh-make lsb-release
	apt-get install libssl-dev
	apt-get install doxygen graphviz

7. Build paho_mqtt_c
	cd paho.mqtt.c
	use cmake to build the makefiles in folder "build"
	 cmake -B build
    compile the library
	 sudo cmake --build build/ --target install

8. Build paho.mqtt.cpp	
	cd paho.mqtt.c
	use cmake to build the makefiles in folder "build"
	 cmake -B build
	use cmake gui to set PAHO_MQTT_C_INCLUDE_DIRS 
		PAHO_MQTT_C_INCLUDE_DIRS:PATH=/usr/local/include
		PAHO_MQTT_C_LIBRARIES:FILEPATH=/usr/local/lib/libpaho-mqtt3c.so    
	compile the library
	 sudo cmake --build build/ --target install

9. Clone emon_suite from GitHub
	git clone https://github.com/sfewings/emon_Suite.git
	
10.	Build /share/Emon_LogToJson using /bin/sh GCC_Build.txt.sh from inside path /share/Emon_LogToJson/

11.	Build /share/Emon_SerialToMQTT using /bin/sh GCC_Build.txt.sh in folder /share/Emon_SerialToMQTT/

12. To run manually, use the command lines in /share/Emon_LogToJson/Emon_LogToJson.sh and /share/Emon_SerialToMQTT/Emon_SerialToMQTT.sh
	Note: Required adding shared library path for libpaho-mcttpp3.so.1  https://stackoverflow.com/a/21173918
	 LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib
	 export LD_LIBRARY_PATH

13.	Enable Emon_LogToJson and Emon_SerialToMQTT
	/etc/systemd/system/Emon_LogToJson.service
	/etc/systemd/system/Emon_SerialToMQTT.service
	#To install 	1. sudo copy to /etc/systemd/system
	#		2. sudo systemctl enable Emon_LogToJson
	//note sympolic link to files in /etc/systemd/system/multi-user.target.wants

14. 	Install nginx
	Copy contents of /etc/nginx/sites-available/default
	This enables shannstainable.fewings.org http and https traffic to node-red on port :1880\ui

15. 	Enable projects in node-red
	in /home/pi/.node-red/settings.js     
	// Customising the editor
    editorTheme: {
        projects: {
            // To enable the Projects feature, set this value to true
            enabled: true
			
16.	Create SSL certificate for shannstainable.fewings.org using letsencrypt
	/etc/letsencrypt/live/shannstainable.fewings.org/cert.pem
	Set up renewal every 40 days by placing /etc/letsencrypt/renewal/shannstainable.fewings.org.conf

17. Auto DNS shannstainable.fewings.org
	Add this line to the crontab file. Run crontab -e
	#run the dyndns every 30 minutes
	30 * * * * /usr/bin/curl --insecure -d "u=steve&p=5yufdsHyf6" https://mike.fewings.org/dyndns.php >> /share/log/curl_cron.log 2>&1
	Note that it logs each execution in the file /share/log/curl_cron.log
	
18. Update NodeRed GIT repo from RaspPi
	
	
	