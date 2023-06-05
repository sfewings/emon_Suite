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
	chdir ~./ssh
    ssh-keygen -t rsa -C "sfewings@iinet.net.au"  
	//note use default name and passwode of none
	copy contents of id_rsa.pub to your github ssh public keys

5. Create a /share directory for the contents of emon
	sudo mkdir /share
	sudo chmod 777 /share

6. Clone emon_Suite to /share
	cd /share
	git clone git@github.com:sfewings/emon_Suite.git
   or to clone without account
	git clone https://github.com/sfewings/emon_Suite.git

7. Install and configure samba to make share available
	sudo apt-get install samba samba-common-bin
	sudo nano /etc/samba/smb.conf
	At the bottom of this file add the following lines (If on a safe network!)
		[share]
			comment = Pi shared folder
			path = /share
			browseable = yes
			writeable = Yes
			only guest = no
			create mask = 0777
			directory mask = 0777
			public = yes
			guest ok = yes
	Add a samba user to allow access to samba (user is pi)
		sudo smbpasswd -a pi
	restart the samba service
		sudo smbcontrol smbd reload-config


8. Install docker and docker-compose
	curl -fsSL https://get.docker.com -o get-docker.sh
	sudo sh get-docker.sh
   Add pi user permissions to start containers
	sudo usermod -aG docker pi
   Restart
	shutdown -r now
   Install Docker Compose
	sudo pip3 install docker-compose
  or
    sudo apt install docker-compose	

9. Create a share/lib directory in the home directory (or anywhere. But be sure to expose through samba)
	mkdir -p /share/libs
	chmod 777 
	
10.clone paho_mqtt_c and paho.mqtt.cpp from github
	cd ~/share/libs
	git clone git@github.com:eclipse/paho.mqtt.c.git  
		or 
	git clone https://github.com/eclipse/paho.mqtt.c.git
	git clone https://github.com/eclipse/paho.mqtt.cpp.git
	
11.	install c and c++ build environment
	See https://github.com/eclipse/paho.mqtt.c
	apt-get install build-essential gcc make cmake cmake-gui cmake-curses-gui
	apt-get install fakeroot fakeroot devscripts dh-make lsb-release
	apt-get install libssl-dev
	apt-get install doxygen graphviz

12. Build paho_mqtt_c
	cd paho.mqtt.c
	make
	sudo make install

	    or
	
	cd paho.mqtt.c
	use cmake to build the makefiles in folder "build"
	 cmake -B build
    compile the library
	 sudo cmake --build build/ --target install

13. Build paho.mqtt.cpp	
	cd paho.mqtt.cpp
	use cmake to build the makefiles in folder "build"
	 cmake -B build
	use cmake gui to set PAHO_MQTT_C_INCLUDE_DIRS 
		PAHO_MQTT_C_INCLUDE_DIRS:PATH=/usr/local/include
		PAHO_MQTT_C_LIBRARIES:FILEPATH=/usr/local/lib/libpaho-mqtt3c.so    
	compile the library
	 sudo cmake --build build/ --target install

14. Clone emon_suite from GitHub
	git clone https://github.com/sfewings/emon_Suite.git
	
15.	Build /share/Emon_LogToJson using /bin/sh GCC_Build.txt.sh from inside path /share/Emon_LogToJson/

16.	Build /share/Emon_SerialToMQTT using /bin/sh GCC_Build.txt.sh in folder /share/Emon_SerialToMQTT/

17. To run manually, use the command lines in /share/Emon_LogToJson/Emon_LogToJson.sh and /share/Emon_SerialToMQTT/Emon_SerialToMQTT.sh
	Note: Required adding shared library path for libpaho-mcttpp3.so.1  https://stackoverflow.com/a/21173918
	 LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib
	 export LD_LIBRARY_PATH

18.	Enable Emon_LogToJson and Emon_SerialToMQTT
	/etc/systemd/system/Emon_LogToJson.service
	/etc/systemd/system/Emon_SerialToMQTT.service
	#To install 	1. sudo copy to /etc/systemd/system
	#		2. sudo systemctl enable Emon_LogToJson
	//note sympolic link to files in /etc/systemd/system/multi-user.target.wants

19. 	Install nginx
	sudo apt install nginx
	Copy contents of /etc/nginx/sites-available/default
	This enables shannstainable.fewings.org http and https traffic to node-red on port :1880\ui

20. 	Enable projects in node-red
	in /home/pi/.node-red/settings.js     
	// Customising the editor
    editorTheme: {
        projects: {
            // To enable the Projects feature, set this value to true
            enabled: true
			
21.	Create SSL certificate for shannstainable.fewings.org using letsencrypt
	/etc/letsencrypt/live/shannstainable.fewings.org/cert.pem
	Set up renewal every 40 days by placing /etc/letsencrypt/renewal/shannstainable.fewings.org.conf
	Maybe required?? install sudo apt-get install python3-certbot-nginx
	Add this to the crontab file. Run crontab -e 
	# run the certbot renewal on the 1st day of each month. Be sure to start and stop nginx so certbot can use port 80
	* * * 1 * certbot renew --pre-hook "service nginx stop" --post-hook "service nginx start"

22. Auto DNS shannstainable.fewings.org
	Add this line to the crontab file. Run crontab -e
	#run the dyndns every 30 minutes
	30 * * * * date >> /share/log/curl_cron.log && /usr/bin/curl --insecure -d "u=steve&p=5yufdsHyf6" https://mike.fewings.org/dyndns.php >> /share/log/curl_cron.log 2>&1;echo "" >> /share/log/curl_cron.log
	Note that it logs each execution in the file /share/log/curl_cron.log
	
23. Update NodeRed GIT repo from RaspPi
	

24. Including InfluxDB library for C++ (Not used for emon_suite)
	Read instructuons at https://github.com/offa/influxdb-cxx
	prerequisits 
	  curl:- git clone https://github.com/curl/curl.git
			cmake .
			sudo make install
	  boost:- sudo apt-get install libboost1.67-all
	  Catch2:- git clone https://github.com/catchorg/Catch2
  			cd Catch2/
  			mkdir build && cd build
			cmake ..
  			make
  			sudo make install

	git clone https://github.com/offa/influxdb-cxx.git
	cd influxdb-cxx
	mkdir build && cd build
	cmake ..	
	open cmake GUI and turn off INFLUXCXX_SYSTEMTEST and INFLUXCXX_TESTING to avoid requireing Catch2, trompeloeil and other testing frameworks
	